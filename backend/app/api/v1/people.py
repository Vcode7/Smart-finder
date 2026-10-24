"""
People found in your photos and videos (faces grouped across every library).
Naming, hiding, merging and correcting are admin-only.
"""
import asyncio
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import require_admin, require_auth
from app.core.config import settings
from app.core.access import visible_library_ids
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


def _cover_url(cover: Optional[str], allowed: Optional[Set[str]] = None) -> Optional[str]:
    if not cover or cover.count(":") < 2:
        return None
    lib_id, source_id, face_id = cover.split(":", 2)
    if allowed is not None and lib_id not in allowed:
        return None
    return f"{settings.base_path}/api/knowledge/{source_id}/faces/{face_id}"


def _person(row: Dict[str, Any], allowed: Optional[Set[str]] = None,
            counts: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "faceCount": row["face_count"] if counts is None else counts.get(row["id"], 0),
        "hidden": bool(row["hidden"]),
        "coverUrl": _cover_url(row["cover_face"], allowed),
        "updatedAt": row["updated_at"],
    }


def _visible_counts(allowed: Set[str]) -> Dict[str, int]:
    """Faces per person inside the libraries shared with a non-admin user."""
    counts: Dict[str, int] = {}
    for lib in get_library_manager().online():
        if lib.id not in allowed or lib.db is None:
            continue
        for r in lib.db.all("SELECT person_id, COUNT(*) AS n FROM faces WHERE person_id IS NOT NULL GROUP BY person_id"):
            counts[r["person_id"]] = counts.get(r["person_id"], 0) + int(r["n"])
    return counts


def _media(person_id: str, offset: int, limit: int, allowed: Optional[Set[str]] = None) -> Dict[str, Any]:
    manager = get_library_manager()
    found: List[tuple] = []
    for lib in manager.online():
        if lib.db is None or (allowed is not None and lib.id not in allowed):
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
            "thumbnail": f"{settings.base_path}/api/knowledge/{src['id']}/thumbnail",
            "faceCrop": f"{settings.base_path}/api/knowledge/{src['id']}/faces/{best['id']}" if best and best["crop_path"] else None,
            "faceId": best["id"] if best else None,
        })
    return {"total": len(found), "offset": offset, "limit": limit, "items": items}


@router.get("")
async def list_people(includeHidden: bool = Query(False), user: Dict[str, Any] = Depends(require_auth)):
    def query():
        allowed = visible_library_ids(user)
        where = "" if includeHidden else "WHERE hidden = 0"
        rows = db_all(f"SELECT * FROM persons {where} ORDER BY (name IS NULL), face_count DESC LIMIT 2000")
        if allowed is None:
            return {"people": [_person(r) for r in rows if r["face_count"] or r["name"]]}
        counts = _visible_counts(allowed)   # users only see people who appear in data shared with them
        people = [_person(r, allowed, counts) for r in rows if counts.get(r["id"])]
        return {"people": sorted(people, key=lambda p: (p["name"] is None, -p["faceCount"]))}
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
    allowed = visible_library_ids(user)
    if allowed is None:
        media = await asyncio.to_thread(_media, person_id, offset, limit)
        return {"person": _person(row), "media": media}
    counts = await asyncio.to_thread(_visible_counts, allowed)
    if not counts.get(person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    media = await asyncio.to_thread(_media, person_id, offset, limit, allowed)
    return {"person": _person(row, allowed, counts), "media": media}


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
