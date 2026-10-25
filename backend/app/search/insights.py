"""
app/search/insights.py
~~~~~~~~~~~~~~~~~~~~~~
What a file is about, from what the index already holds, with no model involved.

`get_insights` returns the topics and events of one source, cached in the library's
`source_insights` table and tied to the file's fingerprint (a changed file is derived
again). Topics come from headings, captions, OCR, the file and folder names, people
recognised in the file and the most characteristic words of its text. The summary job
later stores better ones from the LLM (origin 'llm'), which are never replaced by these.

`build_doc_context` and `extractive_summary` give the summary job its input and its
fallback, again straight from the indexed chunks.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.library.manager import Library
from app.search.constants import STOPWORDS

MAX_TOPICS = 6
DERIVE_VERSION = "#t2"      # bump when derive_topics changes, so cached index-derived topics are redone
MAX_EVENTS = 3

_WORD = re.compile(r"[^\W\d_][\w'-]*", re.UNICODE)        # starts with a letter (Latin or Devanagari)
_NAMED = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+(?:of|the|and|de|for)\s+|\s+)(?:[A-Z][a-z]{2,}\s+(?:(?:of|the|and|de|for)\s+)?)*[A-Z][a-z]{2,}\b")
_EVENT_WORDS = (
    "wedding", "marriage", "reception", "conference", "meeting", "festival", "ceremony", "summit", "exam",
    "examination", "election", "birthday", "anniversary", "workshop", "seminar", "rally", "protest", "trip",
    "tour", "match", "tournament", "concert", "launch", "inauguration", "annual day", "graduation", "farewell",
    "puja", "diwali", "holi", "eid", "christmas", "picnic", "exhibition", "hearing", "session", "interview",
)
# Capitalised words before the event word are part of its name ("Rahul Wedding"); only the
# event word itself is case-insensitive
_EVENT_RE = re.compile(
    r"\b((?:[A-Z][\w'-]+\s+){0,3}(?i:" + "|".join(re.escape(w) for w in _EVENT_WORDS) + r")(?:\s+(?:19|20)\d{2})?)\b")
_GENERIC = {
    "documents", "document", "downloads", "download", "pictures", "picture", "photos", "photo", "images", "image",
    "desktop", "new folder", "untitled", "scan", "scans", "img", "dcim", "camera", "screenshots", "misc", "files",
    "events", "event", "albums", "album", "backup", "backups", "gallery", "my pictures", "whatsapp images",
    "page", "pages", "chapter", "contents", "index", "abstract", "introduction", "copy", "final", "draft",
}
_PAGE_HEADING = re.compile(r"^(page\s*\d+|p\.?\s*\d+|\d+)$", re.IGNORECASE)
# Camera folders and file stems: "110EOSR6", "100MSDCF", "IMG_0042", "DSC01234", "P1000123"
_CAMERA_CODE = re.compile(r"^(?:\d{2,3}[A-Za-z]{2,}[A-Za-z0-9_]*|(?:img|dsc|dscn|dscf|pxl|mvi|vid|p)[\s_-]?\d{3,}.*)$",
                          re.IGNORECASE)
# What image captions say about every photo; never a topic on their own
_CAPTION_FILLER = {
    "wearing", "sitting", "standing", "large", "small", "people", "person", "group", "side", "background", "front",
    "room", "screen", "looking", "giving", "holding", "their", "they", "them", "there", "three", "four", "five",
    "white", "black", "left", "right", "smiling", "text", "hands", "hand", "table", "chairs", "chair", "woman",
    "women", "man", "men", "while", "behind", "several", "microphone", "microphones", "suit", "suits", "stage",
    "shows", "showing", "reads", "wooden", "portrait", "podium", "audience", "uniform", "clapping", "decorated",
    "projector", "banner", "image", "photo", "picture", "wall", "floor", "blue", "red", "green", "dark",
}


_LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def _clean_phrase(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip(" \t\r\n-_:;,.|#*"))
    text = _LEADING_ARTICLE.sub("", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return text.rstrip()


def _is_generic(phrase: str) -> bool:
    low = phrase.lower().strip()
    words = low.split()
    return (not low or low in _GENERIC or bool(_PAGE_HEADING.match(low)) or bool(_CAMERA_CODE.match(low))
            or len(low) < 3 or not re.search(r"[^\W\d_]", low)
            or all(w in _CAPTION_FILLER or w in STOPWORDS for w in words))


def _name_tokens(name: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name or "")
    return re.sub(r"[_\-.]+", " ", stem).strip()


def _dedupe(items: Iterable[str], limit: int) -> List[str]:
    out: List[str] = []
    for item in items:
        low = item.lower()
        if any(low in o.lower() or o.lower() in low for o in out):
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


_DATE_SEGMENT = re.compile(r"^(?:(?:19|20)\d{2}|\d{1,2}|\d{4}[-_.]\d{1,2}(?:[-_.]\d{1,2})?|\d{1,2}[-_.]\d{1,2}[-_.](?:19|20)?\d{2})$")


def _folder_topics(folder: str) -> List[str]:
    """The folder names on a file's path that say something, deepest first ("Events/UPSC Centenary/110EOSR6" -> UPSC Centenary)."""
    out: List[str] = []
    for seg in reversed([s for s in (folder or "").replace("\\", "/").split("/") if s]):
        phrase = _clean_phrase(re.sub(r"[_]+", " ", seg))
        if _DATE_SEGMENT.match(phrase) or _is_generic(phrase):
            continue
        out.append(phrase)
    return out


