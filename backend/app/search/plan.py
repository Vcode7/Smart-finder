"""
app/search/plan.py
~~~~~~~~~~~~~~~~~~
Turns a search request — typed text plus any attached image, audio, video or document —
into the signals the engine searches with. Everything here is local and rule-based
(no LLM in the critical path).

Text understanding:
  * filters      type:pdf  kind:video  in:"Holiday photos"  folder:trips/goa
                 after:2023-01-01  before:2024  year:2022
  * phrases      "exact words" (also searched as phrases)
  * hints        "photo of…", "video where…", "said…", "pdf about…" reweight retrievers;
                 they never hide results
  * folders      words naming a library's folders ("dancing at Rahul wedding" with
                 Events/Rahul Wedding/) scope the search there: files below the folder
                 lead, ranked by the other words (matched per library by the engine,
                 see folders.py); they never hide results either
Attached files:
  * image    → image vector (with typed words: also one picture+words vector), faces
               (identity vectors), perceptual hash, OCR text
  * audio    → Whisper transcript (searched as text)
  * video    → transcript of its soundtrack + a few keyframes (as images)
  * document → its title and first passages, each searched separately
"""
from __future__ import annotations

import contextlib
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.search.constants import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, classify_extension, tokenize

KINDS = {"document", "image", "video", "audio"}
COMPOSE_IMAGE_SIDE = 768        # attached picture kept this large for a picture+words query
_KIND_ALIASES = {
    "doc": "document", "docs": "document", "document": "document", "documents": "document", "pdf": "document",
    "image": "image", "images": "image", "photo": "image", "photos": "image", "picture": "image", "pictures": "image",
    "video": "video", "videos": "video", "movie": "video", "movies": "video",
    "audio": "audio", "music": "audio", "song": "audio", "songs": "audio", "recording": "audio", "recordings": "audio",
}
_FILTER_RE = re.compile(
    r'(?<!\S)(type|ext|kind|is|in|library|folder|after|before|year):("([^"]*)"|\S+)', re.IGNORECASE
)
_PHRASE_RE = re.compile(r'"([^"]{2,})"')

# Modality hints: retriever weight multipliers (never filters)
_HINTS: List[Tuple[re.Pattern, Dict[str, float]]] = [
    (re.compile(r"\b(photos?|pictures?|pics?|images?|screenshots?|photographs?|selfies?|तस्वीर|फोटो)\b", re.I),
     {"clip_text": 1.6, "compose": 1.3}),
    (re.compile(r"\b(videos?|clips?|footage|scenes?|movies?|वीडियो)\b", re.I),
     {"clip_text": 1.3, "transcript": 1.2}),
    (re.compile(r"\b(said|says|saying|talks? about|talking about|mentions?|mentioned|speech|spoke|discuss(?:ed|es)?|"
                r"podcast|interview|lecture|recording|voice|बोला|कहा)\b", re.I),
     {"transcript": 1.6}),
    (re.compile(r"\b(documents?|pdfs?|reports?|papers?|pages?|slides?|spreadsheets?|letters?|invoices?)\b", re.I),
     {"bm25": 1.2, "dense": 1.2}),
]
# Sounds: switches on CLAP sound search ("dog barking", "applause", "sound of rain")
_SOUND_HINT = re.compile(
    r"\b(sounds?|noises?|noisy|bark(?:s|ing)?|meow(?:s|ing)?|music|musical|songs?|singing|sings?|applause|"
    r"clapp(?:ing)?|laugh(?:s|ing|ter)?|cry(?:ing)?|crying|scream(?:s|ing)?|sirens?|horns?|honk(?:s|ing)?|rain|"
    r"thunder|engines?|birds?|chirp(?:s|ing)?|explosions?|gunshots?|whistl(?:e|es|ing)|bells?|drums?|guitar|"
    r"piano|violin|flute|cheer(?:s|ing)?|footsteps|knock(?:s|ing)?|alarms?|beep(?:s|ing)?|ringtones?|traffic|"
    r"waves|wind|crowd|baby|dogs?|cats?|आवाज़|आवाज|संगीत|गाना|गीत|हंसी|तालियां|बारिश)\b", re.I)


