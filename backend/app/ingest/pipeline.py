"""
app/ingest/pipeline.py
~~~~~~~~~~~~~~~~~~~~~~
Indexing worker for folder libraries.

Queue: every library's `sources` table (status 'queued'), ordered by priority
(uploads > changed files > bulk scans) and then by size, smallest first. It survives
restarts; sources interrupted mid-run are re-queued (bounded attempts).

Main pass — text and images. Two stages overlap: while the model stage embeds and
writes file N, the extraction stage parses file N+1 (PDF text, document images, video
keyframes). Chunks are embedded and written in batches as they are produced, so memory
stays flat for files of any size, and the database is never locked while a model runs.
Each run first purges the source's previous derived data, so re-runs and retries never
duplicate anything; a failed run purges its partial data.

Transcription pass — audio and video soundtracks are transcribed after the main queue
is drained (uploads still go first). Whisper then gets the GPU to itself: CLIP waits in
system RAM if VRAM is short, and Whisper itself is parked in RAM between passes, so
switching costs about a second instead of a 30-60 s reload.

Image pass — when the image model changes, a library's old image vectors are dropped
(they can't be compared with the new model's) and re-made from the pictures already on
disk: the original file for photos, the cached copy for everything else.

Stages run on daemon threads so shutdown never waits for a long transcription; work
interrupted that way is simply re-queued.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Collection, Dict, List, Optional, Set, Tuple

import numpy as np

from app.ingest.chunking import chunk_text, transcript_windows
from app.ingest.extract import (
    MIN_PHOTO_SHORT_SIDE, MIN_PHOTO_SIDE, Extraction, Visual, extract, open_image, save_display,
)
from app.library.fingerprint import file_fingerprint
from app.library.manager import Library, LibraryManager, get_library_manager
from app.library.paths import is_asset_dir
from app.library.sources import PRIORITY_UPLOAD, purge_derived
from app.library.vector_store import VectorStore
from app.search.activity import yield_to_searches
from app.search.constants import build_enriched_text

MAX_ATTEMPTS = 3
TEXT_BATCH = 64
VISUAL_BATCH = 16
MODEL_MAX_SIDE = 2048           # photos are decoded at most this large for the models
OCR_MIN_CHARS = 20
OCR_TEXT_GATE = 0.35            # text likelihood above which photos / document images get OCR
FACE_MIN_SIZE_PX = 32           # smaller or less confident faces get no identity vector
FACE_MIN_SCORE = 0.55
FACE_CROP_SIDE = 128
FACE_TRACK_SIMILARITY = 0.6     # same person in nearby keyframes of one video
FACE_TRACK_GAP_S = 12.0
FACE_TRACK_RESAMPLE_S = 60.0    # long appearances get one more identity vector per minute
CHECKPOINT_INTERVAL_S = 60.0
IDLE_POLL_S = 10.0
WHISPER_IDLE_RELEASE_S = 600.0  # free Whisper's RAM after 10 idle minutes

Progress = Callable[[str, int, int], None]


class IndexingCancelled(Exception):
    pass


def _signed64(v: int) -> int:
    return v - (1 << 64) if v >= (1 << 63) else v


def _image_hashes(img) -> Tuple[Optional[int], Optional[int]]:
    try:
        import imagehash
        return _signed64(int(str(imagehash.phash(img)), 16)), _signed64(int(str(imagehash.dhash(img)), 16))
    except Exception:
        return None, None


@dataclass
class PendingChunk:
    kind: str
    text: str
    heading: Optional[str] = None
    page: Optional[int] = None
    ts_start: Optional[float] = None
    ts_end: Optional[float] = None
    visual_item_id: Optional[int] = None


@dataclass
class Prepared:
    lib: Library
    src: Dict[str, Any]
    path: Path
    extraction: Extraction
    fingerprint: Optional[str]
    started: float = field(default_factory=time.time)


# ── claiming ─────────────────────────────────────────────────────────────────
_QUEUED = "status = 'queued'"

# Enrichment passes, in the order they run once the main queue is empty. Each one has a
# state column on `sources` (pending → running → done | failed). "images" only runs after
# the image model changed: it re-makes image vectors without indexing the files again.
PASS_COLUMNS: Dict[str, str] = {
    "images": "image_vectors", "transcribe": "transcript", "caption": "captions", "sounds": "sounds",
}


def _pass_where(column: str) -> str:
    return f"status = 'indexed' AND {column} = 'pending'"


_TRANSCRIBE = _pass_where("transcript")


def _best_candidate(manager: LibraryManager, where: str, busy: List[str]) -> Optional[Tuple[Library, Dict[str, Any]]]:
    exclude = f" AND id NOT IN ({','.join('?' * len(busy))})" if busy else ""
    best: Optional[Tuple[Library, Dict[str, Any]]] = None
    for lib in manager.online():
        if lib.paused or lib.db is None:
            continue
        row = lib.db.one(f"SELECT * FROM sources WHERE {where}{exclude} ORDER BY priority DESC, size ASC LIMIT 1", busy)
        if row and (best is None or (row["priority"], -row["size"]) > (best[1]["priority"], -best[1]["size"])):
            best = (lib, row)
    return best


def claim_next(manager: LibraryManager, busy: Collection[str] = ()) -> Optional[Tuple[Library, Dict[str, Any]]]:
    """
    Atomically take the most urgent queued source across all online, unpaused libraries.
    `busy` holds ids still being worked on in this process (a file that changed while it
    was indexed is re-queued, but must not run twice at the same time).
    """
    busy = list(busy)
    for _ in range(5):
        best = _best_candidate(manager, _QUEUED, busy)
        if best is None:
            return None
        lib, row = best
        if lib.db.execute(
            "UPDATE sources SET status = 'processing', attempts = attempts + 1, error = NULL "
            "WHERE id = ? AND status = 'queued'", (row["id"],),
        ):
            row["attempts"] = int(row["attempts"]) + 1
            row["_claimed_at"] = time.time()
            return lib, row
    return None


def claim_pass(manager: LibraryManager, name: str,
               busy: Collection[str] = ()) -> Optional[Tuple[Library, Dict[str, Any]]]:
    column = PASS_COLUMNS[name]
    busy = list(busy)
    for _ in range(5):
        best = _best_candidate(manager, _pass_where(column), busy)
        if best is None:
            return None
        lib, row = best
        if lib.db.execute(
            f"UPDATE sources SET {column} = 'running' WHERE id = ? AND status = 'indexed' AND {column} = 'pending'",
            (row["id"],),
        ):
            row["_claimed_at"] = time.time()
            return lib, row
    return None


def claim_transcription(manager: LibraryManager, busy: Collection[str] = ()) -> Optional[Tuple[Library, Dict[str, Any]]]:
    return claim_pass(manager, "transcribe", busy)


def next_action(manager: LibraryManager, busy: Collection[str] = ()) -> Optional[str]:
    """
    'index', a pass name ('images' | 'transcribe' | 'caption' | 'sounds') or None. Uploads first;
    enrichment passes when the main queue is empty — except for uploads, whose passes
    also run ahead of bulk indexing.
    """
    busy = list(busy)
    regular = _best_candidate(manager, _QUEUED, busy)
    passes = [(name, _best_candidate(manager, _pass_where(col), busy)) for name, col in PASS_COLUMNS.items()]
    if regular and regular[1]["priority"] >= PRIORITY_UPLOAD:
        return "index"
    for name, best in passes:
        if best and best[1]["priority"] >= PRIORITY_UPLOAD:
            return name
    if regular:
        return "index"
    for name, best in passes:
        if best:
            return name
    return None


# ── main pass, stage 1: extraction ───────────────────────────────────────────
def prepare(lib: Library, src: Dict[str, Any]) -> Prepared:
    path = lib.abs_path(src["rel_path"])
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    purge_derived(lib, src["id"])
    try:
        fingerprint = file_fingerprint(path)
    except OSError:
        fingerprint = None
    ex = extract(src["kind"], path, src["ext"], lib.source_cache_dir(src["id"]))
    return Prepared(lib=lib, src=src, path=path, extraction=ex, fingerprint=fingerprint,
                    started=src.get("_claimed_at") or time.time())


# ── main pass, stage 2: models + writes ──────────────────────────────────────
class _ChunkSink:
    """Embeds and writes chunks in batches as they are produced."""

    def __init__(self, lib: Library, src: Dict[str, Any], counts: Dict[str, int],
                 should_stop: Callable[[], bool], first_ord: int = 0):
        self.lib = lib
        self.src = src
        self.counts = counts
        self.should_stop = should_stop
        self.buf: List[PendingChunk] = []
        self.ord = first_ord

    def add(self, chunk: PendingChunk) -> None:
        if chunk.text and chunk.text.strip():
            self.buf.append(chunk)
            if len(self.buf) >= TEXT_BATCH:
                self.flush()

    def add_text(self, text: str, kind: str, heading: Optional[str] = None, page: Optional[int] = None,
                 visual_item_id: Optional[int] = None, ts: Optional[float] = None) -> None:
        for piece in chunk_text(text):
            self.add(PendingChunk(kind=kind, text=piece, heading=heading, page=page,
                                  ts_start=ts, visual_item_id=visual_item_id))

    def flush(self) -> None:
        if not self.buf:
            return
        if self.should_stop():
            raise IndexingCancelled()
        yield_to_searches()
        from app.search import model_pipeline as mp
        lib, src = self.lib, self.src
        assert lib.db is not None and lib.vectors is not None
        batch, self.buf = self.buf, []
        vecs = mp.get_text_embeddings_batch([build_enriched_text(p.heading or "", p.text) for p in batch])
        rows: List[Tuple[int, str, List[float]]] = []
        with lib.db.write() as c:
            for p, vec in zip(batch, vecs):
                cur = c.execute(
                    """INSERT INTO chunks (source_id, kind, text, heading, page, ts_start, ts_end, visual_item_id, ord)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (src["id"], p.kind, p.text, p.heading, p.page, p.ts_start, p.ts_end, p.visual_item_id, self.ord),
                )
                self.ord += 1
                if vec is not None:
                    rows.append((int(cur.lastrowid), src["id"], vec))
            vec_ids = VectorStore.insert_rows(c, "text", rows)
        lib.vectors.index_rows("text", vec_ids, [r[2] for r in rows])
        self.counts["chunks"] = self.counts.get("chunks", 0) + len(batch)
        self.counts["text_vectors"] = self.counts.get("text_vectors", 0) + len(vec_ids)


