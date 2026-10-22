"""
Resumable, unlimited uploads (see app/library/uploads.py for the protocol).

Next.js forwards each request body in full, so clients send files in chunks of
`chunkSize` bytes; any number of chunks, any file size.
"""
import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

from app.api.deps import require_admin
from app.ingest.pipeline import get_pipeline
from app.library.manager import get_library_manager
from app.library.uploads import (
    UploadError, abort_upload, complete_upload, session_status, start_upload, write_chunk,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])


class StartUploadRequest(BaseModel):
    fileName: str = Field(min_length=1)
    size: int = Field(ge=0)
    lastModified: Optional[float] = None    # File.lastModified (ms since epoch)
    relativePath: Optional[str] = None      # webkitRelativePath, for folder uploads
    libraryId: Optional[str] = None         # default: the Uploads library
    subdir: Optional[str] = None


def _error(e: UploadError) -> JSONResponse:
    body: Dict[str, Any] = {"detail": e.message}
    if e.received is not None:
        body["received"] = e.received
    return JSONResponse(status_code=e.status, content=body)


@router.post("")
async def start(req: StartUploadRequest, user: Dict[str, Any] = Depends(require_admin)):
    try:
        return await asyncio.to_thread(
            start_upload, get_library_manager(), user, req.fileName, req.size, req.lastModified,
            req.relativePath, req.libraryId, req.subdir,
        )
    except UploadError as e:
        return _error(e)


@router.get("/{upload_id}")
async def status(upload_id: str, user: Dict[str, Any] = Depends(require_admin)):
    try:
        return await asyncio.to_thread(session_status, get_library_manager(), upload_id, user)
    except UploadError as e:
        return _error(e)


@router.put("/{upload_id}")
async def put_chunk(upload_id: str, request: Request, offset: int = Query(..., ge=0),
                    user: Dict[str, Any] = Depends(require_admin)):
    try:
        received = await write_chunk(get_library_manager(), upload_id, offset, request.stream(), user)
        return {"received": received}
    except UploadError as e:
        return _error(e)
    except ClientDisconnect:
        return JSONResponse(status_code=499, content={"detail": "Client disconnected"})


@router.post("/{upload_id}/complete")
async def complete(upload_id: str, user: Dict[str, Any] = Depends(require_admin)):
    try:
        result = await asyncio.to_thread(complete_upload, get_library_manager(), upload_id, user)
    except UploadError as e:
        return _error(e)
    if result.get("status") == "queued":
        get_pipeline().wake()
    return result


@router.delete("/{upload_id}")
async def abort(upload_id: str, user: Dict[str, Any] = Depends(require_admin)):
    try:
        await asyncio.to_thread(abort_upload, get_library_manager(), upload_id, user)
        return {"ok": True}
    except UploadError as e:
        return _error(e)