@dataclass
class Filters:
    kinds: Set[str] = field(default_factory=set)
    exts: Set[str] = field(default_factory=set)
    libraries: Set[str] = field(default_factory=set)      # ids or names (resolved by the engine)
    folder: Optional[str] = None
    after: Optional[str] = None                           # ISO date, inclusive
    before: Optional[str] = None                          # ISO date, exclusive

    def active(self) -> bool:
        return bool(self.kinds or self.exts or self.folder or self.after or self.before)

    def describe(self) -> Dict[str, Any]:
        return {k: (sorted(v) if isinstance(v, set) else v) for k, v in self.__dict__.items() if v}


@dataclass
class ImageSignal:
    label: str
    clip_vec: Optional[List[float]] = None
    compose_vec: Optional[List[float]] = None   # the picture and the typed words as one query
    faces: List[List[float]] = field(default_factory=list)
    phash: Optional[int] = None
    ocr_text: str = ""
    person: Optional[str] = None          # set when the faces come from a named person
    image: Optional[Any] = field(default=None, repr=False)   # PIL thumbnail, kept until the plan is built


@dataclass
class QueryPlan:
    raw_text: str = ""
    text: str = ""                                        # typed text without filter syntax
    phrases: List[str] = field(default_factory=list)
    text_vec: Optional[List[float]] = None
    clip_text_vec: Optional[List[float]] = None
    images: List[ImageSignal] = field(default_factory=list)
    extra: List[Tuple[str, str, float]] = field(default_factory=list)    # (label, text, weight)
    extra_vecs: List[Optional[List[float]]] = field(default_factory=list)
    filters: Filters = field(default_factory=Filters)
    boosts: Dict[str, float] = field(default_factory=dict)
    exclude_sources: Set[str] = field(default_factory=set)
    rerank_query: str = ""                                # what the reranker judges passages against
    visual_text: str = ""                                 # text for image search (names of people removed)
    clap_text_vec: Optional[List[float]] = None           # the text as a sound (when it describes one)
    sound_vecs: List[List[float]] = field(default_factory=list)   # attached audio as sound
    people: List[Dict[str, Any]] = field(default_factory=list)    # people named in the text
    folder_scopes: Dict[str, List[Any]] = field(default_factory=dict)   # library id → FolderMatch list
    content_text: str = ""                                # the text without the words naming folders
    content_text_vec: Optional[List[float]] = None
    content_clip_vec: Optional[List[float]] = None
    trace: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_faces(self) -> bool:
        """Faces from an attached picture ("this person…"), which also filter the results."""
        return any(img.faces and not img.person for img in self.images)

    @property
    def kind(self) -> str:
        parts = []
        if self.text:
            parts.append("text")
        if self.images:
            parts.append("face" if self.has_faces and not any(i.clip_vec for i in self.images) else "image")
        if self.sound_vecs or any(label.startswith("speech") for label, _, _ in self.extra):
            parts.append("audio")
        if any(label.startswith("document") for label, _, _ in self.extra):
            parts.append("document")
        return "+".join(parts) or "empty"


