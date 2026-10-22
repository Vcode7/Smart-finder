"""
Folder libraries: list, attach, detach, rescan, pause, exclusions, and adding
individual local files in place (no copies). Changing libraries is admin-only: a
library makes every file in its folder readable through the API.
"""
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import require_admin, require_auth
from app.core.access import can_access_library, filter_libraries, is_admin
from app.ingest.pipeline import get_pipeline
from app.library.manager import Library, LibraryError, get_library_manager
from app.library.paths import INDEX_DIRNAME
from app.library.service import get_library_service
from app.library.sources import (
    PRIORITY_UPLOAD, add_or_update_source, exclude_path, exclusion_patterns, file_kind,
    remove_exclusion, source_payload,
)

router = APIRouter(prefix="/libraries", tags=["libraries"])


class AttachRequest(BaseModel):
    path: str = Field(min_length=1)
    name: Optional[str] = None


class UpdateRequest(BaseModel):
    name: Optional[str] = None
    paused: Optional[bool] = None
    watch: Optional[bool] = None


class AddFilesRequest(BaseModel):
    paths: List[str] = Field(min_length=1)


class ExclusionRequest(BaseModel):
    pattern: str = Field(min_length=1)


def _summary(lib: Library) -> Dict[str, Any]:
    service = get_library_service()
    out = lib.summary()
    out["scan"] = service.scan_state(lib.id)
    out["watching"] = service.watchers.watching(lib.id)
    return out


def _get(lib_id: str) -> Library:
    lib = get_library_manager().get(lib_id)
    if lib is None:
        raise HTTPException(status_code=404, detail="Library not found")
    return lib


def _online(lib_id: str) -> Library:
    try:
        return get_library_manager().require(lib_id)
    except LibraryError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ── collection ───────────────────────────────────────────────────────────────
def _indexing_status(user: Dict[str, Any]) -> Dict[str, Any]:
    status = get_pipeline().status()
    if not is_admin(user):
        # These name files that may be in libraries that are not shared with the user
        status["current"] = None
        status["lastError"] = None
    return status


def _guard(user: Dict[str, Any], lib_id: str) -> None:
    """404 (not 403) for libraries that are not shared with a non-admin user."""
    if not can_access_library(user, lib_id):
        raise HTTPException(status_code=404, detail="Library not found")


@router.get("")
async def list_libraries(user: Dict[str, Any] = Depends(require_auth)):
    def build():
        admin = is_admin(user)
        libs = []
        for lib in filter_libraries(user, get_library_manager().all()):
            summary = _summary(lib)
            if not admin:
                for key in ("path", "indexPath", "error", "scan"):
                    summary.pop(key, None)   # server paths and scan internals are admin-only
            libs.append(summary)
        return {"libraries": libs, "indexing": _indexing_status(user)}
    return await asyncio.to_thread(build)


@router.get("/status")
async def indexing_status(user: Dict[str, Any] = Depends(require_auth)):
    return await asyncio.to_thread(_indexing_status, user)


@router.post("", status_code=201)
async def attach_library(req: AttachRequest, user: Dict[str, Any] = Depends(require_admin)):
    try:
        lib = await asyncio.to_thread(get_library_service().attach, req.path, req.name)
    except LibraryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await asyncio.to_thread(_summary, lib)


@router.post("/pause")
async def pause_indexing(user: Dict[str, Any] = Depends(require_admin)):
    get_pipeline().pause()
    return {"paused": True}


@router.post("/resume")
async def resume_indexing(user: Dict[str, Any] = Depends(require_admin)):
    get_pipeline().resume()
    return {"paused": False}


@router.post("/files")
async def add_files(req: AddFilesRequest, user: Dict[str, Any] = Depends(require_admin)):
    """
    Index individual local files where they are. A file inside a library folder joins
    that library; any other file joins the 'Linked files' library by absolute path.
    """
    def add() -> List[Dict[str, Any]]:
        manager = get_library_manager()
        results: List[Dict[str, Any]] = []
        for raw in req.paths:
            entry: Dict[str, Any] = {"path": raw}
            try:
                p = Path(raw).expanduser().resolve(strict=True)
            except OSError:
                results.append({**entry, "status": "error", "error": "File not found"})
                continue
            if p.is_dir():
                results.append({**entry, "status": "error", "error": "This is a folder — add it as a library instead"})
                continue
            if INDEX_DIRNAME in p.parts:
                results.append({**entry, "status": "error", "error": "Index files cannot be added"})
                continue
            if file_kind(p.name) == "unsupported":
                results.append({**entry, "status": "error", "error": "Unsupported file type"})
                continue
            try:
                lib = manager.library_for_path(p)
                st = p.stat()
                sid = add_or_update_source(lib, lib.rel_path(p), st.st_size, st.st_mtime,
                                           origin="linked" if lib.is_linked else "folder", priority=PRIORITY_UPLOAD)
            except (LibraryError, OSError, ValueError) as e:
                results.append({**entry, "status": "error", "error": str(e)})
                continue
            if sid is None:
                results.append({**entry, "status": "excluded", "libraryId": lib.id})
                continue
            status = lib.db.scalar("SELECT status FROM sources WHERE id = ?", (sid,)) if lib.db else None
            results.append({**entry, "status": "added", "sourceId": sid, "libraryId": lib.id,
                            "libraryName": lib.name, "processingStatus": status})
        return results

    results = await asyncio.to_thread(add)
    if any(r["status"] == "added" for r in results):
        get_pipeline().wake()
    return {"results": results}


