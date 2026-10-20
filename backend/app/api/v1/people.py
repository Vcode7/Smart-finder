"""
People found in your photos and videos (faces grouped across every library).
Naming, hiding, merging and correcting are admin-only.
"""
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import require_admin, require_auth
from app.database.session import db_all, db_get, db_run
from app.library.manager import LibraryError, get_library_manager
from app.people import cluster

router = APIRouter(prefix="/people", tags=["people"])


class UpdatePerson(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    hidden: Optional[bool] = None


class MergeRequest(BaseModel):
    targetId: str


class AssignRequest(BaseModel):
    libraryId: str
    faceId: int
    personId: Optional[str] = None      # None = "not this person"


def _cover_url(cover: Optional[str]) -> Optional[str]:
    if not cover or cover.count(":") < 2:
        return None
    _lib, source_id, face_id = cover.split(":", 2)
    return f"/api/knowledge/{source_id}/faces/{face_id}"


def _person(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "faceCount": row["face_count"],
        "hidden": bool(row["hidden"]),
        "coverUrl": _cover_url(row["cover_face"]),
        "updatedAt": row["updated_at"],
    }


def _media(person_id: str, offset: int, limit: int) -> Dict[str, Any]:
    manager = get_library_manager()
    found: List[tuple] = []
    for lib in manager.online():
        if lib.db is None:
            continue
        for r in lib.db.all(
            "SELECT source_id, COUNT(*) AS n, MAX(quality) AS q FROM faces WHERE person_id = ? GROUP BY source_id",
            (person_id,),
        ):
            found.append((lib, r))
    found.sort(key=lambda x: (x[1]["n"], x[1]["q"] or 0), reverse=True)
    items = []
    for lib, r in found[offset:offset + limit]:
        src = lib.db.one("SELECT * FROM sources WHERE id = ?", (r["source_id"],))
        if not src:
            continue
        best = lib.db.one(
            "SELECT id, ts, page, crop_path FROM faces WHERE source_id = ? AND person_id = ? "
            "ORDER BY crop_path IS NULL, quality DESC LIMIT 1", (src["id"], person_id))
        times = [t["ts"] for t in lib.db.all(
            "SELECT DISTINCT ts FROM faces WHERE source_id = ? AND person_id = ? AND ts IS NOT NULL ORDER BY ts LIMIT 12",
            (src["id"], person_id))]
        items.append({
            "sourceId": src["id"], "libraryId": lib.id, "libraryName": lib.name, "title": src["name"],
            "kind": src["kind"], "relPath": src["rel_path"], "faces": r["n"], "timestamps": times,
            "page": best["page"] if best else None,
            "thumbnail": f"/api/knowledge/{src['id']}/thumbnail",
            "faceCrop": f"/api/knowledge/{src['id']}/faces/{best['id']}" if best and best["crop_path"] else None,
            "faceId": best["id"] if best else None,
        })
    return {"total": len(found), "offset": offset, "limit": limit, "items": items}


@router.get("")
async def list_people(includeHidden: bool = Query(False), user: Dict[str, Any] = Depends(require_auth)):
    def query():
        where = "" if includeHidden else "WHERE hidden = 0"
        rows = db_all(f"SELECT * FROM persons {where} ORDER BY (name IS NULL), face_count DESC LIMIT 2000")
        return {"people": [_person(r) for r in rows if r["face_count"] or r["name"]]}
    return await asyncio.to_thread(query)


@router.post("/recluster")
async def regroup(user: Dict[str, Any] = Depends(require_admin)):
    return await asyncio.to_thread(cluster.recluster)


@router.post("/faces/assign")
async def assign_face(req: AssignRequest, user: Dict[str, Any] = Depends(require_admin)):
    try:
        await asyncio.to_thread(cluster.assign_face, get_library_manager(), req.libraryId, req.faceId, req.personId)
    except (LibraryError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = await asyncio.to_thread(cluster.recluster)
    return {"ok": True, **result}


@router.get("/{person_id}")
async def get_person(person_id: str, offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=500),
                     user: Dict[str, Any] = Depends(require_auth)):
    row = await asyncio.to_thread(db_get, "SELECT * FROM persons WHERE id = ?", (person_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    media = await asyncio.to_thread(_media, person_id, offset, limit)
    return {"person": _person(row), "media": media}


@router.patch("/{person_id}")
async def update_person(person_id: str, req: UpdatePerson, user: Dict[str, Any] = Depends(require_admin)):
    row = await asyncio.to_thread(db_get, "SELECT * FROM persons WHERE id = ?", (person_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    if req.name is not None:
        name = req.name.strip() or None
        await asyncio.to_thread(db_run, "UPDATE persons SET name = ?, updated_at = datetime('now') WHERE id = ?",
                                (name, person_id))
    if req.hidden is not None:
        await asyncio.to_thread(db_run, "UPDATE persons SET hidden = ?, updated_at = datetime('now') WHERE id = ?",
                                (1 if req.hidden else 0, person_id))
    row = await asyncio.to_thread(db_get, "SELECT * FROM persons WHERE id = ?", (person_id,))
    return _person(row)


@router.post("/{person_id}/merge")
async def merge_person(person_id: str, req: MergeRequest, user: Dict[str, Any] = Depends(require_admin)):
    try:
        moved = await asyncio.to_thread(cluster.merge, get_library_manager(), person_id, req.targetId)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = await asyncio.to_thread(cluster.recluster)
    return {"ok": True, "moved": moved, **result}