def derive_topics(name: str, folder: str, headings: List[str], texts: List[str],
                  people: List[str], captions: Optional[List[str]] = None,
                  is_image: bool = False) -> Tuple[List[str], List[str]]:
    """
    (topics, events) from the pieces of a file's indexed text. `captions` (image captions and OCR)
    can name things ("Union Public Service Commission") but their single words are only filler
    ("Sitting", "Stage"), so they feed the named phrases and events, never the word counts.

    An image says little about its occasion itself, and a model's description of it is not a topic.
    So its topics are only the folder path it sits in, the people recognised in it and the names
    printed in it (`captions` must then hold the OCR text alone).
    """
    if is_image:
        folders = _folder_topics(folder)
        events = _dedupe([f for f in folders if any(w in f.lower() for w in _EVENT_WORDS)]
                         + [p for p in (_clean_phrase(m.group(1)) for c in (captions or [])
                                        for m in _EVENT_RE.finditer(c or ""))
                            if p and p.lower() not in _EVENT_WORDS and not _is_generic(p)], MAX_EVENTS)
        printed: Counter = Counter()
        for c in captions or []:
            for m in _NAMED.finditer(c or ""):
                phrase = _clean_phrase(m.group(0))
                if not _is_generic(phrase):
                    printed[phrase] += 1
        candidates = events + folders[:3] + list(people) + [p for p, _ in printed.most_common(4)]
        return _dedupe(candidates, MAX_TOPICS), events

    prose = "\n".join(t for t in texts if t)[:20000]
    body = (prose + "\n" + "\n".join(c for c in (captions or []) if c))[:24000]
    folder = (folder or "").replace("\\", "/")

    events: List[str] = []
    for source in (_name_tokens(name), folder.replace("/", " "), *headings[:6], body):
        for m in _EVENT_RE.finditer(source or ""):
            phrase = _clean_phrase(m.group(1))
            if phrase and phrase.lower() not in _EVENT_WORDS and not _is_generic(phrase):
                events.append(phrase.title() if phrase.islower() else phrase)
    # A folder named for the occasion is the best event label there is
    leaf = _clean_phrase(folder.rstrip("/").rsplit("/", 1)[-1]) if folder else ""
    if leaf and not _is_generic(leaf) and any(w in leaf.lower() for w in _EVENT_WORDS):
        events.insert(0, leaf)
    events = _dedupe(events, MAX_EVENTS)

    named: Counter = Counter()
    for m in _NAMED.finditer(body):
        phrase = _clean_phrase(m.group(0))
        if not _is_generic(phrase):
            named[phrase] += 1
    words = Counter(
        w.lower() for w in _WORD.findall(prose)
        if len(w) >= 4 and w.lower() not in STOPWORDS and w.lower() not in _GENERIC
        and w.lower() not in _CAPTION_FILLER and not w.isupper()
    )

    # The title chunk's heading is the file's own path or name: not a topic
    stem = _name_tokens(name).lower()
    headings = [h for h in headings if "/" not in h and "\\" not in h and _name_tokens(h).lower() != stem]
    candidates: List[str] = list(people)
    candidates += [h for h in (_clean_phrase(h) for h in headings) if not _is_generic(h)][:4]
    candidates += events
    candidates += [p for p, n in named.most_common(8) if n >= 2 or len(named) <= 3]
    if leaf and not _is_generic(leaf):
        candidates.append(leaf)
    candidates += [w.capitalize() for w, n in words.most_common(6) if n >= 2]
    if not candidates:
        stem = _clean_phrase(_name_tokens(name))
        if not _is_generic(stem):
            candidates.append(stem)
    return _dedupe(candidates, MAX_TOPICS), events


