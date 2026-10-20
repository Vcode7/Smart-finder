"""
app/library/compat.py
~~~~~~~~~~~~~~~~~~~~~
Library sources through the existing /api/knowledge routes, in the response shapes the
frontend already uses (knowledge list rows, the detail modal, file/thumbnail/frame URLs).

Deleting: a file the app itself created (browser upload, internet import) is deleted;
any other file is only removed from the index and kept out of it (an exclusion) — the
user's own files are never deleted.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

from app.core.files import is_within, sanitize_filename, unique_path
from app.library.manager import Library, LibraryManager, get_library_manager
from app.library.sources import (
    PRIORITY_CHANGED, PRIORITY_UPLOAD, add_or_update_source, exclude_path, file_kind, queue_source, remove_source,
)

_STATUS = {"queued": "uploaded", "processing": "processing", "indexed": "completed"}
APP_CREATED_ORIGINS = ("upload", "internet")


def _meta(src: Dict[str, Any]) -> Dict[str, Any]:
    try:
        meta = json.loads(src.get("meta_json") or "{}")
    except Exception:
        meta = {}
    meta.pop("processing_info", None)
    return meta


def legacy_row(lib: Library, src: Dict[str, Any], usernames: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    meta = _meta(src)
    counts = meta.get("counts") or {}
    if src.get("origin") == "internet":
        meta.setdefault("source_type", "internet")
    return {
        "id": src["id"],
        "filename": src["name"],
        "original_name": src["name"],
        "file_type": src["ext"],
        "file_path": src["rel_path"],
        "file_size": src["size"],
        "upload_date": src.get("added_at"),
        "uploaded_by": src.get("uploaded_by"),
        "uploader_name": (usernames or {}).get(src.get("uploaded_by") or "", None),
        "processing_status": _STATUS.get(src["status"], src["status"]),
        "error_message": src.get("error"),
        "metadata_json": json.dumps(meta),
        "tags_json": "[]",
        "chunk_count": counts.get("chunks", 0),
        "transcript_count": counts.get("segments", 0),
        "face_count": counts.get("faces", 0),
        "frame_count": counts.get("visuals", 0) if src["kind"] == "video" else 0,
        "duration_seconds": src.get("duration"),
        "page_count": src.get("page_count"),
        "libraryId": lib.id,
        "libraryName": lib.name,
        "relPath": src["rel_path"],
        "kind": src["kind"],
        "transcriptStatus": src.get("transcript"),
    }


def list_rows(manager: LibraryManager, admin: bool, status: Optional[str], q: Optional[str],
              limit: int) -> Tuple[List[Dict[str, Any]], int]:
    """Newest-first rows from every online library (at most `limit` per library) and the total."""
    from app.database.session import db_all
    rows: List[Tuple[Library, Dict[str, Any]]] = []
    total = 0
    reverse = {"uploaded": "queued", "completed": "indexed"}
    for lib in manager.online():
        assert lib.db is not None
        where, params = ["status NOT IN ('missing', 'excluded')"], []
        if not admin:
            where.append("status = 'indexed'")
        elif status:
            where.append("status = ?")
            params.append(reverse.get(status, status))
        if q and q.strip():
            where.append("name LIKE ?")
            params.append(f"%{q.strip()}%")
        clause = " AND ".join(where)
        total += int(lib.db.scalar(f"SELECT COUNT(*) FROM sources WHERE {clause}", params, 0))
        for r in lib.db.all(f"SELECT * FROM sources WHERE {clause} ORDER BY added_at DESC LIMIT ?", [*params, limit]):
            rows.append((lib, r))
    ids = sorted({r.get("uploaded_by") for _, r in rows if r.get("uploaded_by")})
    usernames: Dict[str, str] = {}
    if ids:
        for u in db_all(f"SELECT id, username FROM users WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)):
            usernames[u["id"]] = u["username"]
    return [legacy_row(lib, r, usernames) for lib, r in rows], total


def find(source_id: str) -> Optional[Tuple[Library, Dict[str, Any]]]:
    return get_library_manager().find_source(source_id)


def detail(lib: Library, src: Dict[str, Any]) -> Dict[str, Any]:
    assert lib.db is not None
    sid, kind = src["id"], src["kind"]
    row = legacy_row(lib, src)
    log = lib.db.one("SELECT info_json FROM source_logs WHERE source_id = ?", (sid,))
    try:
        processing_info = json.loads(log["info_json"]) if log else None
    except Exception:
        processing_info = None
    sections = [
        {"id": s["id"], "section_title": s["title"], "page_num": s["page"], "order_idx": s["ord"],
         "char_count": s["char_count"]}
        for s in lib.db.all("SELECT * FROM sections WHERE source_id = ? ORDER BY ord", (sid,))
    ]
    chunks = [
        {"id": c["id"], "chunk_order": c["ord"], "page_num": c["page"], "char_count": len(c["text"]),
         "chunk_text": c["text"], "kind": c["kind"]}
        for c in lib.db.all(
            "SELECT * FROM chunks WHERE source_id = ? AND kind != 'title' ORDER BY ord LIMIT 20", (sid,))
    ]
    document = None
    if kind == "document":
        document = {"id": sid, "title": src["name"], "page_count": src.get("page_count"),
                    "section_count": len(sections), "full_text": None}
    video = None
    transcripts: List[Dict[str, Any]] = []
    frames: List[Dict[str, Any]] = []
    if kind in ("video", "audio"):
        video = {"id": sid, "duration": src.get("duration"), "format": src["ext"],
                 "thumbnail_path": None, "transcriptStatus": src.get("transcript")}
        transcripts = [
            {"id": t["id"], "start_time": t["ts_start"], "end_time": t["ts_end"], "text": t["text"]}
            for t in lib.db.all("SELECT * FROM transcript_segments WHERE source_id = ? ORDER BY ts_start", (sid,))
        ]
    if kind in ("video", "document"):
        frames = [
            {"id": v["id"], "timestamp": v["ts"], "frame_number": i + 1, "scene_id": 1, "frame_path": None,
             "page": v["page"], "kind": v["kind"], "visual_description": v["caption"] or v["ocr_text"]}
            for i, v in enumerate(lib.db.all(
                "SELECT * FROM visual_items WHERE source_id = ? ORDER BY COALESCE(ts, 0), COALESCE(page, 0), id",
                (sid,)))
        ]
    image = None
    if kind == "image":
        v = lib.db.one("SELECT * FROM visual_items WHERE source_id = ? ORDER BY id LIMIT 1", (sid,))
        image = {"id": v["id"] if v else sid, "width": src.get("width"), "height": src.get("height"),
                 "ocr_text": v["ocr_text"] if v else None, "description": v["caption"] if v else None}
    faces = [
        {"id": f["id"], "timestamp": f["ts"], "page": f["page"], "quality": f["quality"],
         "cropUrl": f"/api/knowledge/{sid}/faces/{f['id']}" if f["crop_path"] else None}
        for f in lib.db.all("SELECT * FROM faces WHERE source_id = ? ORDER BY quality DESC LIMIT 60", (sid,))
    ]
    return {
        "source": row,
        "processing_info": processing_info,
        "document": document,
        "sections": sections,
        "chunks": chunks,
        "video": video,
        "transcripts": transcripts,
        "frames": frames,
        "image": image,
        "faces": faces,
        "library": {"id": lib.id, "name": lib.name, "relPath": src["rel_path"]},
    }


# ── files served from a library ──────────────────────────────────────────────
def source_file(lib: Library, src: Dict[str, Any]) -> Optional[Path]:
    path = lib.abs_path(src["rel_path"])
    if not lib.is_linked and not is_within(path, lib.root):
        return None
    return path if path.is_file() else None


def internet_url(src: Dict[str, Any]) -> Optional[str]:
    if src.get("origin") != "internet":
        return None
    url = _meta(src).get("url")
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None


def cache_file(lib: Library, src: Dict[str, Any], rel: Optional[str]) -> Optional[Path]:
    if not rel:
        return None
    base = lib.source_cache_dir(src["id"])
    path = base / rel
    return path if is_within(path, base) and path.is_file() else None


def thumbnail(lib: Library, src: Dict[str, Any]) -> Optional[Path]:
    thumb = cache_file(lib, src, _meta(src).get("thumbnail") or "thumb.webp")
    if thumb is not None:
        return thumb
    if src["kind"] == "image":
        return source_file(lib, src)
    return None


def frame(lib: Library, src: Dict[str, Any], frame_id: str) -> Optional[Path]:
    assert lib.db is not None
    try:
        vid = int(frame_id)
    except ValueError:
        return None
    v = lib.db.one("SELECT cache_path FROM visual_items WHERE id = ? AND source_id = ?", (vid, src["id"]))
    return cache_file(lib, src, v["cache_path"]) if v else None


def face_crop(lib: Library, src: Dict[str, Any], face_id: str) -> Optional[Path]:
    assert lib.db is not None
    try:
        fid = int(face_id)
    except ValueError:
        return None
    f = lib.db.one("SELECT crop_path FROM faces WHERE id = ? AND source_id = ?", (fid, src["id"]))
    return cache_file(lib, src, f["crop_path"]) if f else None


# ── actions ──────────────────────────────────────────────────────────────────
def delete(lib: Library, src: Dict[str, Any]) -> Dict[str, Any]:
    if lib.is_linked:
        remove_source(lib, src["id"])
        return {"deleted": src["id"], "fileDeleted": False}
    if src.get("origin") in APP_CREATED_ORIGINS:
        path = lib.abs_path(src["rel_path"])
        if is_within(path, lib.root):
            path.unlink(missing_ok=True)
        remove_source(lib, src["id"])
        return {"deleted": src["id"], "fileDeleted": True}
    exclude_path(lib, src["rel_path"])
    return {"deleted": src["id"], "fileDeleted": False, "excluded": True,
            "note": "Removed from the library; the file itself was not touched"}


def reprocess(lib: Library, src: Dict[str, Any]) -> bool:
    return queue_source(lib, src["id"], PRIORITY_CHANGED)


def uploads_name_taken(name: str) -> bool:
    try:
        lib = get_library_manager().uploads()
    except Exception:
        return False
    assert lib.root is not None
    return (lib.root / name).exists()


def save_upload(stream: BinaryIO, filename: str, user_id: Optional[str], resolve_duplicates: bool) -> Dict[str, Any]:
    """Stream one multipart file into the Uploads library and queue it (no size limit)."""
    lib = get_library_manager().uploads()
    assert lib.root is not None
    name = sanitize_filename(filename or "uploaded_file")
    if file_kind(name) == "unsupported":
        return {"filename": name, "error": f"Unsupported file type '{Path(name).suffix or name}'"}
    target = lib.root / name
    if target.exists():
        if not resolve_duplicates:
            return {"filename": name, "error": f"A file named '{name}' already exists. Upload cancelled or requires confirmation."}
        target = unique_path(lib.root, name)
    part = target.with_name(f"{target.name}.{uuid.uuid4().hex[:8]}.smartfind-part")
    try:
        stream.seek(0)
        with open(part, "wb") as out:
            shutil.copyfileobj(stream, out, length=1024 * 1024)
        for _ in range(50):
            try:
                part.rename(target)
                break
            except FileExistsError:
                target = unique_path(lib.root, target.name)
    finally:
        part.unlink(missing_ok=True)
    st = target.stat()
    sid = add_or_update_source(lib, lib.rel_path(target), st.st_size, st.st_mtime, origin="upload",
                               priority=PRIORITY_UPLOAD, uploaded_by=user_id)
    info = {"id": sid, "filename": target.name, "original_name": target.name, "file_type": target.suffix.lstrip(".").lower(),
            "file_size": st.st_size, "processing_status": "uploaded", "libraryId": lib.id, "relPath": lib.rel_path(target)}
    return {**info, "source": dict(info)}


def _yaml_value(v: Any) -> str:
    s = str(v).replace("\n", " ").strip()
    return json.dumps(s, ensure_ascii=False)


def import_internet_item(item: Any, user_id: Optional[str]) -> Dict[str, Any]:
    """Save an internet result as a Markdown file in Uploads/Internet/ and queue it."""
    lib = get_library_manager().uploads()
    assert lib.root is not None
    folder = lib.root / "Internet"
    folder.mkdir(parents=True, exist_ok=True)
    title = (getattr(item, "title", None) or "Internet source").strip()
    stem = re.sub(r"\s+", " ", sanitize_filename(title, default="internet-source"))[:120].rstrip(". ")
    target = unique_path(folder, f"{stem}.md")
    front = {
        "title": title, "url": getattr(item, "url", None), "category": getattr(item, "category", None),
        "domain": getattr(item, "domain", None), "platform": getattr(item, "platform", None),
        "author": getattr(item, "author", None), "published": getattr(item, "publishedDate", None),
        "imported": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    body = getattr(item, "fullText", None) or getattr(item, "snippet", None) or title
    lines = ["---"] + [f"{k}: {_yaml_value(v)}" for k, v in front.items() if v] + ["---", "", f"# {title}", "", body.strip(), ""]
    target.write_text("\n".join(lines), encoding="utf-8")
    st = target.stat()
    meta = {"source_type": "internet", "url": front["url"], "original_url": front["url"], "category": front["category"],
            "domain": front["domain"], "platform": front["platform"], "author": front["author"],
            "publishedDate": front["published"], "thumbnail": None}
    remote_thumb = getattr(item, "thumbnail", None)
    if remote_thumb:
        meta["remoteThumbnail"] = remote_thumb
    sid = add_or_update_source(lib, lib.rel_path(target), st.st_size, st.st_mtime, origin="internet",
                               priority=PRIORITY_UPLOAD, uploaded_by=user_id, meta=meta)
    return {"id": sid, "title": title, "category": front["category"], "relPath": lib.rel_path(target)}
