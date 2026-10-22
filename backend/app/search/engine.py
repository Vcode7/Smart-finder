"""
app/search/engine.py
~~~~~~~~~~~~~~~~~~~~
One search across every online library.

1. Retrieval, per library and in parallel (each retriever returns ~200 candidates):
     bm25        keyword search over every text unit (FTS5: body text, OCR, transcripts)
     dense       meaning: Qwen3 query embedding vs. chunk embeddings
     transcript  the dense/keyword hits that are speech (weighted by "said…" hints)
     extra       passages from attached files (speech, OCR text, document passages)
     clip_text   the typed text vs. images and video frames (Qwen3-VL-Embedding)
     clip_image  attached images vs. images and frames
     compose     attached image + typed text as one query ("this photo, but at night")
     face        faces in attached images vs. indexed faces
     dupe        near-identical images (perceptual hash)
     name        file and folder names (trigram index)
     folder      every file below a folder the query names (folders.py), tied in rank
     folder_*    the other words of such a query (dense, keyword, picture) searched only
                 inside those folders: "dancing at Rahul wedding" → "dancing" photos in
                 Events/Rahul Wedding/, even when they aren't in the global top 200
2. Fusion: weighted reciprocal-rank fusion at the file level (k = 60), so a file with
   many matching chunks doesn't crowd out files that match in other ways.
3. Reranking: the best passages of the top files are re-scored by Qwen3-Reranker-0.6B,
   and where the GPU has room, the best matching picture of the top files that matched
   the typed text by picture is re-scored by Qwen3-VL-Reranker-2B.
4. Scoring: relevanceScore in [0, 1] — 0.7 × reranker + 0.3 × best other evidence when
   a passage was reranked, otherwise calibrated similarity of the best evidence. A face
   in the query becomes a filter when other terms are present ("this person at a beach").
   Files below a named folder are boosted, judged on the query's other words.
"""
from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.library.manager import Library, LibraryManager, get_library_manager
from app.search.constants import STOPWORDS
from app.search.folders import match_folders, scope_members
from app.search.plan import QueryPlan, apply_folder_scopes

RRF_K = 60
RETRIEVE_K = 200
RERANK_FILES = 30           # top fused files whose passages are reranked
RERANK_DEEP_FILES = 10      # ...of which these get RERANK_PASSAGES_PER_FILE passages judged, the rest one
RERANK_PASSAGES_PER_FILE = 3
# Top fused files whose best picture match the picture reranker judges. On
# eval/visual_queries.json 12 gains as much as 20 (R@1 0.88 → 0.92); ~0.25 s per picture
# on an RTX 4050 laptop GPU.
RERANK_VISUAL_FILES = 12
PICTURE_RERANK_SIDE = 1024  # pictures are decoded this large for the picture reranker
MIN_RELEVANCE = 0.15
VISUAL_EVIDENCE = 12        # matching frames / images kept per file
VISUAL_RETRIEVERS = ("clip_text", "clip_image", "compose", "face", "dupe", "folder_clip")
TEXT_RETRIEVERS = ("dense", "bm25", "extra", "transcript", "folder_dense", "folder_bm25")
TIED_RETRIEVERS = ("folder", "filter")   # equal scores share a rank (every file of a folder alike)
BROWSE_MAX = 5000           # files listed for a query of filters only
FOLDER_BOOST = 0.35         # share of the remaining headroom a folder match adds
FOLDER_FLOOR = 0.4          # × folder score: the rest of a named folder, below real matches
MAX_EXACT_IDS = 50000       # filtered vector searches beyond this many ids filter afterwards
FACE_MATCH = 0.42           # buffalo_l cosine treated as "same person"
DUPE_MAX_BITS = 10
BURST_MAX_BITS = 6          # photos this close (perceptual hash) show as one result

BASE_WEIGHTS: Dict[str, float] = {
    "bm25": 1.0, "dense": 1.0, "transcript": 0.0, "extra": 0.8, "clip_text": 0.8,
    "clip_image": 1.3, "compose": 0.9, "face": 1.6, "dupe": 1.6, "name": 0.7,
    "sound": 1.3, "sound_audio": 1.5,
    "folder": 1.2, "folder_dense": 1.0, "folder_bm25": 0.8, "folder_clip": 1.0, "filter": 1.0,
}
TIMED_RETRIEVERS = ("sound", "sound_audio")

_WORD_RE = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)


# ── calibration (raw similarity → [0, 1]) ────────────────────────────────────
# Measured on real files (Hindi and English news PDFs, a phone video, event photos):
#   Qwen3 query↔passage      relevant 0.51–0.67, unrelated 0.24–0.34
#   Qwen3-VL text↔image      relevant 0.27–0.77 (median 0.57), unrelated median 0.15, p95 0.27
#   Qwen3-VL image↔image     same picture 1.0 (0.79–0.94 against a 384 px copy), other photos
#                            of the same event median 0.49, p95 0.75
#   ArcFace                  same person 0.85–0.91, others < 0.10
def _ramp(x: float, zero: float, lo: float, hi: float, out_lo: float, out_hi: float) -> float:
    """0 up to `zero`, rising to out_lo at `lo`, to out_hi at `hi`, flat above."""
    if x <= zero:
        return 0.0
    if x < lo:
        return out_lo * (x - zero) / (lo - zero)
    if x >= hi:
        return out_hi
    return out_lo + (x - lo) / (hi - lo) * (out_hi - out_lo)


def cal_dense(cos: float) -> float:      # Qwen3 query↔passage cosine
    return _ramp(cos, 0.30, 0.40, 0.70, 0.20, 0.95)


def cal_clip_text(cos: float) -> float:  # Qwen3-VL text↔image cosine
    return _ramp(cos, 0.22, 0.30, 0.60, 0.15, 0.92)


def cal_clip_image(cos: float) -> float:  # Qwen3-VL image↔image cosine
    return _ramp(cos, 0.50, 0.65, 0.92, 0.25, 0.98)


def cal_face(cos: float) -> float:       # ArcFace (buffalo_l) cosine
    return _ramp(cos, 0.25, FACE_MATCH, 0.75, 0.45, 0.98) if cos < FACE_MATCH else \
        _ramp(cos, 0.0, FACE_MATCH, 0.75, 0.70, 0.98)


def cal_dupe(bits: float) -> float:      # perceptual-hash Hamming distance
    return max(0.0, 1.0 - bits / 32.0)


def cal_sound(cos: float) -> float:      # CLAP text↔audio cosine (speech video vs "a man giving a speech": 0.15)
    return _ramp(cos, 0.08, 0.15, 0.35, 0.20, 0.92)