# ── reading the index ────────────────────────────────────────────────────────
def _people(lib: Library, source_id: str) -> List[str]:
    from app.database.session import db_all
    ids = [r["person_id"] for r in lib.db.all(
        "SELECT DISTINCT person_id FROM faces WHERE source_id = ? AND person_id IS NOT NULL", (source_id,))]
    if not ids:
        return []
    rows = db_all(f"SELECT name FROM persons WHERE hidden = 0 AND name IS NOT NULL AND name != '' "
                  f"AND id IN ({','.join('?' * len(ids))})", tuple(ids))
    return [r["name"] for r in rows][:3]


def _sample_chunks(lib: Library, source_id: str, max_chars: int) -> List[Dict[str, Any]]:
    """Chunks in reading order; a file with more text than fits is sampled evenly, start to end."""
    rows = lib.db.all("SELECT id, length(text) AS n FROM chunks WHERE source_id = ? ORDER BY ord", (source_id,))
    if not rows:
        return []
    total = sum(r["n"] for r in rows)
    if total <= max_chars:
        picked = [r["id"] for r in rows]
    else:
        count = max(1, min(len(rows), int(max_chars // max(1, total / len(rows)))))
        picked = [rows[int(i * len(rows) / count)]["id"] for i in range(count)]
    return lib.db.all(
        f"SELECT id, kind, heading, text, page, ts_start FROM chunks WHERE id IN ({','.join('?' * len(picked))}) ORDER BY ord",
        picked)


def _source_row(lib: Library, source_id: str) -> Optional[Dict[str, Any]]:
    return lib.db.one("SELECT id, name, ext, kind, size, mtime, fingerprint, rel_path, folder FROM sources WHERE id = ?",
                      (source_id,))


def _fingerprint(src: Dict[str, Any]) -> str:
    return str(src.get("fingerprint") or f"{src.get('size')}:{src.get('mtime')}")


def _row_to_insight(row: Dict[str, Any]) -> Dict[str, Any]:
    def load(key: str) -> List[str]:
        try:
            v = json.loads(row.get(key) or "[]")
            return [str(x) for x in v] if isinstance(v, list) else []
        except Exception:
            return []
    return {"topics": load("topics_json"), "events": load("events_json"),
            "summary": row.get("summary"), "origin": row.get("origin") or "index"}


def get_insights(lib: Library, source_id: str) -> Dict[str, Any]:
    """Topics, events and (once summarised) the summary of a source; derived on first use."""
    src = _source_row(lib, source_id)
    if src is None:
        return {"topics": [], "events": [], "summary": None, "origin": "index"}
    fp = _fingerprint(src)
    cached = lib.db.one("SELECT * FROM source_insights WHERE source_id = ?", (source_id,))
    # Index-derived topics also carry the version of the derivation, so improving it refreshes old rows
    want = fp if cached and cached.get("origin") == "llm" else fp + DERIVE_VERSION
    if cached and cached.get("fingerprint") == want:
        return _row_to_insight(cached)

    chunks = _sample_chunks(lib, source_id, 6000)
    headings = [c["heading"] for c in chunks if c.get("heading")]
    headings += [r["title"] for r in lib.db.all(
        "SELECT title FROM sections WHERE source_id = ? AND title IS NOT NULL ORDER BY ord LIMIT 8", (source_id,))]
    visual = lib.db.all("SELECT caption, ocr_text FROM visual_items WHERE source_id = ? ORDER BY id LIMIT 6",
                        (source_id,))
    texts = [c["text"] for c in chunks]
    is_image = src.get("kind") == "image"
    ocr = [v["ocr_text"] for v in visual if v["ocr_text"]]
    # An image's description is not what it is about: its OCR text and folder are the only evidence
    captions = ocr if is_image else [v["caption"] for v in visual if v["caption"]] + ocr
    topics, events = derive_topics(src["name"], src.get("folder") or "", [] if is_image else list(dict.fromkeys(headings)),
                                   [] if is_image else texts, _people(lib, source_id), captions, is_image)
    try:
        lib.db.execute(
            "INSERT INTO source_insights (source_id, fingerprint, topics_json, events_json, origin) "
            "VALUES (?, ?, ?, ?, 'index') ON CONFLICT(source_id) DO UPDATE SET fingerprint = excluded.fingerprint, "
            "topics_json = excluded.topics_json, events_json = excluded.events_json, summary = NULL, "
            "origin = 'index', model = NULL, updated_at = datetime('now')",
            (source_id, fp + DERIVE_VERSION, json.dumps(topics, ensure_ascii=False),
             json.dumps(events, ensure_ascii=False)))
    except Exception as e:     # a read-only library still gets topics, just not cached
        print(f"[Insights] not cached for {source_id}: {e}")
    return {"topics": topics, "events": events, "summary": None, "origin": "index"}


def save_llm_insights(lib: Library, source_id: str, summary: str, topics: List[str], events: List[str],
                      model: str) -> None:
    """Keep what the LLM said about a file; it replaces the index-derived topics."""
    src = _source_row(lib, source_id)
    if src is None:
        return
    topics = _dedupe([_clean_phrase(t) for t in topics if t], MAX_TOPICS)
    events = _dedupe([_clean_phrase(e) for e in events if e], MAX_EVENTS)
    try:
        lib.db.execute(
            "INSERT INTO source_insights (source_id, fingerprint, topics_json, events_json, summary, origin, model) "
            "VALUES (?, ?, ?, ?, ?, 'llm', ?) ON CONFLICT(source_id) DO UPDATE SET fingerprint = excluded.fingerprint, "
            "topics_json = excluded.topics_json, events_json = excluded.events_json, summary = excluded.summary, "
            "origin = 'llm', model = excluded.model, updated_at = datetime('now')",
            (source_id, _fingerprint(src), json.dumps(topics, ensure_ascii=False),
             json.dumps(events, ensure_ascii=False), summary, model))
    except Exception as e:
        print(f"[Insights] LLM insight not cached for {source_id}: {e}")


def cached_llm_summary(lib: Library, source_id: str) -> Optional[Dict[str, Any]]:
    """The stored LLM summary of a source, when it still describes the same file content."""
    src = _source_row(lib, source_id)
    if src is None:
        return None
    row = lib.db.one("SELECT * FROM source_insights WHERE source_id = ? AND origin = 'llm' AND summary IS NOT NULL",
                     (source_id,))
    if not row or row.get("fingerprint") != _fingerprint(src):
        return None
    return _row_to_insight(row)


# ── summary job input and fallback ───────────────────────────────────────────
def build_doc_context(lib: Library, source_id: str, snippet: str, max_chars: int) -> str:
    """The text the LLM reads for one file: the passage that matched, then the file's own text in order."""
    parts: List[str] = []
    if snippet and not snippet.startswith(("File name matches", "In folder", "At the top level")):
        parts.append(f"Best matching passage: {snippet}")
    budget = max_chars - sum(len(p) for p in parts)
    chunks = _sample_chunks(lib, source_id, max(budget, 600))
    if not chunks:
        visual = lib.db.all("SELECT caption, ocr_text FROM visual_items WHERE source_id = ? ORDER BY id LIMIT 3",
                            (source_id,))
        chunks = [{"text": " ".join(x for x in (v["caption"], v["ocr_text"]) if x), "kind": "caption",
                   "page": None, "ts_start": None} for v in visual]
    for c in chunks:
        label = f"[{c['kind']}" + (f" p.{c['page']}" if c.get("page") else "")
        if c.get("ts_start") is not None:
            label += f" {int(c['ts_start'] // 60)}:{int(c['ts_start'] % 60):02d}"
        parts.append(label + "] " + re.sub(r"\s+", " ", c.get("text") or "").strip())
    return "\n".join(p for p in parts if p.strip())[:max_chars]


_SENTENCE = re.compile(r"(?<=[.!?।])\s+")


def extractive_summary(text: str, sentences: int = 3, limit: int = 600) -> str:
    """The first sentences of the text: the fallback when the LLM cannot be used."""
    lines = (text or "").splitlines()
    if len(lines) > 1 and lines[0].startswith("Best matching passage:"):
        lines = lines[1:]               # the passage the search matched is shown with the result already
    lines = [ln.removeprefix("Best matching passage: ") for ln in lines]
    clean = re.sub(r"\[[^\]]+\]\s*", "", "\n".join(lines))
    clean = re.sub(r"\s+", " ", clean).strip()
    picked = [s for s in _SENTENCE.split(clean) if len(s) > 25][:sentences] or [clean[:limit]]
    out = " ".join(picked)
    return out[:limit].rstrip() + ("…" if len(out) > limit else "")
