"""
app/library/uploads.py
~~~~~~~~~~~~~~~~~~~~~~
Resumable uploads of any size, streamed straight into a library folder.

  start     — skipped when a file with the same name, size and modification time is
              already indexed anywhere; otherwise a session is opened
  chunks    — each chunk is written at its offset into `<name>.<id>.smartfind-part`
              next to the destination (never into RAM or the system temp folder);
              re-sending a chunk is harmless
  status    — bytes received so far, to resume after a dropped connection or restart
  complete  — size check, content fingerprint (identical content already indexed →
              the copy is dropped), original modification time restored, atomic rename
              to a free final name, queued with upload priority
  abort     — the partial file is removed

Sessions live in the library database, so uploads survive restarts. Sessions idle for
24 hours are removed with their partial files. There is no size or count limit; the
only check is that the destination drive has room for the file.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Tuple

from app.core.files import is_within, safe_join, sanitize_filename, sanitize_relative_path, unique_path
from app.library.fingerprint import file_fingerprint
from app.library.manager import UPLOADS_LIBRARY_ID, Library, LibraryError, LibraryManager
from app.library.paths import INDEX_DIRNAME
from app.library.sources import PRIORITY_UPLOAD, add_or_update_source, file_kind

CHUNK_SIZE = 8 * 1024 * 1024            # what clients are asked to send per request
WRITE_BUFFER = 1024 * 1024
STALE_AFTER_S = 24 * 3600
PART_SUFFIX = ".smartfind-part"


class UploadError(Exception):
    def __init__(self, status: int, message: str, received: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.received = received


_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


# ── lookups ──────────────────────────────────────────────────────────────────
def find_existing(manager: LibraryManager, name: str, size: int,
                  mtime: Optional[float]) -> Optional[Tuple[Library, Dict[str, Any]]]:
    """A file with this name and size (and modification time, when known) already indexed."""
    for lib in manager.online():
        assert lib.db is not None
        for row in lib.db.all(
            "SELECT * FROM sources WHERE size = ? AND name = ? AND status NOT IN ('missing', 'excluded')",
            (size, name),
        ):
            if mtime is None or abs(float(row["mtime"]) - mtime) < 2.0:
                return lib, row
    return None


def find_by_fingerprint(manager: LibraryManager, fingerprint: str,
                        size: int) -> Optional[Tuple[Library, Dict[str, Any]]]:
    for lib in manager.online():
        assert lib.db is not None
        row = lib.db.one(
            "SELECT * FROM sources WHERE fingerprint = ? AND size = ? AND status NOT IN ('missing', 'excluded')",
            (fingerprint, size),
        )
        if row:
            return lib, row
    return None


def find_session(manager: LibraryManager, upload_id: str) -> Tuple[Library, Dict[str, Any]]:
    for lib in manager.online():
        assert lib.db is not None
        row = lib.db.one("SELECT * FROM upload_sessions WHERE id = ?", (upload_id,))
        if row:
            return lib, row
    raise UploadError(404, "Upload not found (it was completed, cancelled or expired)")


def _check_owner(sess: Dict[str, Any], user: Dict[str, Any]) -> None:
    if sess.get("created_by") and sess["created_by"] != user.get("id") and user.get("role") != "admin":
        raise UploadError(403, "This upload belongs to another user")


def _exists_payload(lib: Library, row: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "exists", "sourceId": row["id"], "libraryId": lib.id, "libraryName": lib.name,
            "relPath": row["rel_path"], "processingStatus": row["status"]}


# ── session lifecycle ────────────────────────────────────────────────────────
def start_upload(
    manager: LibraryManager,
    user: Dict[str, Any],
    file_name: str,
    size: int,
    last_modified_ms: Optional[float] = None,
    relative_path: Optional[str] = None,
    library_id: Optional[str] = None,
    subdir: Optional[str] = None,
) -> Dict[str, Any]:
    if size < 0:
        raise UploadError(400, "Invalid file size")
    name = sanitize_filename(file_name)
    rel_dir = sanitize_relative_path(subdir) if subdir else Path()
    if relative_path:
        rp = sanitize_relative_path(relative_path)   # folder uploads keep their structure
        name = rp.name
        rel_dir = rel_dir / rp.parent
    if file_kind(name) == "unsupported":
        raise UploadError(415, f"'{name}' is not a supported file type")

    mtime = (float(last_modified_ms) / 1000.0) if last_modified_ms else None
    hit = find_existing(manager, name, size, mtime)
    if hit:
        return _exists_payload(*hit)

    try:
        lib = manager.require(library_id or UPLOADS_LIBRARY_ID)
    except LibraryError as e:
        raise UploadError(400, str(e))
    if lib.is_linked or lib.root is None:
        raise UploadError(400, "Uploads can only go into a folder library")
    if any(part == INDEX_DIRNAME or part.startswith(".") for part in rel_dir.parts):
        raise UploadError(400, "Invalid destination folder")
    try:
        dest_dir = safe_join(lib.root, rel_dir)
    except ValueError:
        raise UploadError(400, "Invalid destination folder")
    dest_dir.mkdir(parents=True, exist_ok=True)

    free = shutil.disk_usage(dest_dir).free
    if free < size:
        raise UploadError(507, f"Not enough space on the destination drive: the file needs "
                               f"{size / 2**30:.2f} GB, {free / 2**30:.2f} GB is free")

    upload_id = uuid.uuid4().hex
    target = unique_path(dest_dir, name)
    part = dest_dir / f"{target.name}.{upload_id[:8]}{PART_SUFFIX}"
    part.touch()
    assert lib.db is not None
    lib.db.execute(
        """INSERT INTO upload_sessions (id, rel_path, part_path, size, received, last_modified, created_by)
           VALUES (?, ?, ?, ?, 0, ?, ?)""",
        (upload_id, lib.rel_path(target), lib.rel_path(part), size, mtime, user.get("id")),
    )
    return {"status": "started", "uploadId": upload_id, "chunkSize": CHUNK_SIZE, "received": 0,
            "libraryId": lib.id, "relPath": lib.rel_path(target)}


def session_status(manager: LibraryManager, upload_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    lib, sess = find_session(manager, upload_id)
    _check_owner(sess, user)
    return {"uploadId": upload_id, "received": int(sess["received"]), "size": int(sess["size"]),
            "chunkSize": CHUNK_SIZE, "libraryId": lib.id, "relPath": sess["rel_path"]}


async def write_chunk(manager: LibraryManager, upload_id: str, offset: int,
                      body: AsyncIterator[bytes], user: Dict[str, Any]) -> int:
    """Stream one request body into the partial file at `offset`. Returns bytes received."""
    async with _locks[upload_id]:
        lib, sess = await asyncio.to_thread(find_session, manager, upload_id)
        _check_owner(sess, user)
        received, size = int(sess["received"]), int(sess["size"])
        if offset > received:
            raise UploadError(409, f"Chunk starts at {offset} but only {received} bytes were received", received)
        part = lib.abs_path(sess["part_path"])
        if not part.exists():
            raise UploadError(410, "The partial upload is gone; please start again")

        pos = offset
        buf = bytearray()
        f = await asyncio.to_thread(open, part, "r+b")
        try:
            await asyncio.to_thread(f.seek, offset)
            async for data in body:
                if pos + len(buf) + len(data) > size:
                    raise UploadError(400, "More data than the declared file size", max(received, pos))
                buf += data
                if len(buf) >= WRITE_BUFFER:
                    await asyncio.to_thread(f.write, bytes(buf))
                    pos += len(buf)
                    buf.clear()
            if buf:
                await asyncio.to_thread(f.write, bytes(buf))
                pos += len(buf)
                buf.clear()
            await asyncio.to_thread(lambda: (f.flush(), os.fsync(f.fileno())))
        finally:
            await asyncio.to_thread(f.close)
            # Progress counts even when the connection dropped mid-chunk
            if pos > received:
                received = pos
                assert lib.db is not None
                await asyncio.to_thread(
                    lib.db.execute,
                    "UPDATE upload_sessions SET received = MAX(received, ?), updated_at = datetime('now') WHERE id = ?",
                    (pos, upload_id),
                )
        return received


def complete_upload(manager: LibraryManager, upload_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    lib, sess = find_session(manager, upload_id)
    _check_owner(sess, user)
    assert lib.db is not None
    part = lib.abs_path(sess["part_path"])
    size = int(sess["size"])
    if not part.exists():
        raise UploadError(410, "The partial upload is gone; please start again")
    actual = part.stat().st_size
    if int(sess["received"]) < size or actual < size:
        raise UploadError(409, f"Upload incomplete: {min(actual, int(sess['received']))} of {size} bytes",
                          min(actual, int(sess["received"])))
    if actual > size:
        with open(part, "r+b") as f:
            f.truncate(size)

    fingerprint = file_fingerprint(part)
    dup = find_by_fingerprint(manager, fingerprint, size)
    if dup:
        part.unlink(missing_ok=True)
        lib.db.execute("DELETE FROM upload_sessions WHERE id = ?", (upload_id,))
        return _exists_payload(*dup)

    if sess.get("last_modified"):
        try:
            os.utime(part, (time.time(), float(sess["last_modified"])))  # keep the original date
        except OSError:
            pass
    target = lib.abs_path(sess["rel_path"])
    for _ in range(50):
        if target.exists():
            target = unique_path(target.parent, target.name)
        try:
            os.rename(part, target)   # atomic; never overwrites on Windows
            break
        except FileExistsError:
            continue
    else:
        raise UploadError(500, "Could not find a free file name for the upload")
    if not is_within(target, lib.root):
        raise UploadError(500, "Upload ended outside its library")

    st = target.stat()
    rel = lib.rel_path(target)
    source_id = add_or_update_source(
        lib, rel, st.st_size, st.st_mtime, origin="upload", priority=PRIORITY_UPLOAD,
        uploaded_by=user.get("id"), fingerprint=fingerprint,
    )
    lib.db.execute("DELETE FROM upload_sessions WHERE id = ?", (upload_id,))
    _locks.pop(upload_id, None)
    return {
        "status": "queued" if source_id else "saved",
        "sourceId": source_id,
        "libraryId": lib.id,
        "libraryName": lib.name,
        "relPath": rel,
        "fileName": target.name,
        **({} if source_id else {"note": "Saved, but this folder is excluded from indexing"}),
    }


def abort_upload(manager: LibraryManager, upload_id: str, user: Dict[str, Any]) -> None:
    lib, sess = find_session(manager, upload_id)
    _check_owner(sess, user)
    assert lib.db is not None
    lib.abs_path(sess["part_path"]).unlink(missing_ok=True)
    lib.db.execute("DELETE FROM upload_sessions WHERE id = ?", (upload_id,))
    _locks.pop(upload_id, None)


def cleanup_stale_uploads(manager: LibraryManager, max_age_s: int = STALE_AFTER_S) -> int:
    """Remove sessions (and their partial files) that saw no data for `max_age_s`."""
    removed = 0
    for lib in manager.online():
        assert lib.db is not None
        for row in lib.db.all(
            "SELECT id, part_path FROM upload_sessions WHERE updated_at < datetime('now', ?)",
            (f"-{int(max_age_s)} seconds",),
        ):
            try:
                lib.abs_path(row["part_path"]).unlink(missing_ok=True)
            except OSError:
                continue
            lib.db.execute("DELETE FROM upload_sessions WHERE id = ?", (row["id"],))
            removed += 1
    return removed