def cal_sound_audio(cos: float) -> float:  # CLAP audio↔audio cosine
    return _ramp(cos, 0.45, 0.60, 0.92, 0.30, 0.98)


# ── data ─────────────────────────────────────────────────────────────────────
@dataclass
class Hit:
    lib_id: str
    source_id: str
    kind: str            # chunk | visual | face | source
    entity_id: int
    score: float         # raw similarity (higher is better)


@dataclass
class FileMatch:
    lib: Library
    source_id: str
    ranks: Dict[str, int] = field(default_factory=dict)
    best: Dict[str, Hit] = field(default_factory=dict)
    hits: Dict[str, List[Hit]] = field(default_factory=dict)
    fused: float = 0.0
    rerank: Optional[float] = None
    rerank_hit: Optional[Hit] = None
    relevance: float = 0.0
    evidence: str = ""

    @property
    def key(self) -> Tuple[str, str]:
        return self.lib.id, self.source_id


@dataclass
class EngineResult:
    documents: List[Dict[str, Any]]
    videos: List[Dict[str, Any]]
    images: List[Dict[str, Any]]
    audio: List[Dict[str, Any]]
    trace: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {"documents": self.documents, "videos": self.videos, "images": self.images, "audio": self.audio}

    def all(self) -> List[Dict[str, Any]]:
        return sorted(self.documents + self.videos + self.images + self.audio,
                      key=lambda x: x["relevanceScore"], reverse=True)


# ── helpers ──────────────────────────────────────────────────────────────────
def _in_clause(values: List[Any]) -> str:
    return ",".join("?" * len(values))


def _chunks(seq: List[Any], n: int = 900) -> Iterable[List[Any]]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def fts_terms(text: str) -> List[str]:
    words = [w.lower() for w in _WORD_RE.findall(text or "")]
    meaningful = [w for w in words if w not in STOPWORDS and len(w) > 1]
    return list(dict.fromkeys(meaningful or words))[:24]