# ── text ─────────────────────────────────────────────────────────────────────
def _date_bound(value: str, end: bool = False) -> Optional[str]:
    value = value.strip()
    for fmt, step in (("%Y-%m-%d", "day"), ("%Y-%m", "month"), ("%Y", "year")):
        try:
            d = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if end:  # "before:2024" means before 2024-01-01; "year:2023" ends at 2024-01-01
            if step == "year":
                d = d.replace(year=d.year + 1)
            elif step == "month":
                d = d.replace(year=d.year + (d.month // 12), month=d.month % 12 + 1)
        return d.date().isoformat()
    return None


def parse_text(raw: str) -> Tuple[str, List[str], Filters, Dict[str, float]]:
    filters = Filters()

    def take(m: re.Match) -> str:
        key = m.group(1).lower()
        value = (m.group(3) if m.group(3) is not None else m.group(2)).strip()
        if not value:
            return " "
        if key in ("type", "ext"):
            filters.exts.update(v.lstrip(".").lower() for v in value.split(","))
        elif key in ("kind", "is"):
            for v in value.split(","):
                kind = _KIND_ALIASES.get(v.lower())
                if kind:
                    filters.kinds.add(kind)
        elif key in ("in", "library"):
            filters.libraries.add(value)
        elif key == "folder":
            filters.folder = value.strip("/\\").replace("\\", "/")
        elif key == "after":
            filters.after = _date_bound(value) or filters.after
        elif key == "before":
            filters.before = _date_bound(value, end=False) or filters.before
        elif key == "year":
            filters.after, filters.before = _date_bound(value), _date_bound(value, end=True)
        return " "

    text = _FILTER_RE.sub(take, raw or "")
    phrases = [p.strip() for p in _PHRASE_RE.findall(text) if p.strip()]
    text = re.sub(r"\s+", " ", text.replace('"', " ")).strip()
    boosts: Dict[str, float] = {}
    for pattern, weights in _HINTS:
        if pattern.search(text):
            for k, v in weights.items():
                boosts[k] = max(boosts.get(k, 1.0), v)
    if _SOUND_HINT.search(text):
        boosts["sound"] = 1.0
    return text, phrases, filters, boosts


# ── attached files ───────────────────────────────────────────────────────────
def _image_signal(image_bytes: bytes, label: str) -> Optional[ImageSignal]:
    from app.ingest.extract import open_image
    from app.ingest.pipeline import FACE_MIN_SCORE, FACE_MIN_SIZE_PX, OCR_TEXT_GATE, _image_hashes
    from app.search import model_pipeline as mp
    try:
        img = open_image(image_bytes, max_side=2048)
    except Exception:
        return None
    sig = ImageSignal(label=label)
    vecs = mp.get_image_embeddings_batch([img])
    sig.clip_vec = vecs[0] if vecs else None
    sig.image = img.copy()
    sig.image.thumbnail((COMPOSE_IMAGE_SIDE, COMPOSE_IMAGE_SIDE))
    sig.phash, _ = _image_hashes(img)
    for face in mp.detect_and_embed_faces(img, min_confidence=0.5, model_name=mp.LIBRARY_FACE_MODEL):
        if int(face.get("size_px") or 0) >= FACE_MIN_SIZE_PX and float(face.get("confidence") or 0) >= FACE_MIN_SCORE:
            sig.faces.append(face["embedding"])
    likely = mp.text_likelihood(sig.clip_vec)
    if likely is None or likely >= OCR_TEXT_GATE:
        text = mp.run_ocr(img).strip()
        if len(text) >= 12 and len(text.split()) >= 2:
            sig.ocr_text = text
    return sig


def _media_signals(data: bytes, name: str, plan: QueryPlan, video: bool) -> None:
    """Transcribe an attached audio/video clip; for video also sample keyframes."""
    from app.search import model_pipeline as mp
    suffix = Path(name).suffix or (".mp4" if video else ".webm")
    with tempfile.TemporaryDirectory(prefix="sf_query_") as tmp:
        path = Path(tmp) / f"query{suffix}"
        path.write_bytes(data)
        try:
            result = mp.transcribe_media(str(path))
        except Exception as e:
            result = {}
            plan.trace.setdefault("notes", []).append(f"speech not transcribed: {e}")
        transcript = " ".join(s["text"] for s in result.get("segments") or []).strip()
        if transcript:
            plan.extra.append(("speech", transcript[:2000], 1.0))
            plan.trace["speech"] = transcript[:300]
            plan.trace["speechLanguage"] = result.get("language")
        # The clip as a sound too: finds the same or similar sounds (birdsong, a song, an alarm)
        sound = mp.clap_audio_embedding(str(path))
        if sound is not None:
            plan.sound_vecs.append(sound)
        if video:
            try:
                from app.ingest.extract import _frames_by_seeking, _Keyframes, _probe
                duration = _probe(path).get("duration") or 0.0
                frames = _Keyframes(Path(tmp) / "cache", Path(tmp) / "work")
                points = [0.5] + ([duration / 2, max(0.5, duration - 1.0)] if duration > 4 else [])
                _frames_by_seeking(path, points, frames)
                for i, it in enumerate(frames.items[:3]):
                    work = Path(tmp) / "work" / f"{it['name']}.jpg"
                    sig = _image_signal(work.read_bytes(), f"video frame {i + 1}")
                    if sig:
                        plan.images.append(sig)
            except Exception as e:
                plan.trace.setdefault("notes", []).append(f"video frames skipped: {e}")


def _document_signals(data: bytes, name: str, plan: QueryPlan) -> None:
    from app.ingest.chunking import chunk_text
    from app.ingest.extract import extract
    ext = Path(name).suffix.lstrip(".").lower() or "txt"
    with tempfile.TemporaryDirectory(prefix="sf_query_") as tmp:
        path = Path(tmp) / f"query.{ext}"
        path.write_bytes(data)
        try:
            ex = extract("document", path, ext, Path(tmp) / "cache")
        except Exception as e:
            plan.trace.setdefault("notes", []).append(f"document not readable: {e}")
            return
        try:
            pieces: List[str] = []
            for block in ex.iter_blocks():
                pieces.extend(chunk_text(block.text))
                if len(pieces) >= 3:
                    break
        finally:
            ex.cleanup()
    stem = Path(name).stem.replace("_", " ").replace("-", " ")
    if stem.strip():
        plan.extra.append(("document title", stem, 0.5))
    for i, piece in enumerate(pieces[:3]):
        plan.extra.append((f"document passage {i + 1}", piece, 0.8 if i == 0 else 0.6))
    if pieces:
        plan.trace["document"] = pieces[0][:300]


def attach_file(plan: QueryPlan, data: bytes, name: Optional[str], mime: Optional[str]) -> None:
    name = name or ("query.jpg" if (mime or "").startswith("image/") else "query.bin")
    ext = Path(name).suffix.lstrip(".").lower()
    kind = classify_extension(ext)
    mime = (mime or "").lower()
    if mime.startswith("image/") or ext in IMAGE_EXTENSIONS:
        sig = _image_signal(data, name)
        if sig:
            plan.images.append(sig)
            if sig.ocr_text:
                plan.extra.append(("image text", sig.ocr_text[:1500], 0.8))
                plan.trace["ocr"] = sig.ocr_text[:300]
            plan.trace["faces"] = len(sig.faces)
    elif mime.startswith("audio/") or ext in AUDIO_EXTENSIONS:
        _media_signals(data, name, plan, video=False)
    elif mime.startswith("video/") or ext in VIDEO_EXTENSIONS:
        _media_signals(data, name, plan, video=True)
    elif kind == "document":
        _document_signals(data, name, plan)
    else:
        plan.trace.setdefault("notes", []).append(f"'{name}' is not a supported query file")


# ── assembly ─────────────────────────────────────────────────────────────────
def build_plan(text: str = "", files: Optional[List[Tuple[bytes, Optional[str], Optional[str]]]] = None,
               filters: Optional[Filters] = None) -> QueryPlan:
    """Blocking (runs models); call from a worker thread."""
    from app.search import model_pipeline as mp
    clean, phrases, parsed, boosts = parse_text(text)
    if filters is not None:
        parsed.kinds |= filters.kinds
        parsed.exts |= filters.exts
        parsed.libraries |= filters.libraries
        parsed.folder = filters.folder or parsed.folder
        parsed.after = filters.after or parsed.after
        parsed.before = filters.before or parsed.before
    plan = QueryPlan(raw_text=text or "", text=clean, phrases=phrases, filters=parsed, boosts=boosts)
    pictures = any(data and _shows_pictures(name, mime) for data, name, mime in files or [])
    with mp.pictures_on_gpu() if pictures else contextlib.nullcontext():
        for data, name, mime in files or []:
            if data:
                attach_file(plan, data, name, mime)
        finish_plan(plan)
    return plan


def _shows_pictures(name: Optional[str], mime: Optional[str]) -> bool:
    ext = Path(name or "").suffix.lstrip(".").lower()
    return (mime or "").lower().startswith(("image/", "video/")) or ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS


def _people_in_text(plan: QueryPlan) -> None:
    """People named in the text are searched by face; image search looks for the rest."""
    try:
        from app.library.manager import get_library_manager
        from app.people.cluster import people_named_in, person_face_vectors
        named = people_named_in(plan.text)
    except Exception:
        return
    visual = plan.text
    for person in named:
        vectors = person_face_vectors(get_library_manager(), person["id"]) or (
            [person["centroid"]] if person.get("centroid") else [])
        if not vectors:
            continue
        plan.images.append(ImageSignal(label=f"person: {person['name']}", faces=vectors, person=person["name"]))
        plan.people.append({"id": person["id"], "name": person["name"]})
        visual = re.sub(rf"(?i)\b{re.escape(person['match'])}\b", " ", visual)
    plan.visual_text = re.sub(r"\s+", " ", visual).strip()
    if plan.people:
        plan.trace["people"] = [p["name"] for p in plan.people]


def _only_hints(text: str) -> bool:
    """Nothing left to search for but kind words ("photos from diwali" → "photos")."""
    rest = text
    for pattern, _ in _HINTS:
        rest = pattern.sub(" ", rest)
    return not tokenize(rest)


def apply_folder_scopes(plan: QueryPlan, scopes: Dict[str, List[Any]], library_names: Dict[str, str]) -> None:
    """
    Folders the text names (library id → FolderMatch list): the words that named them
    are taken out, and the rest is embedded to rank the files inside. Blocking.
    """
    from app.search import model_pipeline as mp
    from app.search.folders import without_words
    scopes = {lib_id: found for lib_id, found in scopes.items() if found}
    plan.folder_scopes = scopes
    if not scopes:
        return
    matched = {w for found in scopes.values() for m in found for w in m.matched}
    rest = without_words(plan.text, matched)
    plan.content_text = "" if _only_hints(rest) else rest
    if plan.content_text:
        plan.content_text_vec = mp.get_text_query_embedding(plan.content_text)
        plan.content_clip_vec = mp.get_multimodal_text_embedding(plan.content_text)
    plan.trace["folders"] = [m.describe(library_names.get(lib_id, "")) for lib_id, found in scopes.items() for m in found]
    plan.trace["folderQuery"] = plan.content_text


def finish_plan(plan: QueryPlan) -> None:
    """Compute embeddings for the plan's text and extra passages."""
    from app.search import model_pipeline as mp
    if plan.text:
        _people_in_text(plan)
        plan.text_vec = mp.get_text_query_embedding(plan.text)
        visual = plan.visual_text if plan.people else plan.text
        if visual:
            plan.clip_text_vec = mp.get_multimodal_text_embedding(visual)
            # "This photo, but at night": the picture and the words as one query
            for img in plan.images:
                if img.image is not None and img.clip_vec is not None:
                    img.compose_vec = mp.get_composed_query_embedding(img.image, visual)
        if "sound" in plan.boosts:
            plan.clap_text_vec = mp.clap_text_embedding(plan.text)
    for img in plan.images:
        img.image = None
    plan.extra_vecs = [mp.get_text_query_embedding(t[:1500]) for _, t, _ in plan.extra]
    # What passages are judged against: the typed words, else what the attachment says
    if not plan.rerank_query:
        if plan.text:
            plan.rerank_query = plan.text
        else:
            for preferred in ("speech", "document passage 1", "image text"):
                hit = next((t for label, t, _ in plan.extra if label == preferred), None)
                if hit:
                    plan.rerank_query = hit[:600]
                    break
    plan.trace["filters"] = plan.filters.describe()
    plan.trace["queryKind"] = plan.kind
