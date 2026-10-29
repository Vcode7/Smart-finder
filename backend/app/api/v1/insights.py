"""
app/api/v1/insights.py
~~~~~~~~~~~~~~~~~~~~~~
Endpoints behind the search page's Dashboard and Summary tabs and the topic chips on results.

All of them work on a search session (`searchId`, returned by /search/smart and /search/similar),
so nothing searches again: the session holds a light row for every ranked file. They are called
by the page after the results are on screen and never delay them.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.deps import require_auth
from app.core.config import settings
from app.library.manager import get_library_manager
from app.processing.queue import spawn_background
from app.search import insights
from app.search.constants import COMPOSITE_MIN_SCORE
from app.search.session import (
    SearchSession, cut_rows, find_or_create_job, get_job, get_session, job_key,
)
from app.search.summary import run_summary_job

router = APIRouter(prefix="/search", tags=["search-insights"])

DASHBOARD_THRESHOLD = 0.30
SUMMARY_THRESHOLD = 0.05
DASHBOARD_TOPIC_FILES = 300     # files whose topics the dashboard derives on a first visit
TOPIC_IDS_MAX = 200
ATTRIBUTE_BATCH = 500           # ids per SQL IN (...) when reading file attributes


class FileRef(BaseModel):
    libraryId: Optional[str] = None
    sourceId: str


class TopicsRequest(BaseModel):
    searchId: str
    ids: List[FileRef] = Field(default_factory=list)


class DashboardRequest(BaseModel):
    searchId: str
    relativeThreshold: float = DASHBOARD_THRESHOLD


class SummaryRequest(BaseModel):
    searchId: str
    query: Optional[str] = None
    force: bool = False          # retry: start a new job even if a finished one exists


def _session(search_id: str, user: Dict[str, Any]) -> SearchSession:
    session = get_session(search_id, user["id"])
    if session is None:
        raise HTTPException(status_code=404, detail="This search is no longer available. Search again.")
    return session


def _fraction(value: float, default: float) -> float:
    """Thresholds arrive as 0.3 or 30."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v / 100.0 if v > 1.0 else v))


def _topics_for(refs: List[Dict[str, Optional[str]]]) -> Dict[str, Dict[str, Any]]:
    """{sourceId: {topics, events, origin}} for the given files (blocking)."""
    manager = get_library_manager()
    out: Dict[str, Dict[str, Any]] = {}
    for ref in refs:
        lib = manager.get(ref.get("libraryId") or "")
        if lib is None or lib.db is None:
            continue
        try:
            got = insights.get_insights(lib, ref["sourceId"])
        except Exception as e:      # one unreadable file must not hide the others' topics
            print(f"[Insights] topics failed for {ref['sourceId']}: {e}")
            continue
        out[ref["sourceId"]] = {"topics": got["topics"], "events": got["events"], "origin": got["origin"]}
    return out


@router.post("/topics")
async def search_topics(req: TopicsRequest, user: Dict[str, Any] = Depends(require_auth)):
    session = _session(req.searchId, user)
    known = {(r.get("libraryId"), r["sourceId"]) for r in session.rows}
    # Only files this search found: the session is what authorises reading them
    refs = [{"libraryId": r.libraryId, "sourceId": r.sourceId} for r in req.ids[:TOPIC_IDS_MAX]
            if (r.libraryId, r.sourceId) in known]
    return {"topics": await run_in_threadpool(_topics_for, refs)}


