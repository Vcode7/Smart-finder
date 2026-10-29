"""
backend/app/api/v1/catalogs.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
External library sources (Koha, DSpace): which ones the search page can offer, their admin
settings and connection test, and the lazy file list of a DSpace item.

The searching itself happens in /api/search/smart (see app/search/catalogs/registry.py).
"""
import asyncio
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_admin, require_auth
from app.search.catalogs import registry
from app.search.catalogs.dspace import DSpaceConnector, valid_uuid

router = APIRouter(prefix="/catalogs", tags=["catalogs"])

FILES_TTL = 300
_files_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


class CatalogSettings(BaseModel):
    enabled: Optional[bool] = None
    baseUrl: Optional[str] = None
    apiUrl: Optional[str] = None
    uiUrl: Optional[str] = None
    authType: Optional[str] = None
    username: Optional[str] = None
    secret: Optional[str] = None
    timeout: Optional[int] = None
    maxResults: Optional[int] = None


def _source(source: str) -> str:
    if source not in registry.SOURCES:
        raise HTTPException(status_code=404, detail=f"Unknown source '{source}'")
    return source


@router.get("/sources")
async def list_sources(user: Dict[str, Any] = Depends(require_auth)):
    """The library sources a search can use. Internet search is separate and not listed here."""
    available = set(await asyncio.to_thread(registry.available_sources))
    return {"sources": [
        {"id": s, "label": registry.LABELS[s], "available": s == "local" or s in available}
        for s in registry.ALL_SOURCES
    ]}


@router.get("/settings")
async def get_settings(user: Dict[str, Any] = Depends(require_admin)):
    return {"sources": [await asyncio.to_thread(registry.public_config, s) for s in registry.SOURCES]}


@router.post("/settings/{source}")
async def update_settings(source: str, req: CatalogSettings, user: Dict[str, Any] = Depends(require_admin)):
    _source(source)
    try:
        await asyncio.to_thread(registry.save_config, source, req.model_dump(exclude_none=True))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    _files_cache.clear()
    return {"success": True, **(await asyncio.to_thread(registry.public_config, source))}


@router.post("/{source}/test")
async def test_source(source: str, req: Optional[CatalogSettings] = None,
                      user: Dict[str, Any] = Depends(require_admin)):
    """Try the connection with the stored settings, or with the form's unsaved ones."""
    _source(source)
    try:
        cfg = await asyncio.to_thread(registry.merge_config, source, req.model_dump(exclude_none=True) if req else {})
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not cfg.get("baseUrl"):
        raise HTTPException(status_code=400, detail="Give the URL first")
    started = time.monotonic()
    try:
        info = await asyncio.wait_for(registry.make_connector(source, cfg).test(), timeout=float(cfg["timeout"]) + 5)
        return {"success": True, "latency_ms": int((time.monotonic() - started) * 1000), **info}
    except Exception as e:
        _state, message = registry.describe_error(source, e, cfg)
        return {"success": False, "latency_ms": int((time.monotonic() - started) * 1000), "error": message}


@router.get("/dspace/items/{uuid}/files")
async def dspace_item_files(uuid: str, user: Dict[str, Any] = Depends(require_auth)):
    """
    The files of a DSpace item with whether anonymous users may open them. Links point at
    DSpace, which decides who may download; SmartFinder never serves the files itself.
    """
    if not valid_uuid(uuid):
        raise HTTPException(status_code=400, detail="Not a DSpace item id")
    cfg = await asyncio.to_thread(registry.get_config, "dspace")
    if not registry.is_available(cfg):
        raise HTTPException(status_code=404, detail="DSpace is not set up")
    hit = _files_cache.get(uuid)
    if hit and time.monotonic() - hit[0] < FILES_TTL:
        return hit[1]
    try:
        files, message = await asyncio.wait_for(DSpaceConnector(cfg).list_files(uuid),
                                                timeout=float(cfg["timeout"]) + 2)
    except Exception as e:
        _state, why = registry.describe_error("dspace", e, cfg)
        return {"files": [], "message": f"The files could not be listed: {why}."}
    payload = {"files": [f.__dict__ for f in files], "message": message}
    if len(_files_cache) > 500:
        _files_cache.clear()
    _files_cache[uuid] = (time.monotonic(), payload)
    return payload