# ── single library ───────────────────────────────────────────────────────────
@router.get("/{lib_id}")
async def get_library(lib_id: str, user: Dict[str, Any] = Depends(require_auth)):
    _guard(user, lib_id)
    summary = await asyncio.to_thread(_summary, _get(lib_id))
    if not is_admin(user):
        for key in ("path", "indexPath", "error", "scan"):
            summary.pop(key, None)
    return summary


@router.patch("/{lib_id}")
async def update_library(lib_id: str, req: UpdateRequest, user: Dict[str, Any] = Depends(require_admin)):
    _get(lib_id)
    try:
        if req.name is not None:
            await asyncio.to_thread(get_library_manager().rename, lib_id, req.name)
        lib = await asyncio.to_thread(get_library_service().update, lib_id, req.paused, req.watch)
    except LibraryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await asyncio.to_thread(_summary, lib)


@router.delete("/{lib_id}")
async def detach_library(lib_id: str, deleteIndex: bool = Query(False),
                         user: Dict[str, Any] = Depends(require_admin)):
    """Stop indexing a folder. Its files are never touched; deleteIndex removes only .smartfind."""
    _get(lib_id)
    try:
        await asyncio.to_thread(get_library_service().detach, lib_id, deleteIndex)
    except LibraryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.post("/{lib_id}/rescan")
async def rescan_library(lib_id: str, user: Dict[str, Any] = Depends(require_admin)):
    _online(lib_id)
    started = get_library_service().scan(lib_id)
    return {"started": started, "scan": get_library_service().scan_state(lib_id)}


@router.post("/{lib_id}/retry-failed")
async def retry_failed(lib_id: str, user: Dict[str, Any] = Depends(require_admin)):
    lib = _online(lib_id)

    def retry() -> int:
        assert lib.db is not None
        n = lib.db.execute("UPDATE sources SET status = 'queued', attempts = 0, error = NULL WHERE status = 'failed'")
        n += lib.db.execute(
            "UPDATE sources SET transcript = 'pending', error = NULL WHERE status = 'indexed' AND transcript = 'failed'"
        )
        n += lib.db.execute(
            "UPDATE sources SET image_vectors = 'pending', error = NULL WHERE status = 'indexed' AND image_vectors = 'failed'"
        )
        return n

    n = await asyncio.to_thread(retry)
    if n:
        get_pipeline().wake()
    return {"requeued": n}


@router.get("/{lib_id}/sources")
async def list_sources(
    lib_id: str,
    status: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Substring of the file name or path"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: Dict[str, Any] = Depends(require_auth),
):
    _guard(user, lib_id)
    lib = _online(lib_id)

    def query() -> Dict[str, Any]:
        assert lib.db is not None
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if q:
            if len(q) >= 3:  # trigram index
                where.append("rowid IN (SELECT rowid FROM sources_fts WHERE sources_fts MATCH ?)")
                params.append('"' + q.replace('"', '""') + '"')
            else:
                where.append("(name LIKE ? OR rel_path LIKE ?)")
                params.extend([f"%{q}%", f"%{q}%"])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = lib.db.scalar(f"SELECT COUNT(*) FROM sources {clause}", params, 0)
        rows = lib.db.all(
            f"SELECT * FROM sources {clause} ORDER BY added_at DESC, rel_path LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return {"total": total, "offset": offset, "limit": limit,
                "sources": [source_payload(lib, r) for r in rows]}

    return await asyncio.to_thread(query)


@router.get("/{lib_id}/exclusions")
async def list_exclusions(lib_id: str, user: Dict[str, Any] = Depends(require_admin)):
    lib = _online(lib_id)
    return {"exclusions": await asyncio.to_thread(exclusion_patterns, lib)}


@router.post("/{lib_id}/exclusions")
async def add_exclusion(lib_id: str, req: ExclusionRequest, user: Dict[str, Any] = Depends(require_admin)):
    """'Remove from library': forget matching files and keep them out. Files stay on disk."""
    lib = _online(lib_id)
    removed = await asyncio.to_thread(exclude_path, lib, req.pattern.strip().strip("/"))
    return {"removed": removed}


@router.delete("/{lib_id}/exclusions")
async def delete_exclusion(lib_id: str, pattern: str = Query(..., min_length=1),
                           user: Dict[str, Any] = Depends(require_admin)):
    lib = _online(lib_id)
    await asyncio.to_thread(remove_exclusion, lib, pattern)
    get_library_service().scan(lib_id)   # bring the files back in
    return {"ok": True}