def _attributes(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    {sourceId: what the index knows about the file itself}: pages, duration, size in pixels,
    camera, whether it has a location or a transcript, and the people recognised in it. These
    feed the per-file-type charts; a file the index cannot read simply has none of them.
    """
    from json import loads
    from app.database.session import db_all
    manager = get_library_manager()
    by_lib: Dict[str, List[str]] = {}
    for r in rows:
        by_lib.setdefault(r.get("libraryId") or "", []).append(r["sourceId"])

    out: Dict[str, Dict[str, Any]] = {}
    person_names: Dict[Any, str] = {}
    for lib_id, ids in by_lib.items():
        lib = manager.get(lib_id)
        if lib is None or lib.db is None:
            continue
        for i in range(0, len(ids), ATTRIBUTE_BATCH):
            batch = ids[i:i + ATTRIBUTE_BATCH]
            marks = ",".join("?" * len(batch))
            try:
                for s in lib.db.all(
                        "SELECT id, page_count, duration, width, height, gps_lat, transcript, meta_json "
                        f"FROM sources WHERE id IN ({marks})", tuple(batch)):
                    try:
                        camera = (loads(s.get("meta_json") or "{}") or {}).get("camera")
                    except Exception:
                        camera = None
                    out[s["id"]] = {
                        "pages": s.get("page_count"), "duration": s.get("duration"),
                        "width": s.get("width"), "height": s.get("height"),
                        "hasLocation": s.get("gps_lat") is not None, "camera": camera,
                        "transcript": s.get("transcript"), "people": [],
                    }
                faces = lib.db.all(
                    f"SELECT DISTINCT source_id, person_id FROM faces WHERE person_id IS NOT NULL AND source_id IN ({marks})",
                    tuple(batch))
                wanted = {f["person_id"] for f in faces} - set(person_names)
                if wanted:
                    ids_list = list(wanted)
                    for p in db_all("SELECT id, name FROM persons WHERE hidden = 0 AND name IS NOT NULL AND name != '' "
                                    f"AND id IN ({','.join('?' * len(ids_list))})", tuple(ids_list)):
                        person_names[p["id"]] = p["name"]
                for f in faces:
                    name = person_names.get(f["person_id"])
                    if name and f["source_id"] in out:
                        out[f["source_id"]]["people"].append(name)
            except Exception as e:      # a library that cannot be read only loses its extra charts
                print(f"[Insights] attributes failed for library {lib_id}: {e}")
    return out


def _dashboard(session: SearchSession, relative: float) -> Dict[str, Any]:
    kept = cut_rows(session.rows, relative, COMPOSITE_MIN_SCORE)
    top = max((r.get("relevanceScore") or 0.0 for r in session.rows), default=0.0)
    in_library = [r for r in kept if r.get("libraryId")]      # catalog records have no index to read
    derived = _topics_for([{"libraryId": r.get("libraryId"), "sourceId": r["sourceId"]}
                           for r in in_library[:DASHBOARD_TOPIC_FILES]])
    attrs = _attributes(in_library)
    keys = ("id", "sourceId", "libraryId", "libraryName", "category", "title", "fileType", "fileSize", "relPath",
            "folder", "relevanceScore", "modifiedAt", "takenAt", "indexedAt", "year", "recordUrl")
    files = []
    for r in kept:
        row = {k: r.get(k) for k in keys}
        row["source"] = r.get("origin") or "local"      # local | koha | dspace
        t = derived.get(r["sourceId"])
        row["topics"] = t["topics"] if t else (r.get("subjects") or [])[:6]
        row["events"] = t["events"] if t else []
        row.update(attrs.get(r["sourceId"]) or {})
        files.append(row)
    return {
        "query": session.query,
        "totals": {
            "candidates": len(session.rows), "kept": len(kept),
            "topScore": round(top, 4), "relativeThreshold": round(relative, 4),
            "minScore": round(max(COMPOSITE_MIN_SCORE, top - relative), 4) if session.rows else 0.0,
            "totalBytes": sum(int(r.get("fileSize") or 0) for r in kept),
            "topicsFor": min(len(kept), DASHBOARD_TOPIC_FILES),
        },
        "files": files,
    }


@router.post("/dashboard")
async def search_dashboard(req: DashboardRequest, user: Dict[str, Any] = Depends(require_auth)):
    session = _session(req.searchId, user)
    return await run_in_threadpool(_dashboard, session, _fraction(req.relativeThreshold, DASHBOARD_THRESHOLD))


@router.post("/summary")
async def start_summary(req: SummaryRequest, user: Dict[str, Any] = Depends(require_auth)):
    """Starts (or joins) the summary job for the search's top files and returns at once."""
    session = _session(req.searchId, user)
    rows = cut_rows(session.rows, SUMMARY_THRESHOLD, COMPOSITE_MIN_SCORE)[:max(1, settings.SUMMARY_MAX_DOCS)]
    job, created = find_or_create_job(session, job_key(session.id, rows), req.force)
    if created:
        query = (req.query or session.query or "").strip() or "the files found"
        if rows:
            spawn_background(run_summary_job(job, rows, query))
        else:
            job.status = "done"
    return job.view()


@router.get("/summary/{job_id}")
async def summary_status(job_id: str, user: Dict[str, Any] = Depends(require_auth)):
    job = get_job(job_id, user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Summary job not found")
    return job.view()


@router.delete("/summary/{job_id}")
async def cancel_summary(job_id: str, user: Dict[str, Any] = Depends(require_auth)):
    job = get_job(job_id, user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Summary job not found")
    if job.status in ("queued", "running"):
        job.cancelled = True
    return {"jobId": job.id, "cancelled": job.cancelled}