def _fts_quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def focus_window(text: str, terms: Iterable[str], size: int = 700) -> Tuple[str, bool]:
    """
    The `size`-character window of `text` with the most query terms in it (whole words).
    Long chunks — a news page with several stories — are judged and shown by the part
    that matches. Returns (window, cut) where cut tells whether text was shortened.
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= size:
        return text, False
    wanted = {t.lower() for t in terms if t}
    if not wanted:
        return text[:size], True
    words = [(m.start(), m.group(0).lower()) for m in _WORD_RE.finditer(text)]
    hits = [pos for pos, w in words if w in wanted]
    if not hits:
        return text[:size], True
    best_start, best_count, k = hits[0], 0, 0
    for i, start in enumerate(hits):   # two pointers: hits within [start, start + size)
        k = max(k, i)
        while k + 1 < len(hits) and hits[k + 1] < start + size:
            k += 1
        if k - i + 1 > best_count:
            best_start, best_count = start, k - i + 1
    begin = max(0, best_start - size // 5)
    space = text.rfind(" ", 0, begin)
    begin = space + 1 if space > 0 and begin - space < 40 else begin
    return text[begin:begin + size], True


def _allowed_sources(lib: Library, plan: QueryPlan) -> Optional[Set[str]]:
    f = plan.filters
    if not f.active() and not plan.exclude_sources:
        return None
    assert lib.db is not None
    where, params = ["status NOT IN ('missing', 'excluded')"], []
    if f.kinds:
        where.append(f"kind IN ({_in_clause(list(f.kinds))})")
        params.extend(f.kinds)
    if f.exts:
        where.append(f"ext IN ({_in_clause(list(f.exts))})")
        params.extend(f.exts)
    if f.folder:
        # A path from the library root, or a folder's name at any depth (folder:"Rahul Wedding")
        where.append("(rel_path = ? OR rel_path LIKE ? ESCAPE '\\' OR ('/' || folder || '/') LIKE ? ESCAPE '\\')")
        esc = f.folder.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").rstrip("/")
        params.extend([f.folder, esc + "/%", "%/" + esc + "/%"])
    when = "COALESCE(taken_at, datetime(mtime, 'unixepoch'))"
    if f.after:
        where.append(f"{when} >= ?")
        params.append(f.after)
    if f.before:
        where.append(f"{when} < ?")
        params.append(f.before)
    ids = {r["id"] for r in lib.db.all(f"SELECT id FROM sources WHERE {' AND '.join(where)}", params)}
    return ids - plan.exclude_sources


# ── retrievers (one library) ─────────────────────────────────────────────────
def _vector_hits(lib: Library, space: str, vec: Optional[List[float]], kind: str,
                 allowed: Optional[Set[str]], k: int = RETRIEVE_K) -> List[Hit]:
    if vec is None or lib.vectors is None or lib.db is None:
        return []
    allowed_ids: Optional[List[int]] = None
    fetch = k
    if allowed is not None:
        if not allowed:
            return []
        if len(allowed) <= 2000:
            src = list(allowed)
            allowed_ids = []
            for part in _chunks(src):
                allowed_ids.extend(r["id"] for r in lib.db.all(
                    f"SELECT id FROM vectors WHERE space = ? AND source_id IN ({_in_clause(part)})", [space, *part]))
            if not allowed_ids:
                return []
            if len(allowed_ids) > MAX_EXACT_IDS:
                allowed_ids, fetch = None, k * 8
        else:
            fetch = k * 4   # large allowed set: search wider, filter afterwards
    found = lib.vectors.search(space, vec, fetch, allowed_ids)
    if not found:
        return []
    meta: Dict[int, Dict[str, Any]] = {}
    ids = [vid for vid, _ in found]
    for part in _chunks(ids):
        for r in lib.db.all(f"SELECT id, entity_id, source_id FROM vectors WHERE id IN ({_in_clause(part)})", part):
            meta[int(r["id"])] = r
    hits = []
    for vid, score in found:
        row = meta.get(vid)       # a vector removed since the index was saved is skipped
        if row is None or (allowed is not None and row["source_id"] not in allowed):
            continue
        hits.append(Hit(lib.id, row["source_id"], kind, int(row["entity_id"]), float(score)))
        if len(hits) >= k:
            break
    return hits


def _bm25(lib: Library, plan: QueryPlan, allowed: Optional[Set[str]], k: int = RETRIEVE_K,
          text: Optional[str] = None) -> List[Hit]:
    assert lib.db is not None
    terms = fts_terms(plan.text if text is None else text)
    phrases = [p for p in plan.phrases if p.strip()] if text is None else []
    if not terms and not phrases:
        return []
    quoted = [_fts_quote(t) for t in terms] + [_fts_quote(p) for p in phrases]
    sql = ("SELECT c.id AS id, c.source_id AS source_id, -bm25(chunks_fts, 1.0, 0.4) AS score "
           "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid WHERE chunks_fts MATCH ? "
           "ORDER BY bm25(chunks_fts, 1.0, 0.4) LIMIT ?")
    seen: Set[int] = set()
    hits: List[Hit] = []
    queries = [" AND ".join(quoted)]
    if len(quoted) > 1:
        queries.append(" OR ".join(quoted))     # fill with partial matches, ranked after full ones
    for q in queries:
        try:
            rows = lib.db.all(sql, (q, k * 2 if allowed is not None else k))
        except Exception:
            continue
        for r in rows:
            if r["id"] in seen or (allowed is not None and r["source_id"] not in allowed):
                continue
            seen.add(r["id"])
            hits.append(Hit(lib.id, r["source_id"], "chunk", int(r["id"]), float(r["score"])))
        if len(hits) >= k // 4:
            break
    return hits[:k]


def _names(lib: Library, plan: QueryPlan, allowed: Optional[Set[str]], k: int = 50) -> List[Hit]:
    assert lib.db is not None
    terms = [t for t in fts_terms(plan.text) if len(t) >= 3]
    if not terms:
        return []
    try:
        rows = lib.db.all(
            "SELECT s.id AS id, s.name AS name, s.rel_path AS rel_path FROM sources_fts "
            "JOIN sources s ON s.rowid = sources_fts.rowid WHERE sources_fts MATCH ? "
            "ORDER BY bm25(sources_fts) LIMIT ?",
            (" OR ".join(_fts_quote(t) for t in terms), k * 2),
        )
    except Exception:
        return []
    hits = []
    for r in rows:
        if allowed is not None and r["id"] not in allowed:
            continue
        hay = f"{r['name']} {r['rel_path']}".lower()
        frac = sum(1 for t in terms if t in hay) / len(terms)
        hits.append(Hit(lib.id, r["id"], "source", 0, frac))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


def _hamming_fn(a: Optional[int], b: Optional[int]) -> int:
    if a is None or b is None:
        return 64
    return bin((int(a) ^ int(b)) & 0xFFFFFFFFFFFFFFFF).count("1")


def _dupes(lib: Library, phash: Optional[int], allowed: Optional[Set[str]], k: int = 50) -> List[Hit]:
    if phash is None or lib.db is None:
        return []
    conn = lib.db.conn()
    conn.create_function("hamming", 2, _hamming_fn, deterministic=True)
    rows = conn.execute(
        "SELECT id, source_id, hamming(phash, ?) AS d FROM visual_items "
        "WHERE phash IS NOT NULL AND hamming(phash, ?) <= ? ORDER BY d LIMIT ?",
        (phash, phash, DUPE_MAX_BITS, k),
    ).fetchall()
    # Score is "bits that match" so higher is better, like every other retriever
    return [Hit(lib.id, r["source_id"], "visual", int(r["id"]), 64.0 - float(r["d"]))
            for r in rows if allowed is None or r["source_id"] in allowed]


def _merge_max(lists: Iterable[List[Hit]]) -> List[Hit]:
    best: Dict[Tuple[str, int], Hit] = {}
    for hits in lists:
        for h in hits:
            key = (h.kind, h.entity_id) if h.kind != "source" else ("source", hash(h.source_id))
            if key not in best or h.score > best[key].score:
                best[key] = h
    return sorted(best.values(), key=lambda h: h.score, reverse=True)


def _normalized_sum(a: List[float], b: List[float], wb: float) -> List[float]:
    v = [x + wb * y for x, y in zip(a, b)]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def retrieve_library(lib: Library, plan: QueryPlan) -> Dict[str, List[Hit]]:
    allowed = _allowed_sources(lib, plan)
    out: Dict[str, List[Hit]] = {}
    if plan.text:
        out["bm25"] = _bm25(lib, plan, allowed)
        out["name"] = _names(lib, plan, allowed)
    if plan.text_vec is not None:
        out["dense"] = _vector_hits(lib, "text", plan.text_vec, "chunk", allowed)
    extra_lists = [_vector_hits(lib, "text", v, "chunk", allowed, k=100) for v in plan.extra_vecs if v is not None]
    if extra_lists:
        out["extra"] = _merge_max(extra_lists)
    if plan.clip_text_vec is not None:
        out["clip_text"] = _vector_hits(lib, "clip", plan.clip_text_vec, "visual", allowed)
    img_lists, compose_lists, face_lists, dupe_lists = [], [], [], []
    for img in plan.images:
        if img.clip_vec is not None:
            img_lists.append(_vector_hits(lib, "clip", img.clip_vec, "visual", allowed))
            if plan.clip_text_vec is not None:
                # Stored-vector signals ("more like this file") have no picture to compose with
                composed = img.compose_vec or _normalized_sum(img.clip_vec, plan.clip_text_vec, 0.6)
                compose_lists.append(_vector_hits(lib, "clip", composed, "visual", allowed))
        for f in img.faces:
            face_lists.append(_vector_hits(lib, "face", f, "face", allowed))
        dupe_lists.append(_dupes(lib, img.phash, allowed))
    for name, lists in (("clip_image", img_lists), ("compose", compose_lists), ("face", face_lists), ("dupe", dupe_lists)):
        if lists:
            out[name] = _merge_max(lists)
    if plan.clap_text_vec is not None:
        out["sound"] = _vector_hits(lib, "clap", plan.clap_text_vec, "audio", allowed)
    sound_lists = [_vector_hits(lib, "clap", v, "audio", allowed) for v in plan.sound_vecs]
    if sound_lists:
        out["sound_audio"] = _merge_max(sound_lists)
    if allowed is not None and plan.filters.active() and not out and not plan.text and not plan.extra \
            and not plan.images:
        # Only filters (folder:"Events/Diwali 2023"): list what they allow, in path order
        listed = [r["id"] for r in lib.db.all("SELECT id FROM sources ORDER BY rel_path") if r["id"] in allowed]
        out["filter"] = [Hit(lib.id, sid, "source", 0, 1.0) for sid in listed[:BROWSE_MAX]]
    scopes = plan.folder_scopes.get(lib.id)
    if scopes:
        members = scope_members(lib, scopes, allowed)
        out["folder"] = [Hit(lib.id, sid, "source", 0, s)
                         for sid, s in sorted(members.items(), key=lambda kv: kv[1], reverse=True)]
        inside = set(members)
        if plan.content_text and inside:
            out["folder_bm25"] = _bm25(lib, plan, inside, text=plan.content_text)
            if plan.content_text_vec is not None:
                out["folder_dense"] = _vector_hits(lib, "text", plan.content_text_vec, "chunk", inside)
            if plan.content_clip_vec is not None:
                out["folder_clip"] = _vector_hits(lib, "clip", plan.content_clip_vec, "visual", inside)
    return out


# ── the engine ───────────────────────────────────────────────────────────────
class SearchEngine:
    def __init__(self, manager: Optional[LibraryManager] = None):
        self._manager = manager

    @property
    def manager(self) -> LibraryManager:
        return self._manager or get_library_manager()

    def _libraries(self, plan: QueryPlan, allowed: Optional[Set[str]] = None) -> List[Library]:
        libs = [lib for lib in self.manager.online() if lib.db is not None]
        if allowed is not None:
            # Applied before the in:<library> filter, so a query can never widen access
            libs = [lib for lib in libs if lib.id in allowed]
        wanted = {w.lower() for w in plan.filters.libraries}
        if wanted:
            libs = [lib for lib in libs if lib.id.lower() in wanted or lib.name.lower() in wanted]
        return libs

    def _weights(self, plan: QueryPlan) -> Dict[str, float]:
        w = dict(BASE_WEIGHTS)
        for k, v in plan.boosts.items():
            if k in w:
                w[k] *= v
        if "transcript" in plan.boosts:
            w["transcript"] = 0.8 * plan.boosts["transcript"]
        if plan.images and not plan.text:
            w["name"] = 0.0
        if plan.people:
            w["face"] = 2.2          # "photos of Rahul": the face is the point of the query
        return w

    def search(self, plan: QueryPlan, limit: int = 20,
               allowed_libraries: Optional[Set[str]] = None) -> EngineResult:
        """`allowed_libraries` limits the search to those library ids (None = every library)."""
        from app.search import model_pipeline as mp
        from app.search.activity import search_activity
        try:
            with search_activity():
                return self._search(plan, limit, allowed_libraries)
        finally:
            mp.trim_vram()

    def _search(self, plan: QueryPlan, limit: int, allowed: Optional[Set[str]] = None) -> EngineResult:
        libs = self._libraries(plan, allowed)
        trace: Dict[str, Any] = {**plan.trace, "libraries": [lib.name for lib in libs]}
        if not libs:
            return EngineResult([], [], [], [], trace)
        with ThreadPoolExecutor(max_workers=min(8, len(libs))) as pool:
            if plan.text and not plan.filters.folder:
                scopes = dict(pool.map(lambda lib: (lib.id, match_folders(lib, plan.text)), libs))
                apply_folder_scopes(plan, scopes, {lib.id: lib.name for lib in libs})
                for key in ("folders", "folderQuery"):
                    if key in plan.trace:
                        trace[key] = plan.trace[key]
            per_lib = list(pool.map(lambda lib: (lib, retrieve_library(lib, plan)), libs))

        # Global per-retriever rankings (similarities share a scale across libraries)
        by_retriever: Dict[str, List[Hit]] = {}
        lib_by_id = {lib.id: lib for lib in libs}
        for lib, lists in per_lib:
            for name, hits in lists.items():
                by_retriever.setdefault(name, []).extend(hits)
        for name in by_retriever:
            by_retriever[name].sort(key=lambda h: h.score, reverse=True)
        self._split_transcripts(by_retriever, lib_by_id)
        trace["candidates"] = {k: len(v) for k, v in by_retriever.items()}

        weights = self._weights(plan)
        files = self._fuse(by_retriever, weights, lib_by_id)
        if plan.has_faces and (plan.text or plan.extra):
            # "This person, doing X": only media where the person appears
            files = {k: f for k, f in files.items()
                     if f.best.get("face") is not None and f.best["face"].score >= FACE_MATCH}
            trace["faceFilter"] = True
        ranked = sorted(files.values(), key=lambda f: f.fused, reverse=True)

        judged = self._rerank_pool(ranked, RERANK_FILES, plan)
        passages = self._load_passages(judged)
        self._rerank(plan, judged, passages, trace)
        self._rerank_pictures(plan, self._rerank_pool(ranked, RERANK_VISUAL_FILES, plan), passages, trace)
        top_fused = ranked[0].fused if ranked else 1.0
        for f in ranked:
            self._score(f, top_fused, plan)
        loaded = {f.key for f in judged}
        ranked = [f for f in ranked if f.relevance >= MIN_RELEVANCE]
        ranked.sort(key=lambda f: f.relevance, reverse=True)
        return self._shape(ranked, passages, loaded, plan, limit, trace)

    @staticmethod
    def _rerank_pool(ranked: List[FileMatch], n: int, plan: QueryPlan) -> List[FileMatch]:
        """
        The top n fused files for the rerankers. When the query named folders, a third of
        the places go to the best files outside them, so a folder of hundreds of files
        can't keep a strong match elsewhere from being judged.
        """
        if not plan.folder_scopes:
            return ranked[:n]
        outside = [f for f in ranked if "folder" not in f.best][:n // 3]
        inside = [f for f in ranked if "folder" in f.best][:n - len(outside)]
        return sorted(inside + outside, key=lambda f: f.fused, reverse=True)

    @staticmethod
    def _split_transcripts(by_retriever: Dict[str, List[Hit]], lib_by_id: Dict[str, Library]) -> None:
        """Speech chunks found by bm25/dense also form their own 'transcript' list."""
        chunk_ids: Dict[str, Set[int]] = {}
        for name in ("dense", "bm25"):
            for h in by_retriever.get(name, []):
                chunk_ids.setdefault(h.lib_id, set()).add(h.entity_id)
        speech: Dict[Tuple[str, int], bool] = {}
        for lib_id, ids in chunk_ids.items():
            lib = lib_by_id[lib_id]
            id_list = list(ids)
            for part in _chunks(id_list):
                for r in lib.db.all(f"SELECT id FROM chunks WHERE kind = 'transcript' AND id IN ({_in_clause(part)})", part):
                    speech[(lib_id, int(r["id"]))] = True
        if speech:
            merged = [h for name in ("dense", "bm25") for h in by_retriever.get(name, [])
                      if speech.get((h.lib_id, h.entity_id))]
            by_retriever["transcript"] = _merge_max([merged])

    @staticmethod
    def _fuse(by_retriever: Dict[str, List[Hit]], weights: Dict[str, float],
              lib_by_id: Dict[str, Library]) -> Dict[Tuple[str, str], FileMatch]:
        files: Dict[Tuple[str, str], FileMatch] = {}
        for name, hits in by_retriever.items():
            w = weights.get(name, 0.0)
            tied = name in TIED_RETRIEVERS
            rank, prev = 0, None
            for h in hits:
                key = (h.lib_id, h.source_id)
                f = files.get(key)
                if f is None:
                    f = files[key] = FileMatch(lib=lib_by_id[h.lib_id], source_id=h.source_id)
                f.hits.setdefault(name, []).append(h)
                if name not in f.ranks:
                    if tied and prev is not None and h.score < prev:
                        rank += 1
                    prev = h.score
                    f.ranks[name] = rank
                    f.best[name] = h
                    if w > 0:
                        f.fused += w / (RRF_K + rank + 1)
                    if not tied:
                        rank += 1
        return files

    @staticmethod
    def _load_passages(files: List[FileMatch]) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
        """Text of the chunks / visuals that could represent each file."""
        want: Dict[str, Dict[str, Set[int]]] = {}
        for f in files:
            per = want.setdefault(f.lib.id, {"chunk": set(), "visual": set(), "face": set(), "audio": set()})
            for name, hits in f.hits.items():
                depth = VISUAL_EVIDENCE if name in VISUAL_RETRIEVERS + TIMED_RETRIEVERS else RERANK_PASSAGES_PER_FILE + 1
                for h in hits[:depth]:
                    if h.kind in per:
                        per[h.kind].add(h.entity_id)
        out: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
        libs = {f.lib.id: f.lib for f in files}
        for lib_id, per in want.items():
            lib = libs[lib_id]
            assert lib.db is not None
            ids = list(per["chunk"])
            for part in _chunks(ids):
                for r in lib.db.all(
                    f"SELECT id, source_id, kind, text, heading, page, ts_start, ts_end, visual_item_id "
                    f"FROM chunks WHERE id IN ({_in_clause(part)})", part):
                    out[(lib_id, "chunk", int(r["id"]))] = r
            ids = list(per["face"])
            for part in _chunks(ids):
                for r in lib.db.all(
                    f"SELECT id, source_id, visual_item_id, ts, page, crop_path, det_score FROM faces "
                    f"WHERE id IN ({_in_clause(part)})", part):
                    out[(lib_id, "face", int(r["id"]))] = r
                    if r["visual_item_id"]:
                        per["visual"].add(int(r["visual_item_id"]))
            ids = list(per["visual"])
            for part in _chunks(ids):
                for r in lib.db.all(
                    f"SELECT id, source_id, kind, page, ts, cache_path, caption, ocr_text FROM visual_items "
                    f"WHERE id IN ({_in_clause(part)})", part):
                    out[(lib_id, "visual", int(r["id"]))] = r
            ids = list(per["audio"])
            for part in _chunks(ids):
                for r in lib.db.all(
                    f"SELECT id, source_id, ts_start, ts_end FROM audio_segments WHERE id IN ({_in_clause(part)})", part):
                    out[(lib_id, "audio", int(r["id"]))] = r
        return out

    @staticmethod
    def _passage_text(row: Dict[str, Any], kind: str) -> str:
        if kind == "chunk":
            head = f"{row['heading']}\n" if row.get("heading") else ""
            return f"{head}{row['text']}"
        if kind == "visual":
            return " ".join(p for p in (row.get("caption") or "", row.get("ocr_text") or "") if p).strip()
        return ""

    def _rerank(self, plan: QueryPlan, files: List[FileMatch],
                passages: Dict[Tuple[str, str, int], Dict[str, Any]], trace: Dict[str, Any]) -> None:
        from app.search import model_pipeline as mp
        if not plan.rerank_query or not files:
            return
        jobs: List[Tuple[FileMatch, Hit, str]] = []
        queries: List[str] = []
        names = self._source_names(files)
        for rank, f in enumerate(files):
            title = names.get(f.key, "")
            # Inside a folder the query named, the folder is accounted for: judge the rest
            query = plan.content_text if plan.content_text and "folder" in f.best else plan.rerank_query
            # Interleave retrievers (best dense, best keyword, best extra, then the runners-up)
            # so an exact keyword hit such as an OCR'd headline is always judged. The top files
            # get several passages judged, the rest one each (keeps a query under a second).
            budget = RERANK_PASSAGES_PER_FILE if rank < RERANK_DEEP_FILES else 1
            picked: List[Hit] = []
            for depth in range(budget):
                for retr in TEXT_RETRIEVERS:
                    hits = f.hits.get(retr, [])
                    if depth < len(hits):
                        h = hits[depth]
                        if h.kind == "chunk" and all(p.entity_id != h.entity_id for p in picked):
                            picked.append(h)
            picked = picked[:budget]
            if not picked:
                for retr in ("folder_clip", "clip_text", "compose", "clip_image"):
                    h = f.best.get(retr)
                    row = passages.get((f.lib.id, "visual", h.entity_id)) if h else None
                    if row and (row.get("caption") or row.get("ocr_text")):
                        picked.append(h)
                        break
            terms = fts_terms(query)
            # A file name only helps the reranker when it is about the query: a generic
            # name ("long report.pdf", "IMG_2041.jpg") made an exact headline match score
            # 0.19 instead of 0.66 in testing
            title_words = {w.lower() for w in _WORD_RE.findall(title)}
            prefix = f"Title: {title}\n" if title_words & set(terms) else ""
            for h in picked:
                row = passages.get((f.lib.id, h.kind, h.entity_id))
                if row is None:
                    continue
                text = self._passage_text(row, h.kind)
                if text.strip():
                    window, _ = focus_window(text, terms, 900)
                    jobs.append((f, h, f"{prefix}{window}"))
                    queries.append(query)
            if not picked and f.best.get("name") is not None:
                jobs.append((f, f.best["name"], f"Title: {title}"))
                queries.append(query)
        if not jobs:
            return
        reranked = 0
        for query in dict.fromkeys(queries):
            batch = [j for j, q in zip(jobs, queries) if q == query]
            scores = mp.rerank(query, [j[2] for j in batch])
            if scores is None:
                continue
            reranked += len(batch)
            for (f, h, _), s in zip(batch, scores):
                if f.rerank is None or s > f.rerank:
                    f.rerank, f.rerank_hit = s, h
        trace["reranked"] = reranked

    def _rerank_pictures(self, plan: QueryPlan, files: List[FileMatch],
                         passages: Dict[Tuple[str, str, int], Dict[str, Any]], trace: Dict[str, Any]) -> None:
        """
        The picture reranker judges each top file's best picture match against the typed
        words (names of people left out); a verdict stronger than the passage's replaces it.
        """
        from app.ingest.pipeline import visual_image
        from app.search import model_pipeline as mp
        query = plan.visual_text if plan.people else plan.text
        if not query or not files or not mp.visual_rerank_enabled():
            return
        picks: List[Tuple[FileMatch, Hit, Dict[str, Any]]] = []
        queries: List[str] = []
        for f in files:
            # A picture can't show the folder it is in: inside a named folder, judge the other
            # words (and leave a folder-only match to the folder)
            in_folder = "folder" in f.best
            if in_folder and not plan.content_text:
                continue
            retrievers = ("folder_clip", "clip_text", "compose") if in_folder else ("clip_text", "compose")
            h = max((f.best[r] for r in retrievers if r in f.best), key=lambda x: x.score, default=None)
            row = passages.get((f.lib.id, "visual", h.entity_id)) if h is not None else None
            if row is not None:
                picks.append((f, h, row))
                queries.append(plan.content_text if in_folder else query)
        if not picks:
            return
        paths: Dict[Tuple[str, str], str] = {}
        by_lib: Dict[str, List[str]] = {}
        for f, _, _ in picks:
            by_lib.setdefault(f.lib.id, []).append(f.source_id)
        libs = {f.lib.id: f.lib for f, _, _ in picks}
        for lib_id, ids in by_lib.items():
            for part in _chunks(ids):
                for r in libs[lib_id].db.all(f"SELECT id, rel_path FROM sources WHERE id IN ({_in_clause(part)})", part):
                    paths[(lib_id, r["id"])] = r["rel_path"]

        def load(pick: Tuple[FileMatch, Hit, Dict[str, Any]]):
            f, _, row = pick
            try:
                return visual_image(f.lib, {"id": f.source_id, "rel_path": paths.get(f.key, "")}, row, PICTURE_RERANK_SIDE)
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            images = list(pool.map(load, picks))
        jobs = [(f, h, im, q) for (f, h, _), im, q in zip(picks, images, queries) if im is not None]
        judged = 0
        for q in dict.fromkeys(j[3] for j in jobs):
            batch = [j for j in jobs if j[3] == q]
            scores = mp.rerank_images(q, [j[2] for j in batch])
            if scores is None:
                continue
            judged += len(batch)
            for (f, h, _, _), s in zip(batch, scores):
                if f.rerank is None or s > f.rerank:
                    f.rerank, f.rerank_hit = s, h
        trace["picturesReranked"] = judged

    def _source_names(self, files: List[FileMatch]) -> Dict[Tuple[str, str], str]:
        out: Dict[Tuple[str, str], str] = {}
        by_lib: Dict[str, List[str]] = {}
        libs = {f.lib.id: f.lib for f in files}
        for f in files:
            by_lib.setdefault(f.lib.id, []).append(f.source_id)
        for lib_id, ids in by_lib.items():
            for part in _chunks(ids):
                for r in libs[lib_id].db.all(f"SELECT id, name, rel_path FROM sources WHERE id IN ({_in_clause(part)})", part):
                    out[(lib_id, r["id"])] = r["rel_path"] if "/" in r["rel_path"] else r["name"]
        return out

    @staticmethod
    def _score(f: FileMatch, top_fused: float, plan: QueryPlan) -> None:
        cal: Dict[str, float] = {}
        if "dense" in f.best:
            cal["dense"] = cal_dense(f.best["dense"].score)
        if "extra" in f.best:
            cal["extra"] = cal_dense(f.best["extra"].score)
        if "clip_text" in f.best:
            cal["clip_text"] = cal_clip_text(f.best["clip_text"].score)
        if "clip_image" in f.best:
            cal["clip_image"] = cal_clip_image(f.best["clip_image"].score)
        if "compose" in f.best:
            cal["compose"] = cal_clip_image(f.best["compose"].score) * 0.95
        if "face" in f.best:
            cal["face"] = cal_face(f.best["face"].score)
        if "dupe" in f.best:
            cal["dupe"] = cal_dupe(64.0 - f.best["dupe"].score)
        if "name" in f.best and "folder" not in f.best:   # in a named folder, the folder says it
            cal["name"] = 0.35 + 0.5 * f.best["name"].score
        if "sound" in f.best:
            cal["sound"] = cal_sound(f.best["sound"].score)
        if "sound_audio" in f.best:
            cal["sound_audio"] = cal_sound_audio(f.best["sound_audio"].score)
        if "folder_dense" in f.best:
            cal["folder_dense"] = cal_dense(f.best["folder_dense"].score)
        if "folder_clip" in f.best:
            cal["folder_clip"] = cal_clip_text(f.best["folder_clip"].score)
        fused_norm = f.fused / top_fused if top_fused > 0 else 0.0

        visual = {k: v for k, v in cal.items()
                  if k in ("clip_text", "clip_image", "compose", "face", "dupe", "name", "sound", "sound_audio",
                           "folder_clip")}
        best_other = max(visual.values(), default=0.0)
        if f.rerank is not None:
            # Rank fusion only lends weight to passages the reranker finds at least plausible
            support = fused_norm * 0.8 * min(1.0, f.rerank * 4.0)
            f.relevance = 0.7 * f.rerank + 0.3 * max(best_other, support)
            # A reranked picture leads the result with that picture
            f.evidence = "clip_text" if f.rerank_hit is not None and f.rerank_hit.kind == "visual" else "reranked passage"
            # A strong visual or face match isn't hidden by a weak passage
            if best_other > f.relevance:
                f.relevance, f.evidence = best_other, max(visual, key=visual.get)
        elif cal:
            ordered = sorted(cal.values(), reverse=True)
            base = ordered[0]
            bonus = 0.1 * ordered[1] * (1.0 - base) if len(ordered) > 1 else 0.0
            f.relevance = min(0.99, base + bonus)
            f.evidence = max(cal, key=cal.get)
        else:
            # Keyword-only match without a reranker: rank by fusion, capped
            f.relevance = 0.25 + 0.4 * fused_norm
            f.evidence = "keywords"
        if plan.has_faces and "face" in cal and (plan.text or plan.extra):
            f.relevance = min(0.99, f.relevance + 0.15 * cal["face"] * (1.0 - f.relevance))
        if "folder" in f.best:
            # In a folder the query named: the folder lifts what the other words found, and
            # every file in it is listed — when other words were given, after the files
            # (inside or outside the folder) that match them
            folder = 0.45 + 0.4 * f.best["folder"].score
            floor = FOLDER_FLOOR * folder if plan.content_text else folder
            lifted = f.relevance + FOLDER_BOOST * folder * (1.0 - f.relevance)
            if floor > lifted:
                lifted, f.evidence = floor, "folder"
            f.relevance = min(0.99, lifted)
            if f.evidence == "keywords":
                f.evidence = "folder"

    # ── shaping ──────────────────────────────────────────────────────────────
    def _shape(self, ranked: List[FileMatch], passages: Dict[Tuple[str, str, int], Dict[str, Any]],
               loaded: Set[Tuple[str, str]], plan: QueryPlan, limit: int, trace: Dict[str, Any]) -> EngineResult:
        buckets: Dict[str, List[Dict[str, Any]]] = {"document": [], "video": [], "image": [], "audio": []}
        rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
        by_lib: Dict[str, List[str]] = {}
        libs = {f.lib.id: f.lib for f in ranked}
        for f in ranked:
            by_lib.setdefault(f.lib.id, []).append(f.source_id)
        for lib_id, ids in by_lib.items():
            for part in _chunks(ids):
                for r in libs[lib_id].db.all(f"SELECT * FROM sources WHERE id IN ({_in_clause(part)})", part):
                    rows[(lib_id, r["id"])] = r
        # Photo bursts: near-identical shots collapse into the best-ranked one
        photo_hash: Dict[Tuple[str, str], int] = {}
        for lib_id, ids in by_lib.items():
            for part in _chunks(ids):
                for r in libs[lib_id].db.all(
                    f"SELECT source_id, phash FROM visual_items WHERE kind = 'photo' AND phash IS NOT NULL "
                    f"AND source_id IN ({_in_clause(part)})", part):
                    photo_hash[(lib_id, r["source_id"])] = int(r["phash"])
        selected: List[Tuple[FileMatch, Dict[str, Any], str]] = []
        similar: Dict[Tuple[str, str], List[str]] = {}
        kept_photos: List[Tuple[Tuple[str, str], int]] = []
        counts = {k: 0 for k in buckets}
        for f in ranked:
            src = rows.get(f.key)
            if src is None:
                continue   # removed since it was indexed
            kind = src["kind"] if src["kind"] in buckets else "document"
            h = photo_hash.get(f.key)
            if h is not None:
                twin = next((key for key, kh in kept_photos if _hamming_fn(h, kh) <= BURST_MAX_BITS), None)
                if twin is not None:
                    similar.setdefault(twin, []).append(src["id"])
                    continue
            if counts[kind] >= limit:
                continue
            counts[kind] += 1
            selected.append((f, src, kind))
            if h is not None:
                kept_photos.append((f.key, h))
        need = [f for f, _, _ in selected if f.key not in loaded]
        if need:
            passages = {**passages, **self._load_passages(need)}
        for f, src, kind in selected:
            item = self._item(f, src, passages, plan)
            if similar.get(f.key):
                item["similarPhotos"] = similar[f.key]
            buckets[kind].append(item)
        trace["returned"] = {k: len(v) for k, v in buckets.items()}
        return EngineResult(buckets["document"], buckets["video"], buckets["image"], buckets["audio"], trace)

    @staticmethod
    def _spoken_at(lib: Library, source_id: str, t: float) -> str:
        """What is being said around time t (for visual matches in a video)."""
        if lib.db is None:
            return ""
        rows = lib.db.all(
            "SELECT text FROM transcript_segments WHERE source_id = ? AND ts_end >= ? AND ts_start <= ? "
            "ORDER BY ts_start LIMIT 2", (source_id, t - 2.0, t + 4.0))
        return " ".join(r["text"] for r in rows).strip()

    @staticmethod
    def _best_segment_start(lib: Library, source_id: str, chunk: Dict[str, Any], plan: QueryPlan) -> float:
        """A transcript window spans ~40 s: seek to the sentence inside it that matches best."""
        start = float(chunk["ts_start"])
        terms = set(fts_terms(plan.text or plan.rerank_query))
        if not terms or lib.db is None:
            return start
        end = float(chunk.get("ts_end") or start)
        best, best_hits = start, 0
        for seg in lib.db.all(
            "SELECT ts_start, text FROM transcript_segments WHERE source_id = ? AND ts_start >= ? AND ts_start <= ? "
            "ORDER BY ts_start", (source_id, start - 0.01, end + 0.01),
        ):
            hits = len(terms & {w.lower() for w in _WORD_RE.findall(seg["text"] or "")})
            if hits > best_hits:
                best, best_hits = float(seg["ts_start"]), hits
        return best

    @staticmethod
    def _snippet(text: str, plan: QueryPlan, size: int = 350) -> str:
        clean = re.sub(r"\s+", " ", text or "").strip()
        window, cut = focus_window(clean, fts_terms(plan.text or plan.rerank_query), size)
        if not cut:
            return window
        lead = "…" if not clean.startswith(window[:40]) else ""
        tail = "…" if not clean.endswith(window[-40:]) else ""
        return f"{lead}{window.strip()}{tail}"

    def _item(self, f: FileMatch, src: Dict[str, Any], passages: Dict[Tuple[str, str, int], Dict[str, Any]],
              plan: QueryPlan) -> Dict[str, Any]:
        import json
        lib_id, sid = f.lib.id, src["id"]
        kind = src["kind"]
        try:
            meta = json.loads(src.get("meta_json") or "{}")
        except Exception:
            meta = {}
        folder = src.get("folder") or ""
        scope = next((s for s in plan.folder_scopes.get(lib_id, []) if s.contains(folder)), None) \
            if "folder" in f.best else None

        # Best text passage: the reranked one, else the strongest chunk hit
        text_hit = f.rerank_hit if f.rerank_hit is not None and f.rerank_hit.kind == "chunk" else None
        if text_hit is None:
            for retr in TEXT_RETRIEVERS:
                if retr in f.best and f.best[retr].kind == "chunk":
                    text_hit = f.best[retr]
                    break
        chunk = passages.get((lib_id, "chunk", text_hit.entity_id)) if text_hit else None

        # Visual evidence (frames for videos, the matching image inside a document)
        frames: List[Dict[str, Any]] = []
        face_scores: Dict[int, float] = {}
        for h in f.hits.get("face", []):
            row = passages.get((lib_id, "face", h.entity_id))
            if row and row.get("visual_item_id"):
                face_scores[int(row["visual_item_id"])] = max(face_scores.get(int(row["visual_item_id"]), 0.0), h.score)
        visual_scores: Dict[int, float] = {}
        for retr, cal in (("clip_text", cal_clip_text), ("clip_image", cal_clip_image), ("compose", cal_clip_image),
                          ("folder_clip", cal_clip_text)):
            for h in f.hits.get(retr, [])[:12]:
                visual_scores[h.entity_id] = max(visual_scores.get(h.entity_id, 0.0), cal(h.score))
        for h in f.hits.get("dupe", [])[:5]:
            visual_scores[h.entity_id] = max(visual_scores.get(h.entity_id, 0.0), cal_dupe(64.0 - h.score))
        for vid, cos in face_scores.items():
            visual_scores[vid] = max(visual_scores.get(vid, 0.0), cal_face(cos))
        if f.rerank_hit is not None and f.rerank_hit.kind == "visual" and f.rerank is not None:
            vid = f.rerank_hit.entity_id
            visual_scores[vid] = max(visual_scores.get(vid, 0.0), f.rerank)
        for vid, sim in sorted(visual_scores.items(), key=lambda kv: kv[1], reverse=True)[:12]:
            v = passages.get((lib_id, "visual", vid))
            if v is None:
                continue
            is_face = vid in face_scores and face_scores[vid] >= FACE_MATCH
            frames.append({
                "id": vid,
                "frameNumber": len(frames) + 1,
                "sceneId": 1,
                "timestamp": v.get("ts"),
                "page": v.get("page"),
                "kind": v.get("kind"),
                "framePath": f"/api/knowledge/{sid}/frames/{vid}",
                "similarity": round(sim, 2),
                "isFaceMatch": is_face,
                "faceSimilarity": round(face_scores[vid], 4) if vid in face_scores else None,
            })

        visual_wins = f.evidence in VISUAL_RETRIEVERS
        sound_hit = f.best.get(f.evidence) if f.evidence in TIMED_RETRIEVERS else None
        sound_row = passages.get((lib_id, "audio", sound_hit.entity_id)) if sound_hit else None
        start = None
        page = None
        if sound_row is not None:
            start = sound_row.get("ts_start")
        elif visual_wins and frames:
            start, page = frames[0].get("timestamp"), frames[0].get("page")
        elif chunk is not None:
            start, page = chunk.get("ts_start"), chunk.get("page")
            if chunk.get("kind") == "transcript" and chunk.get("ts_start") is not None:
                start = self._best_segment_start(f.lib, sid, chunk, plan)
        elif frames:
            start, page = frames[0].get("timestamp"), frames[0].get("page")

        if sound_row is not None and isinstance(start, (int, float)):
            snippet = f"Sound match at {int(start // 60)}:{int(start % 60):02d}."
            spoken = self._spoken_at(f.lib, sid, start)
            if spoken:
                snippet += f" Said there: “{self._snippet(spoken, plan, 220)}”"
        elif chunk is not None and not (visual_wins and kind in ("image", "video")):
            snippet = self._snippet(chunk["text"], plan)
        elif frames:
            v = passages.get((lib_id, "visual", frames[0]["id"])) or {}
            described = (v.get("caption") or v.get("ocr_text") or "").strip()
            where = f" at {int(start // 60)}:{int(start % 60):02d}" if isinstance(start, (int, float)) else (
                f" on page {page}" if page else "")
            label = "Face match" if frames[0]["isFaceMatch"] else "Visual match"
            snippet = f"{label}{where}." + (f" {self._snippet(described, plan, 250)}" if described else "")
            spoken = self._spoken_at(f.lib, sid, start) if isinstance(start, (int, float)) else ""
            if spoken:
                snippet += f" Said there: “{self._snippet(spoken, plan, 220)}”"
        elif chunk is not None:
            snippet = self._snippet(chunk["text"], plan)
        elif scope is not None or "filter" in f.best:
            snippet = f"In folder {folder}" if folder else "At the top level of the library"
        else:
            snippet = f"File name matches: {src['rel_path']}"

        is_face_match = any(fr["isFaceMatch"] for fr in frames) or (
            f.best.get("face") is not None and f.best["face"].score >= FACE_MATCH)
        thumb = f"/api/knowledge/{sid}/thumbnail" if (meta.get("thumbnail") or kind != "image") else f"/api/knowledge/{sid}/file"
        return {
            "id": f"src-{sid}",
            "sourceId": sid,
            "category": kind,
            "title": src["name"],
            "originalName": src["name"],
            "fileType": src["ext"],
            "fileSize": src["size"],
            "uploadDate": src.get("added_at") or "",
            "relevanceScore": round(f.relevance, 4),
            "snippet": snippet,
            "pageCount": src.get("page_count"),
            "pageNum": page,
            "duration": src.get("duration"),
            "startTime": round(float(start), 1) if kind in ("video", "audio") and isinstance(start, (int, float)) else None,
            "endTime": round(float(start) + 15.0, 1) if kind in ("video", "audio") and isinstance(start, (int, float)) else None,
            "matchingFrames": frames if frames and kind in ("video", "document") else None,
            "primaryFrame": frames[0] if frames and kind == "video" else None,
            "isFaceMatch": is_face_match,
            "faceSimilarity": round(f.best["face"].score, 4) if f.best.get("face") is not None else None,
            "thumbnail": thumb,
            "libraryId": lib_id,
            "libraryName": f.lib.name,
            "relPath": src["rel_path"],
            "folder": folder,
            "folderMatch": scope.path if scope is not None else None,
            "matchedBy": sorted(f.best.keys()),
            "evidence": f.evidence,
            "rerankScore": round(f.rerank, 4) if f.rerank is not None else None,
        }


def plan_from_source(lib: Library, source_id: str) -> QueryPlan:
    """
    'Find similar' query for an indexed file, built from what the index already holds:
    its first passages, the CLIP vectors of its images/frames, its best faces and its
    perceptual hash. Blocking (embeds the passages as queries).
    """
    from app.library.vector_store import decode
    from app.search.plan import ImageSignal, finish_plan
    assert lib.db is not None
    plan = QueryPlan()
    plan.exclude_sources = {source_id}
    rows = lib.db.all(
        "SELECT text FROM chunks WHERE source_id = ? AND kind != 'title' ORDER BY ord LIMIT 3", (source_id,))
    for i, r in enumerate(rows):
        plan.extra.append((f"document passage {i + 1}", r["text"][:1500], 0.8 if i == 0 else 0.6))
    clip_rows = lib.db.all(
        "SELECT emb FROM vectors WHERE space = 'clip' AND source_id = ? ORDER BY id LIMIT 24", (source_id,))
    picks = clip_rows[:: max(1, len(clip_rows) // 3)][:3] if clip_rows else []   # spread over the file
    face_rows = lib.db.all(
        "SELECT v.emb FROM vectors v JOIN faces f ON f.id = v.entity_id "
        "WHERE v.space = 'face' AND v.source_id = ? ORDER BY f.quality DESC LIMIT 3", (source_id,))
    phash = lib.db.scalar(
        "SELECT phash FROM visual_items WHERE source_id = ? AND phash IS NOT NULL ORDER BY id LIMIT 1", (source_id,))
    for i, r in enumerate(picks):
        plan.images.append(ImageSignal(label=f"image {i + 1}", clip_vec=decode(r["emb"]).tolist(),
                                       phash=phash if i == 0 else None))
    faces = [decode(r["emb"]).tolist() for r in face_rows]
    if faces:
        if not plan.images:
            plan.images.append(ImageSignal(label="faces"))
        plan.images[0].faces = faces
    finish_plan(plan)
    return plan


_engine: Optional[SearchEngine] = None


def get_engine() -> SearchEngine:
    global _engine
    if _engine is None:
        _engine = SearchEngine()
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None