class _FaceTracker:
    """Follows the same face across nearby keyframes of one video."""

    def __init__(self) -> None:
        self.tracks: List[Dict[str, Any]] = []
        self.next_id = 1

    def match(self, emb: np.ndarray, ts: float, good: bool) -> Dict[str, Any]:
        self.tracks = [t for t in self.tracks if ts - t["last_ts"] <= FACE_TRACK_GAP_S]
        best, best_sim = None, 0.0
        for t in self.tracks:
            sim = float(np.dot(t["emb"], emb))
            if sim > best_sim:
                best, best_sim = t, sim
        if best is not None and best_sim >= FACE_TRACK_SIMILARITY:
            best["last_ts"] = ts
            if good:
                best["emb"] = emb  # follow gradual changes of pose and lighting
            return best
        track = {"id": self.next_id, "emb": emb, "last_ts": ts, "vector_ts": None}
        self.next_id += 1
        self.tracks.append(track)
        return track


_ocr_executor: Optional[ThreadPoolExecutor] = None
_ocr_lock = threading.Lock()


def _ocr_pool() -> ThreadPoolExecutor:
    global _ocr_executor
    with _ocr_lock:
        if _ocr_executor is None:
            workers = max(2, min(4, (os.cpu_count() or 4) // 3))
            _ocr_executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="smartfind-ocr")
        return _ocr_executor


def _load_visual(v: Visual, cache_dir: Path):
    try:
        img = v.render() if v.render is not None else open_image(v.path, max_side=MODEL_MAX_SIDE)
    except Exception:
        return None
    if v.write_cache and v.cache_rel:
        try:
            w, h = save_display(img, cache_dir / v.cache_rel)
            v.width, v.height = v.width or w, v.height or h
        except Exception:
            pass
    return img


def _save_face_crop(img, box: List[float], dest: Path) -> bool:
    """box = [ymin, xmin, ymax, xmax] (normalized). Crops with a margin around the face."""
    try:
        ymin, xmin, ymax, xmax = box
        w, h = img.width, img.height
        mx, my = (xmax - xmin) * 0.25, (ymax - ymin) * 0.25
        crop = img.crop((
            int(max(0.0, xmin - mx) * w), int(max(0.0, ymin - my) * h),
            int(min(1.0, xmax + mx) * w), int(min(1.0, ymax + my) * h),
        ))
        if crop.width < 8 or crop.height < 8:
            return False
        save_display(crop, dest, max_side=FACE_CROP_SIDE)
        return True
    except Exception:
        return False


def _process_visuals(prep: Prepared, sink: _ChunkSink, counts: Dict[str, int],
                     progress: Progress, should_stop: Callable[[], bool]) -> None:
    from app.search import model_pipeline as mp
    lib, src, ex = prep.lib, prep.src, prep.extraction
    assert lib.db is not None and lib.vectors is not None
    cache_dir = lib.source_cache_dir(src["id"])
    tracker = _FaceTracker()
    total = len(ex.visuals)
    if total:
        mp.prepare_for_pictures()

    for start in range(0, total, VISUAL_BATCH):
        if should_stop():
            raise IndexingCancelled()
        yield_to_searches()
        progress("images", start, total)
        batch = ex.visuals[start:start + VISUAL_BATCH]
        loaded = [(v, _load_visual(v, cache_dir)) for v in batch]
        valid = [(v, img) for v, img in loaded if img is not None]
        counts["unreadable_images"] += len(loaded) - len(valid)
        clip_vecs = mp.get_image_embeddings_batch([img for _, img in valid]) if valid else []

        # Tesseract runs as a separate process: start every OCR job of the batch at once, so
        # they overlap each other and the GPU's face detection below
        ocr_jobs = {}
        for (v, img), cvec in zip(valid, clip_vecs):
            if v.ocr:
                likely = mp.text_likelihood(cvec) if v.ocr_gate else None
                if not v.ocr_gate or likely is None or likely >= OCR_TEXT_GATE:
                    ocr_jobs[id(v)] = _ocr_pool().submit(mp.run_ocr, img)
                    counts["ocr_runs"] += 1

        analysed = []
        for (v, img), cvec in zip(valid, clip_vecs):
            faces = mp.detect_and_embed_faces(img, min_confidence=0.5, model_name=mp.LIBRARY_FACE_MODEL) if v.faces else []
            ph, dh = _image_hashes(img)
            job = ocr_jobs.get(id(v))
            analysed.append((v, img, cvec, job.result() if job else "", faces, ph, dh))

        clip_rows: List[Tuple[int, str, List[float]]] = []
        face_rows: List[Tuple[int, str, List[float]]] = []
        ocr_chunks: List[Tuple[Visual, int, str]] = []
        with lib.db.write() as c:
            for v, img, cvec, ocr_text, faces, ph, dh in analysed:
                cur = c.execute(
                    """INSERT INTO visual_items (source_id, kind, page, ts, cache_path, width, height, ocr_text, phash, dhash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (src["id"], v.kind, v.page, v.ts, v.cache_rel, v.width or img.width, v.height or img.height,
                     ocr_text or None, ph, dh),
                )
                vid = int(cur.lastrowid)
                counts["visuals"] += 1
                if cvec is not None:
                    clip_rows.append((vid, src["id"], cvec))
                if ocr_text.strip():
                    ocr_chunks.append((v, vid, ocr_text.strip()))
                for i, face in enumerate(faces):
                    emb = np.asarray(face["embedding"], dtype=np.float32)
                    size_px = int(face.get("size_px") or 0)
                    det = float(face.get("confidence") or 0.0)
                    good = size_px >= FACE_MIN_SIZE_PX and det >= FACE_MIN_SCORE
                    quality = round(det * min(1.0, size_px / 112.0), 4)
                    track_id: Optional[int] = None
                    store = good
                    if v.kind == "keyframe" and v.ts is not None:
                        track = tracker.match(emb, v.ts, good)
                        track_id = track["id"]
                        store = good and (track["vector_ts"] is None or v.ts - track["vector_ts"] >= FACE_TRACK_RESAMPLE_S)
                        if store:
                            track["vector_ts"] = v.ts
                    crop_rel = None
                    if store and _save_face_crop(img, face["box"], cache_dir / "faces" / f"{vid}_{i}.webp"):
                        crop_rel = f"faces/{vid}_{i}.webp"
                    ymin, xmin, ymax, xmax = face["box"]
                    fcur = c.execute(
                        """INSERT INTO faces (source_id, visual_item_id, ts, page, bbox, det_score, quality, crop_path, track_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (src["id"], vid, v.ts, v.page,
                         json.dumps([round(xmin, 4), round(ymin, 4), round(xmax, 4), round(ymax, 4)]),
                         round(det, 4), quality, crop_rel, track_id),
                    )
                    counts["faces"] += 1
                    if store:
                        face_rows.append((int(fcur.lastrowid), src["id"], face["embedding"]))
            clip_ids = VectorStore.insert_rows(c, "clip", clip_rows)
            face_ids = VectorStore.insert_rows(c, "face", face_rows)
        lib.vectors.index_rows("clip", clip_ids, [r[2] for r in clip_rows])
        lib.vectors.index_rows("face", face_ids, [r[2] for r in face_rows])
        counts["face_vectors"] += len(face_ids)

        # OCR text becomes searchable chunks linked to its image (the page text for scans)
        for v, vid, text in ocr_chunks:
            if v.page_text:
                sink.add_text(text, "ocr", heading=f"Page {v.page}" if v.page else None, page=v.page, visual_item_id=vid)
                ex.sections.append({"title": f"Page {v.page}", "page": v.page, "char_count": len(text)})
            elif len(text) >= OCR_MIN_CHARS and len(text.split()) >= 3:
                sink.add_text(text, "ocr", page=v.page, visual_item_id=vid, ts=v.ts)
        for v, _ in loaded:
            if v.work and v.path is not None:
                v.path.unlink(missing_ok=True)
    progress("images", total, total)


def finish(prep: Prepared, progress: Optional[Progress] = None,
           should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    lib, src, ex = prep.lib, prep.src, prep.extraction
    assert lib.db is not None
    progress = progress or (lambda stage, done, total: None)
    should_stop = should_stop or (lambda: False)
    counts = {"visuals": 0, "unreadable_images": 0, "small_images": int(bool(ex.meta.get("small_image"))),
              "ocr_runs": 0, "faces": 0, "face_vectors": 0, "chunks": 0, "text_vectors": 0}
    sink = _ChunkSink(lib, src, counts, should_stop)

    progress("text", 0, 0)
    for block in ex.iter_blocks():
        if block.kind == "table":
            sink.add(PendingChunk(kind="table", text=block.text, heading=block.heading, page=block.page))
        else:
            sink.add_text(block.text, block.kind, heading=block.heading, page=block.page)
    # A title chunk keeps every file findable by name and folder, even without content
    stem = Path(src["name"]).stem.replace("_", " ").replace("-", " ").strip()
    folder = str(Path(src["rel_path"]).parent).replace("\\", "/")
    sink.add(PendingChunk(kind="title", text=stem or src["name"], heading=None if folder in (".", "") else folder))
    sink.flush()

    _process_visuals(prep, sink, counts, progress, should_stop)
    sink.flush()

    try:
        meta = json.loads(src.get("meta_json") or "{}")
    except Exception:
        meta = {}
    meta.pop("processing_info", None)
    if ex.thumbnail_rel:
        meta["thumbnail"] = ex.thumbnail_rel
    else:
        meta.pop("thumbnail", None)
    if ex.meta.get("camera"):
        meta["camera"] = ex.meta["camera"]
    meta["counts"] = counts
    elapsed = round(time.time() - prep.started, 2)

    with lib.db.write() as c:
        for i, s in enumerate(ex.sections):
            c.execute(
                "INSERT INTO sections (id, source_id, title, page, ord, char_count) VALUES (?, ?, ?, ?, ?, ?)",
                (f"{src['id']}:{i}", src["id"], s.get("title"), s.get("page"), i, int(s.get("char_count") or 0)),
            )
        has_pictures = c.execute(
            f"SELECT 1 FROM visual_items v WHERE v.source_id = ? AND {_DESCRIBABLE} LIMIT 1",
            (src["id"], *_DESCRIBABLE_ARGS)).fetchone()
        audio = "pending" if ex.transcribe is not None else None
        updated = c.execute(
            """UPDATE sources SET status = 'indexed', indexed_at = datetime('now'), error = NULL, fingerprint = ?,
                   page_count = ?, duration = ?, width = ?, height = ?, taken_at = ?, gps_lat = ?, gps_lon = ?,
                   transcript = ?, sounds = ?, captions = ?, image_vectors = NULL, meta_json = ?
               WHERE id = ? AND status = 'processing'""",
            (prep.fingerprint, ex.meta.get("page_count"), ex.meta.get("duration"), ex.meta.get("width"),
             ex.meta.get("height"), ex.meta.get("taken_at"), ex.meta.get("gps_lat"), ex.meta.get("gps_lon"),
             audio, audio, "pending" if has_pictures else None, json.dumps(meta), src["id"]),
        ).rowcount
        c.execute(
            "INSERT OR REPLACE INTO source_logs (source_id, info_json) VALUES (?, ?)",
            (src["id"], json.dumps({"seconds": elapsed, "counts": counts, "log": ex.log[-200:]})),
        )
    # updated == 0: the file changed (re-queued) while it was being indexed; the next run
    # purges this run's rows first, so nothing is left behind.
    return {"seconds": elapsed, "current": bool(updated), "transcribe": ex.transcribe is not None, **counts}


def mark_failed(lib: Library, src: Dict[str, Any], error: str) -> None:
    if lib.db is None:
        return
    try:
        purge_derived(lib, src["id"])
    except Exception:
        pass
    lib.db.execute(
        "UPDATE sources SET status = 'failed', transcript = NULL, captions = NULL, sounds = NULL, "
        "image_vectors = NULL, error = ? "
        "WHERE id = ? AND status = 'processing'",
        (error[:2000], src["id"]),
    )


def requeue(lib: Library, src: Dict[str, Any]) -> None:
    """Give back a claimed source that was not finished (shutdown); not counted as an attempt."""
    if lib.db is None:
        return
    lib.db.execute(
        "UPDATE sources SET status = 'queued', attempts = MAX(attempts - 1, 0) WHERE id = ? AND status = 'processing'",
        (src["id"],),
    )


# ── transcription pass ───────────────────────────────────────────────────────
def transcribe_source(lib: Library, src: Dict[str, Any], should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """Transcribe one indexed audio/video source; replaces any previous transcript of it."""
    from app.search import model_pipeline as mp
    assert lib.db is not None and lib.vectors is not None
    should_stop = should_stop or (lambda: False)
    t0 = time.time()
    path = lib.abs_path(src["rel_path"])
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    result = mp.transcribe_media(str(path), should_stop=should_stop)
    if should_stop():
        raise IndexingCancelled()
    segments = result.get("segments") or []

    with lib.db.write() as c:
        old = [r["id"] for r in c.execute(
            "SELECT id FROM chunks WHERE source_id = ? AND kind = 'transcript'", (src["id"],)
        ).fetchall()]
        by_space = lib.vectors.collect_entities(c, "text", old)
        c.execute("DELETE FROM chunks WHERE source_id = ? AND kind = 'transcript'", (src["id"],))
        c.execute("DELETE FROM transcript_segments WHERE source_id = ?", (src["id"],))
        c.executemany(
            "INSERT INTO transcript_segments (source_id, ts_start, ts_end, text) VALUES (?, ?, ?, ?)",
            [(src["id"], s["start"], s["end"], s["text"]) for s in segments],
        )
        first_ord = int(c.execute("SELECT COALESCE(MAX(ord), -1) + 1 AS n FROM chunks WHERE source_id = ?",
                                  (src["id"],)).fetchone()["n"])
    lib.vectors.unindex(by_space)

    counts: Dict[str, int] = {"segments": len(segments), "chunks": 0, "text_vectors": 0}
    sink = _ChunkSink(lib, src, counts, should_stop, first_ord=first_ord)
    for w in transcript_windows(segments):
        sink.add(PendingChunk(kind="transcript", text=w["text"], ts_start=w["ts_start"], ts_end=w["ts_end"]))
    sink.flush()

    with lib.db.write() as c:
        row = c.execute("SELECT meta_json FROM sources WHERE id = ?", (src["id"],)).fetchone()
        try:
            meta = json.loads((row or {}).get("meta_json") or "{}")
        except Exception:
            meta = {}
        meta.setdefault("counts", {})["segments"] = len(segments)
        if result.get("language"):
            meta["language"] = result["language"]
        c.execute(
            "UPDATE sources SET transcript = 'done', meta_json = ? WHERE id = ? AND transcript = 'running'",
            (json.dumps(meta), src["id"]),
        )
    return {"seconds": round(time.time() - t0, 2), **counts}


def requeue_transcription(lib: Library, src: Dict[str, Any]) -> None:
    requeue_pass(lib, src, "transcribe")


def mark_transcription_failed(lib: Library, src: Dict[str, Any], error: str) -> None:
    mark_pass_failed(lib, src, "transcribe", error)


# ── caption pass (Florence-2) ────────────────────────────────────────────────
CAPTION_IMAGE_SIDE = 768        # Florence-2 works at 768 px
CAPTION_BATCH = 8
FRAME_TEXT_GATE = 0.5           # video frames need to look clearly like text to be OCR'd
MIN_DESCRIBE_SIDE = 160         # pictures whose longest side is smaller are never described
MIN_DESCRIBE_SHORT_SIDE = 64    # ...nor thin strips and banners
# Icons, buttons and other small graphics are not worth describing: they cost GPU time
# and add junk to results. Scanned pages have their text; they are not described either.
_DESCRIBABLE = ("v.kind != 'page' AND MAX(COALESCE(v.width, 0), COALESCE(v.height, 0)) >= ? "
                "AND MIN(COALESCE(v.width, 0), COALESCE(v.height, 0)) >= ?")
_DESCRIBABLE_ARGS = (MIN_DESCRIBE_SIDE, MIN_DESCRIBE_SHORT_SIDE)


def _replace_chunks(lib: Library, src: Dict[str, Any], kind: str) -> int:
    """Delete a source's chunks of one kind (and their vectors); returns the next free ord."""
    assert lib.db is not None and lib.vectors is not None
    with lib.db.write() as c:
        old = [r["id"] for r in c.execute(
            "SELECT id FROM chunks WHERE source_id = ? AND kind = ?", (src["id"], kind)).fetchall()]
        by_space = lib.vectors.collect_entities(c, "text", old)
        c.execute("DELETE FROM chunks WHERE source_id = ? AND kind = ?", (src["id"], kind))
        first_ord = int(c.execute("SELECT COALESCE(MAX(ord), -1) + 1 AS n FROM chunks WHERE source_id = ?",
                                  (src["id"],)).fetchone()["n"])
    lib.vectors.unindex(by_space)
    return first_ord


def visual_image(lib: Library, src: Dict[str, Any], v: Dict[str, Any], max_side: int):
    """A visual item's picture as kept on disk: the original file for photos, otherwise its
    cached copy (keyframes, pages and document images). Raises when it can't be read."""
    if v["kind"] == "photo":
        return open_image(lib.abs_path(src["rel_path"]), max_side=max_side)
    return open_image(lib.source_cache_dir(src["id"]) / (v["cache_path"] or ""), max_side=max_side)


def caption_source(lib: Library, src: Dict[str, Any], should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """
    Describe a source's pictures with Florence-2 (photos, video keyframes, images inside
    documents) and read on-screen text in video frames that look like they contain text.
    Descriptions become searchable chunks linked to their picture, page or timestamp.
    """
    from app.library.vector_store import decode
    from app.search import model_pipeline as mp
    assert lib.db is not None
    should_stop = should_stop or (lambda: False)
    t0 = time.time()
    visuals = lib.db.all(
        "SELECT v.id, v.kind, v.page, v.ts, v.cache_path, v.ocr_text, vec.emb AS clip "
        "FROM visual_items v LEFT JOIN vectors vec ON vec.space = 'clip' AND vec.entity_id = v.id "
        f"WHERE v.source_id = ? AND {_DESCRIBABLE} ORDER BY v.id",
        (src["id"], *_DESCRIBABLE_ARGS))
    first_ord = _replace_chunks(lib, src, "caption")
    counts: Dict[str, int] = {"captions": 0, "frame_text": 0, "chunks": 0, "text_vectors": 0}
    sink = _ChunkSink(lib, src, counts, should_stop, first_ord=first_ord)
    seen: Set[str] = set()

    for start in range(0, len(visuals), CAPTION_BATCH):
        if should_stop():
            raise IndexingCancelled()
        yield_to_searches()
        batch = visuals[start:start + CAPTION_BATCH]
        images, rows = [], []
        for v in batch:
            try:
                images.append(visual_image(lib, src, v, CAPTION_IMAGE_SIDE))
                rows.append(v)
            except Exception:
                continue
        if not images:
            continue
        captions = mp.florence_describe(images, mp.CAPTION_TASK)
        # On-screen text for video frames that clearly show text (slides, signs, tickers).
        # run_ocr (PP-OCRv6, Tesseract for Hindi) on an upscaled frame: Florence-2's OCR
        # garbles Devanagari.
        texts: Dict[int, str] = {}
        for i, v in enumerate(rows):
            if v["kind"] != "keyframe" or v["ocr_text"] or not v["clip"]:
                continue
            if (mp.text_likelihood(decode(v["clip"]).tolist()) or 0.0) < FRAME_TEXT_GATE:
                continue
            im = images[i]
            texts[i] = mp.run_ocr(im.resize((im.width * 2, im.height * 2))) if max(im.size) < 1000 else mp.run_ocr(im)
        with lib.db.write() as c:
            for i, (v, caption) in enumerate(zip(rows, captions)):
                ocr = (texts.get(i) or "").strip()
                c.execute("UPDATE visual_items SET caption = ?, ocr_text = COALESCE(?, ocr_text) WHERE id = ?",
                          (caption, ocr or None, v["id"]))
        for i, (v, caption) in enumerate(zip(rows, captions)):
            where = (f"Frame at {int(v['ts'] // 60)}:{int(v['ts'] % 60):02d}" if v["ts"] is not None
                     else f"Picture on page {v['page']}" if v["page"] else "Picture")
            if caption and caption.lower() not in seen:     # similar frames repeat a description
                seen.add(caption.lower())
                sink.add(PendingChunk(kind="caption", text=caption, heading=where, page=v["page"],
                                      ts_start=v["ts"], visual_item_id=v["id"]))
                counts["captions"] += 1
            ocr = (texts.get(i) or "").strip()
            if len(ocr) >= OCR_MIN_CHARS and len(ocr.split()) >= 3:
                sink.add(PendingChunk(kind="ocr", text=ocr, heading=where, ts_start=v["ts"], visual_item_id=v["id"]))
                counts["frame_text"] += 1
    sink.flush()
    lib.db.execute("UPDATE sources SET captions = 'done' WHERE id = ? AND captions = 'running'", (src["id"],))
    return {"seconds": round(time.time() - t0, 2), **counts}


# ── sound pass (CLAP) ────────────────────────────────────────────────────────
def sound_source(lib: Library, src: Dict[str, Any], should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """CLAP vectors for every 10 s of a file's soundtrack (barking, applause, music, rain…)."""
    from app.search import model_pipeline as mp
    assert lib.db is not None and lib.vectors is not None
    should_stop = should_stop or (lambda: False)
    t0 = time.time()
    path = lib.abs_path(src["rel_path"])
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    windows = mp.clap_audio_windows(str(path), should_stop=should_stop)
    if should_stop():
        raise IndexingCancelled()
    with lib.db.write() as c:
        old = [r["id"] for r in c.execute("SELECT id FROM audio_segments WHERE source_id = ?", (src["id"],)).fetchall()]
        by_space = lib.vectors.collect_entities(c, "clap", old)
        c.execute("DELETE FROM audio_segments WHERE source_id = ?", (src["id"],))
    lib.vectors.unindex(by_space)
    rows: List[Tuple[int, str, List[float]]] = []
    with lib.db.write() as c:
        for start, end, vec in windows:
            cur = c.execute("INSERT INTO audio_segments (source_id, ts_start, ts_end) VALUES (?, ?, ?)",
                            (src["id"], start, end))
            rows.append((int(cur.lastrowid), src["id"], vec))
        ids = VectorStore.insert_rows(c, "clap", rows)
        c.execute("UPDATE sources SET sounds = 'done' WHERE id = ? AND sounds = 'running'", (src["id"],))
    lib.vectors.index_rows("clap", ids, [r[2] for r in rows])
    return {"seconds": round(time.time() - t0, 2), "windows": len(rows)}


# ── image pass (after the image model changed) ───────────────────────────────
def reembed_images_source(lib: Library, src: Dict[str, Any],
                          should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """Re-make a source's image vectors with the current image model."""
    from app.search import model_pipeline as mp
    assert lib.db is not None and lib.vectors is not None
    should_stop = should_stop or (lambda: False)
    t0 = time.time()
    visuals = lib.db.all("SELECT id, kind, cache_path FROM visual_items WHERE source_id = ? ORDER BY id", (src["id"],))
    counts: Dict[str, int] = {"vectors": 0, "unreadable_images": 0}
    for start in range(0, len(visuals), VISUAL_BATCH):
        if should_stop():
            raise IndexingCancelled()
        yield_to_searches()
        loaded = []
        for v in visuals[start:start + VISUAL_BATCH]:
            try:
                loaded.append((v, visual_image(lib, src, v, MODEL_MAX_SIDE)))
            except Exception:
                counts["unreadable_images"] += 1
        if not loaded:
            continue
        vecs = mp.get_image_embeddings_batch([img for _, img in loaded])
        if all(vec is None for vec in vecs):
            raise RuntimeError("the image model is unavailable")
        rows = [(v["id"], src["id"], vec) for (v, _), vec in zip(loaded, vecs) if vec is not None]
        with lib.db.write() as c:
            old = lib.vectors.collect_entities(c, "clip", [v["id"] for v, _ in loaded])
            ids = VectorStore.insert_rows(c, "clip", rows)
        lib.vectors.unindex(old)
        lib.vectors.index_rows("clip", ids, [r[2] for r in rows])
        counts["vectors"] += len(ids)
    lib.db.execute("UPDATE sources SET image_vectors = 'done' WHERE id = ? AND image_vectors = 'running'", (src["id"],))
    return {"seconds": round(time.time() - t0, 2), **counts}


PASS_RUNNERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "images": reembed_images_source, "transcribe": transcribe_source, "caption": caption_source,
    "sounds": sound_source,
}
_PASS_LABELS = {"images": "Updating image search", "transcribe": "Transcription", "caption": "Describing pictures",
                "sounds": "Sound analysis"}


def _pass_models(name: str) -> Tuple[Callable[[], None], Callable[[], None]]:
    from app.search import model_pipeline as mp
    return {
        "images": (mp.prepare_for_image_vectors, mp.finish_image_vectors),
        "transcribe": (mp.prepare_for_transcription, mp.finish_transcription),
        "caption": (mp.prepare_for_captions, mp.finish_captions),
        "sounds": (mp.prepare_for_sounds, mp.finish_sounds),
    }[name]


def requeue_pass(lib: Library, src: Dict[str, Any], name: str) -> None:
    column = PASS_COLUMNS[name]
    if lib.db is not None:
        lib.db.execute(f"UPDATE sources SET {column} = 'pending' WHERE id = ? AND {column} = 'running'", (src["id"],))


def mark_pass_failed(lib: Library, src: Dict[str, Any], name: str, error: str) -> None:
    column = PASS_COLUMNS[name]
    if lib.db is not None:
        lib.db.execute(
            f"UPDATE sources SET {column} = 'failed', error = ? WHERE id = ? AND {column} = 'running'",
            (f"{_PASS_LABELS[name]} failed: {error}"[:2000], src["id"]),
        )


def run_pass(manager: LibraryManager, name: str) -> int:
    """Synchronously run one enrichment pass over everything pending (tests and scripts)."""
    prepare_models, finish_models = _pass_models(name)
    done = 0
    prepare_models()
    try:
        while (job := claim_pass(manager, name)) is not None:
            lib, src = job
            try:
                PASS_RUNNERS[name](lib, src)
                done += 1
            except Exception as e:
                mark_pass_failed(lib, src, name, f"{type(e).__name__}: {e}")
    finally:
        finish_models()
    return done


def run_transcriptions(manager: LibraryManager) -> int:
    return run_pass(manager, "transcribe")


def run_all_passes(manager: LibraryManager) -> Dict[str, int]:
    return {name: run_pass(manager, name) for name in PASS_COLUMNS}


# ── recovery ─────────────────────────────────────────────────────────────────
def recover_library(lib: Library) -> int:
    """
    Sources a previous run left in 'processing' go back to the queue (bounded attempts).
    Only call when nothing of this library is in flight: at startup, or when its folder
    comes back online.
    """
    if lib.db is None:
        return 0
    n = lib.db.execute(
        "UPDATE sources SET status = 'queued' WHERE status = 'processing' AND attempts < ?", (MAX_ATTEMPTS,)
    )
    lib.db.execute(
        "UPDATE sources SET status = 'failed', error = 'Indexing was interrupted repeatedly' "
        "WHERE status = 'processing' AND attempts >= ?", (MAX_ATTEMPTS,)
    )
    for column in PASS_COLUMNS.values():
        lib.db.execute(f"UPDATE sources SET {column} = 'pending' WHERE {column} = 'running'")
    small = requeue_undersized_images(lib)
    if small:
        print(f"[Indexer] {lib.name}: {small} small images queued to be indexed by name only")
    stale = requeue_stale_image_vectors(lib)
    if stale:
        print(f"[Indexer] {lib.name}: image model changed; {stale} files queued to update their image vectors")
    return n + small


def requeue_stale_image_vectors(lib: Library) -> int:
    """
    Image vectors from another image model (older libraries: Jina CLIP v2) can't be
    compared with the current model's: drop them all and queue the image pass for every
    indexed file with pictures. A library without image vectors just records the model.
    Matches nothing once the library records the current model.
    """
    from app.search.constants import IMAGE_EMBED_MODEL
    if lib.db is None or lib.vectors is None or lib.vectors.space_model("clip") == IMAGE_EMBED_MODEL:
        return 0
    n = 0
    if lib.db.scalar("SELECT 1 FROM vectors WHERE space = 'clip' LIMIT 1"):
        # Queued before the vectors are dropped: an interruption in between repeats this step
        n = lib.db.execute(
            "UPDATE sources SET image_vectors = 'pending' WHERE status = 'indexed' "
            "AND EXISTS (SELECT 1 FROM visual_items v WHERE v.source_id = sources.id)")
    lib.vectors.reset_space("clip", IMAGE_EMBED_MODEL)
    return n


def requeue_undersized_images(lib: Library) -> int:
    """
    Images indexed before the size rules (icons, strips) still carry an image vector and
    a description; index them again, by name only. Matches nothing once that is done.
    """
    if lib.db is None:
        return 0
    # Only known sizes: rows without one (e.g. migrated from the old index) are left alone
    rows = lib.db.all(
        "SELECT id, rel_path FROM sources WHERE kind = 'image' AND status = 'indexed' "
        "AND width > 0 AND height > 0 AND (MAX(width, height) < ? OR MIN(width, height) < ?) "
        "AND EXISTS (SELECT 1 FROM visual_items v WHERE v.source_id = sources.id)",
        (MIN_PHOTO_SIDE, MIN_PHOTO_SHORT_SIDE),
    )
    # Files in icon folders are about to be dropped by the startup scan instead
    ids = [(r["id"],) for r in rows
           if not any(is_asset_dir(part) for part in PurePosixPath(r["rel_path"]).parts[:-1])]
    with lib.db.write() as c:
        c.executemany("UPDATE sources SET status = 'queued', attempts = 0 WHERE id = ? AND status = 'indexed'", ids)
    return len(ids)


def recover_interrupted(manager: LibraryManager) -> int:
    return sum(recover_library(lib) for lib in manager.online())


# ── worker ───────────────────────────────────────────────────────────────────
def _run_on_daemon_thread(fn: Callable[..., Any], *args: Any) -> "asyncio.Future[Any]":
    """Like asyncio.to_thread, but on a daemon thread that never blocks process exit."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def _deliver(setter: Callable[[Any], None], value: Any) -> None:
        if not fut.done():
            setter(value)

    def _runner() -> None:
        try:
            result = fn(*args)
        except BaseException as e:  # noqa: BLE001 — handed to the awaiting coroutine
            outcome = (fut.set_exception, e)
        else:
            outcome = (fut.set_result, result)
        try:
            loop.call_soon_threadsafe(_deliver, *outcome)
        except RuntimeError:
            pass  # event loop already closed (shutdown)

    threading.Thread(target=_runner, name="smartfind-indexer", daemon=True).start()
    return fut


@dataclass
class _Job:
    lib: Library
    src: Dict[str, Any]
    prepare: "asyncio.Future[Prepared]"


class IngestionPipeline:
    def __init__(self, manager: Optional[LibraryManager] = None):
        self.manager = manager or get_library_manager()
        self.paused = False
        self.current: Optional[Dict[str, Any]] = None
        self.last_error: Optional[str] = None
        self.completed = 0
        self.failed = 0
        self.enriched: Dict[str, int] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._wake: Optional[asyncio.Event] = None
        self._tasks: List[asyncio.Task] = []
        self._claimed: Dict[str, Tuple[Library, Dict[str, Any], str]] = {}
        self._stopping = False
        self._last_enrichment = 0.0
        # Held while _on_idle runs: cancelling the loop leaves its worker thread running,
        # and closing the libraries under it crashes SQLite, so stop() waits for it
        self._idle_lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        from app.processing.queue import spawn_background
        recover_interrupted(self.manager)
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._stopping = False
        self._tasks = [spawn_background(self._run()), spawn_background(self._checkpoint_loop())]

    async def stop(self) -> None:
        self._stopping = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except BaseException:
                pass
        self._tasks = []
        await asyncio.to_thread(self._wait_idle_round)
        # Claimed but unfinished work goes back to the queue (a still-running stage
        # thread can no longer mark it done: its final update requires the claimed state)
        for lib, src, kind in list(self._claimed.values()):
            try:
                if kind in PASS_COLUMNS:
                    requeue_pass(lib, src, kind)
                else:
                    requeue(lib, src)
            except Exception:
                pass
        self._claimed.clear()
        try:
            await asyncio.to_thread(self.manager.checkpoint_all)
        except Exception as e:
            print(f"[Indexer] Final checkpoint notice: {e}")

    def wake(self) -> None:
        """Signal that new work may be queued (safe to call from any thread)."""
        loop, event = self._loop, self._wake
        if loop is None or event is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            pass

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False
        self.wake()

    @property
    def running(self) -> bool:
        return bool(self._tasks) and not self._stopping

    # ── loop ─────────────────────────────────────────────────────────────────
    def _should_stop(self) -> bool:
        return self._stopping

    async def _wait(self, timeout: float) -> None:
        assert self._wake is not None
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    async def _claim(self) -> Optional[_Job]:
        if self.paused or self._stopping:
            return None
        job = await asyncio.to_thread(claim_next, self.manager, list(self._claimed))
        if job is None:
            return None
        lib, src = job
        self._claimed[src["id"]] = (lib, src, "index")
        return _Job(lib, src, _run_on_daemon_thread(prepare, lib, src))

    async def _run(self) -> None:
        nxt: Optional[_Job] = None
        while not self._stopping:
            try:
                if self.paused and nxt is None:
                    await self._wait(2.0)
                    continue
                if nxt is not None:
                    nxt = await self._process(nxt)
                    continue
                action = await asyncio.to_thread(next_action, self.manager, list(self._claimed))
                if action == "index":
                    job = await self._claim()
                    if job is not None:
                        nxt = await self._process(job)
                elif action in PASS_COLUMNS:
                    await self._enrichment_pass(action)
                else:
                    await asyncio.to_thread(self._on_idle)
                    await self._wait(IDLE_POLL_S)
            except asyncio.CancelledError:
                break
            except Exception as e:
                traceback.print_exc()
                self.last_error = str(e)
                await asyncio.sleep(2.0)

    async def _process(self, job: _Job) -> Optional[_Job]:
        """Index one claimed source; returns the next job, whose extraction already started."""
        lib, src = job.lib, job.src
        nxt: Optional[_Job] = None
        self.current = {"libraryId": lib.id, "library": lib.name, "sourceId": src["id"], "file": src["rel_path"],
                        "kind": src["kind"], "size": src["size"], "stage": "extracting",
                        "done": 0, "total": 0, "startedAt": time.time()}
        try:
            try:
                prepared: Prepared = await job.prepare
            except Exception as e:
                nxt = await self._claim()
                await asyncio.to_thread(mark_failed, lib, src, f"{type(e).__name__}: {e}")
                self._fail(lib, src, e)
                return nxt

            # Overlap: extract the next file while the models work on this one
            nxt = await self._claim()

            def progress(stage: str, done: int, total: int) -> None:
                cur = self.current
                if cur is not None:
                    cur.update(stage=stage, done=done, total=total)

            try:
                result = await _run_on_daemon_thread(finish, prepared, progress, self._should_stop)
                self.completed += 1
                print(f"[Indexer] Indexed {lib.name}/{src['rel_path']} in {result['seconds']}s "
                      f"({result['chunks']} chunks, {result['visuals']} images, {result['faces']} faces"
                      f"{', transcript queued' if result['transcribe'] else ''})")
            except IndexingCancelled:
                await asyncio.to_thread(requeue, lib, src)
            except Exception as e:
                traceback.print_exc()
                await asyncio.to_thread(mark_failed, lib, src, f"{type(e).__name__}: {e}")
                self._fail(lib, src, e)
            finally:
                await asyncio.to_thread(prepared.extraction.cleanup)
            return nxt
        finally:
            self._claimed.pop(src["id"], None)
            self.current = None

    async def _enrichment_pass(self, name: str) -> None:
        """
        Run one enrichment pass (images | transcribe | caption | sounds) while it is the most useful
        work: its model loads once for the whole batch and gives its VRAM back after.
        """
        prepare_models, finish_models = _pass_models(name)
        stage = {"images": "updating image search", "transcribe": "transcribing", "caption": "describing pictures",
                 "sounds": "analysing sound"}[name]
        await asyncio.to_thread(prepare_models)
        try:
            while not self._stopping and not self.paused:
                job = await asyncio.to_thread(claim_pass, self.manager, name, list(self._claimed))
                if job is None:
                    break
                lib, src = job
                self._claimed[src["id"]] = (lib, src, name)
                self.current = {"libraryId": lib.id, "library": lib.name, "sourceId": src["id"],
                                "file": src["rel_path"], "kind": src["kind"], "size": src["size"],
                                "stage": stage, "done": 0, "total": 0, "startedAt": time.time()}
                try:
                    result = await _run_on_daemon_thread(PASS_RUNNERS[name], lib, src, self._should_stop)
                    self.enriched[name] = self.enriched.get(name, 0) + 1
                    detail = ", ".join(f"{k} {v}" for k, v in result.items() if k != "seconds" and v)
                    print(f"[Indexer] {_PASS_LABELS[name]}: {lib.name}/{src['rel_path']} in {result['seconds']}s ({detail})")
                except IndexingCancelled:
                    await asyncio.to_thread(requeue_pass, lib, src, name)
                except Exception as e:
                    traceback.print_exc()
                    await asyncio.to_thread(mark_pass_failed, lib, src, name, f"{type(e).__name__}: {e}")
                    self._fail(lib, src, e)
                finally:
                    self._claimed.pop(src["id"], None)
                    self.current = None
                if await asyncio.to_thread(next_action, self.manager, list(self._claimed)) != name:
                    break  # more urgent work (an upload, or another pass's turn)
        finally:
            self._last_enrichment = time.time()
            await asyncio.to_thread(finish_models)

    def _fail(self, lib: Library, src: Dict[str, Any], e: BaseException) -> None:
        self.failed += 1
        self.last_error = f"{src['rel_path']}: {e}"
        print(f"[Indexer] Failed {lib.name}/{src['rel_path']}: {type(e).__name__}: {e}")

    def _wait_idle_round(self) -> None:
        with self._idle_lock:
            pass

    def _on_idle(self) -> None:
        with self._idle_lock:
            if not self._stopping:
                self._idle_round()

    def _idle_round(self) -> None:
        """Queue drained: regroup people if faces changed, hand the GPU back to the search
        models, give cached VRAM back, and free indexing-only models' RAM after a while."""
        try:
            from app.people.cluster import maybe_recluster
            result = maybe_recluster(self.manager)
            if result:
                print(f"[Indexer] People regrouped: {result['people']} people from {result['faces']} faces "
                      f"in {result['seconds']}s")
        except Exception as e:
            print(f"[Indexer] People grouping notice: {e}")
        try:
            from app.search import model_pipeline as mp
            mp.settle_for_search()
            mp.release_cached_vram()
            if self._last_enrichment and time.time() - self._last_enrichment > WHISPER_IDLE_RELEASE_S:
                mp.release_indexing_models()
                self._last_enrichment = 0.0
        except Exception:
            pass

    async def _checkpoint_loop(self) -> None:
        while not self._stopping:
            try:
                await asyncio.sleep(CHECKPOINT_INTERVAL_S)
                await asyncio.to_thread(self.manager.checkpoint_all)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Indexer] Checkpoint notice: {e}")

    # ── status ───────────────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        totals: Dict[str, int] = {}
        pending = {name: 0 for name in PASS_COLUMNS}
        for lib in self.manager.online():
            if lib.db is None:
                continue
            for r in lib.db.all("SELECT status, COUNT(*) AS n FROM sources GROUP BY status"):
                totals[r["status"]] = totals.get(r["status"], 0) + int(r["n"])
            for name, column in PASS_COLUMNS.items():
                pending[name] += int(lib.db.scalar(
                    f"SELECT COUNT(*) FROM sources WHERE status = 'indexed' AND {column} IN ('pending', 'running')", (), 0))
        current = dict(self.current) if self.current else None
        if current:
            current["elapsed"] = round(time.time() - current.pop("startedAt"), 1)
        return {
            "running": self.running,
            "paused": self.paused,
            "current": current,
            "queued": totals.get("queued", 0),
            "processing": totals.get("processing", 0),
            "indexed": totals.get("indexed", 0),
            "failed": totals.get("failed", 0),
            "transcriptsPending": pending["transcribe"],
            "captionsPending": pending["caption"],
            "soundsPending": pending["sounds"],
            "imageVectorsPending": pending["images"],
            "enrichmentPending": sum(pending.values()),
            "completedThisSession": self.completed,
            "transcribedThisSession": self.enriched.get("transcribe", 0),
            "enrichedThisSession": dict(self.enriched),
            "failedThisSession": self.failed,
            "lastError": self.last_error,
        }


_pipeline: Optional[IngestionPipeline] = None


def get_pipeline() -> IngestionPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = IngestionPipeline()
    return _pipeline


def reset_pipeline() -> None:
    global _pipeline
    _pipeline = None
