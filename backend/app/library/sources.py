"""
app/library/sources.py
~~~~~~~~~~~~~~~~~~~~~~
Operations on a library's sources: registering files, queueing, purging derived
data, exclusions. Nothing here touches the user's own files — only index rows,
vectors and the library's cache folder.
"""
from __future__ import annotations

import fnmatch
import json
import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional

from app.library.manager import Library, get_library_manager
from app.search.constants import classify_extension

# Queue priorities: higher runs first; within a priority, smaller files first.
PRIORITY_UPLOAD = 100
PRIORITY_CHANGED = 50
PRIORITY_SCAN = 0

DERIVED_TABLES = ("chunks", "sections", "transcript_segments", "visual_items", "faces", "audio_segments", "source_logs")


def file_kind(name: str) -> str:
    return classify_extension(PurePosixPath(name).suffix.lstrip("."))


def add_or_update_source(
    lib: Library,
    rel_path: str,
    size: int,
    mtime: float,
    origin: str = "folder",
    priority: int = PRIORITY_SCAN,
    uploaded_by: Optional[str] = None,
    fingerprint: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Register a file (new → queued; changed size/mtime → re-queued; unchanged → kept).
    Returns the source id, or None when the type is unsupported or the path is excluded.
    """
    assert lib.db is not None
    name = PurePosixPath(rel_path.replace("\\", "/")).name
    kind = file_kind(name)
    if kind == "unsupported" or is_excluded(lib, rel_path):
        return None
    ext = PurePosixPath(name).suffix.lstrip(".").lower()
    existing = lib.db.one("SELECT id, size, mtime, status FROM sources WHERE rel_path = ?", (rel_path,))
    if existing:
        if int(existing["size"]) == int(size) and abs(float(existing["mtime"]) - float(mtime)) < 1.0 \
                and existing["status"] not in ("missing",):
            return existing["id"]
        lib.db.execute(
            """UPDATE sources SET size = ?, mtime = ?, status = 'queued', priority = MAX(priority, ?),
               attempts = 0, error = NULL, fingerprint = COALESCE(?, NULL) WHERE id = ?""",
            (size, mtime, priority, fingerprint, existing["id"]),
        )
        return existing["id"]

    source_id = str(uuid.uuid4())
    lib.db.execute(
        """INSERT INTO sources (id, rel_path, name, ext, kind, size, mtime, fingerprint, origin,
                                status, priority, uploaded_by, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
        (source_id, rel_path, name, ext, kind, size, mtime, fingerprint, origin, priority,
         uploaded_by, json.dumps(meta or {})),
    )
    get_library_manager().register_sources(lib, [source_id])
    return source_id


def queue_source(lib: Library, source_id: str, priority: int = PRIORITY_CHANGED) -> bool:
    assert lib.db is not None
    return lib.db.execute(
        "UPDATE sources SET status = 'queued', priority = MAX(priority, ?), attempts = 0, error = NULL WHERE id = ?",
        (priority, source_id),
    ) > 0


def _remove_cache(lib: Library, source_id: str) -> None:
    cache = lib.source_cache_dir(source_id)
    shutil.rmtree(cache, ignore_errors=True)
    try:
        cache.parent.rmdir()   # the two-letter shard folder, once empty
    except OSError:
        pass


def purge_derived(lib: Library, source_id: str) -> None:
    """Remove every derived row, vector and cache file of a source; keep the source row."""
    assert lib.db is not None and lib.vectors is not None
    with lib.db.write() as c:
        by_space = lib.vectors.collect_source(c, source_id)
        for table in DERIVED_TABLES:
            c.execute(f"DELETE FROM {table} WHERE source_id = ?", (source_id,))
    lib.vectors.unindex(by_space)
    _remove_cache(lib, source_id)


def remove_source(lib: Library, source_id: str) -> None:
    """Forget a source entirely (index rows, vectors, cache). The file itself is untouched."""
    assert lib.db is not None and lib.vectors is not None
    with lib.db.write() as c:
        by_space = lib.vectors.collect_source(c, source_id)
        c.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    lib.vectors.unindex(by_space)
    _remove_cache(lib, source_id)
    get_library_manager().unregister_sources([source_id])


def remove_sources_under(lib: Library, rel_prefix: str) -> int:
    """Forget every source below a folder (used when a watched folder is deleted)."""
    assert lib.db is not None
    rows = lib.db.all(
        "SELECT id FROM sources WHERE rel_path = ? OR rel_path LIKE ? ESCAPE '\\'",
        (rel_prefix, _like_prefix(rel_prefix)),
    )
    for r in rows:
        remove_source(lib, r["id"])
    return len(rows)


def move_sources(lib: Library, old_rel: str, new_rel: str) -> int:
    """Rename/move a file or folder without re-indexing (paths only)."""
    assert lib.db is not None
    with lib.db.write() as c:
        n = c.execute(
            "UPDATE sources SET rel_path = ?, name = ? WHERE rel_path = ?",
            (new_rel, PurePosixPath(new_rel).name, old_rel),
        ).rowcount
        rows = c.execute(
            "SELECT id, rel_path FROM sources WHERE rel_path LIKE ? ESCAPE '\\'", (_like_prefix(old_rel),)
        ).fetchall()
        for r in rows:
            moved = new_rel + r["rel_path"][len(old_rel):]
            c.execute("UPDATE sources SET rel_path = ? WHERE id = ?", (moved, r["id"]))
        return n + len(rows)


def _like_prefix(rel_dir: str) -> str:
    escaped = rel_dir.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped.rstrip("/") + "/%"


# ── exclusions ───────────────────────────────────────────────────────────────
def exclusion_patterns(lib: Library) -> List[str]:
    assert lib.db is not None
    return [r["pattern"] for r in lib.db.all("SELECT pattern FROM exclusions")]


def is_excluded(lib: Library, rel_path: str, patterns: Optional[Iterable[str]] = None) -> bool:
    pats = list(patterns) if patterns is not None else exclusion_patterns(lib)
    for p in pats:
        if rel_path == p or rel_path.startswith(p.rstrip("/") + "/") or fnmatch.fnmatch(rel_path, p):
            return True
    return False


def exclude_path(lib: Library, rel_path: str) -> int:
    """'Remove from library': remember the exclusion and forget matching sources."""
    assert lib.db is not None
    lib.db.execute("INSERT OR IGNORE INTO exclusions (pattern) VALUES (?)", (rel_path,))
    rows = lib.db.all(
        "SELECT id FROM sources WHERE rel_path = ? OR rel_path LIKE ? ESCAPE '\\'",
        (rel_path, _like_prefix(rel_path)),
    )
    for r in rows:
        remove_source(lib, r["id"])
    return len(rows)


def remove_exclusion(lib: Library, pattern: str) -> None:
    assert lib.db is not None
    lib.db.execute("DELETE FROM exclusions WHERE pattern = ?", (pattern,))


# ── API payloads ─────────────────────────────────────────────────────────────
def source_payload(lib: Library, src: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a source row for the API (keeps the legacy knowledge_sources field names)."""
    try:
        meta = json.loads(src.get("meta_json") or "{}")
    except Exception:
        meta = {}
    status_map = {"queued": "uploaded", "indexed": "completed"}
    return {
        "id": src["id"],
        "libraryId": lib.id,
        "libraryName": lib.name,
        "relPath": src["rel_path"],
        "filename": src["name"],
        "original_name": src["name"],
        "file_type": src["ext"],
        "kind": src["kind"],
        "file_size": src["size"],
        "mtime": src["mtime"],
        "upload_date": src.get("added_at"),
        "indexed_at": src.get("indexed_at"),
        "origin": src.get("origin"),
        "status": src["status"],
        "processing_status": status_map.get(src["status"], src["status"]),
        "error_message": src.get("error"),
        "page_count": src.get("page_count"),
        "duration_seconds": src.get("duration"),
        "width": src.get("width"),
        "height": src.get("height"),
        "taken_at": src.get("taken_at"),
        "url": meta.get("url"),
        "metadata": {k: v for k, v in meta.items() if k != "processing_info"},
    }
