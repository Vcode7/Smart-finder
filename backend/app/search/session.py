"""
app/search/session.py
~~~~~~~~~~~~~~~~~~~~~
Short-lived state that lets the dashboard and summary tabs reuse a search instead of
running it again.

A search session holds the light row of every ranked file (EngineResult.overview). A
summary job is the background work that summarises the top files of a session. Both are
in memory: the backend runs a single worker, and losing them only means the tabs ask
for a new search.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SESSION_TTL = 30 * 60
SESSION_MAX = 50
JOB_MAX = 100


@dataclass
class SearchSession:
    id: str
    user_id: str
    query: str
    rows: List[Dict[str, Any]]
    created: float = field(default_factory=time.time)


@dataclass
class SummaryJob:
    id: str
    session_id: str
    user_id: str
    key: str                      # session + the files being summarised: identical requests share a job
    status: str = "queued"        # queued | running | done | error
    total: int = 0
    done: int = 0
    docs: List[Dict[str, Any]] = field(default_factory=list)
    overall: Optional[str] = None
    overall_source: Optional[str] = None     # llm | extractive
    usage: Dict[str, int] = field(default_factory=lambda: {
        "calls": 0, "promptTokens": 0, "completionTokens": 0, "cachedDocs": 0})
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    cancelled: bool = False
    created: float = field(default_factory=time.time)

    def view(self) -> Dict[str, Any]:
        return {
            "jobId": self.id, "status": self.status,
            "progress": {"done": self.done, "total": self.total},
            "docs": list(self.docs), "overall": self.overall, "overallSource": self.overall_source,
            "usage": dict(self.usage), "warnings": list(self.warnings), "error": self.error,
        }


_lock = threading.Lock()
_sessions: "OrderedDict[str, SearchSession]" = OrderedDict()
_jobs: "OrderedDict[str, SummaryJob]" = OrderedDict()


def create_session(user_id: str, query: str, rows: List[Dict[str, Any]]) -> str:
    sid = uuid.uuid4().hex
    with _lock:
        _purge()
        _sessions[sid] = SearchSession(sid, str(user_id), query, rows)
        while len(_sessions) > SESSION_MAX:
            _sessions.popitem(last=False)
    return sid


def get_session(session_id: str, user_id: str) -> Optional[SearchSession]:
    """The session, only for the user whose search made it."""
    with _lock:
        _purge()
        s = _sessions.get(session_id)
        if s is None or s.user_id != str(user_id):
            return None
        _sessions.move_to_end(session_id)
        return s


def _purge() -> None:
    now = time.time()
    for sid in [k for k, s in _sessions.items() if now - s.created > SESSION_TTL]:
        del _sessions[sid]
    for jid in [k for k, j in _jobs.items() if now - j.created > SESSION_TTL]:
        del _jobs[jid]


def cut_rows(rows: List[Dict[str, Any]], relative: float, floor: float = 0.0) -> List[Dict[str, Any]]:
    """Files within `relative` of the best score (same rule as the results view), best first."""
    ranked = sorted(rows, key=lambda r: r.get("relevanceScore") or 0.0, reverse=True)
    if not ranked:
        return []
    top = ranked[0].get("relevanceScore") or 0.0
    cut = max(floor, round(top - relative, 4))
    return [r for r in ranked if (r.get("relevanceScore") or 0.0) >= cut]


def job_key(session_id: str, rows: List[Dict[str, Any]]) -> str:
    return session_id + ":" + ",".join(f"{r.get('libraryId')}/{r.get('sourceId')}" for r in rows)


def find_or_create_job(session: SearchSession, key: str, force: bool = False) -> "tuple[SummaryJob, bool]":
    """(job, created). A running or finished job for the same files is reused, unless `force` (retry)."""
    with _lock:
        _purge()
        for j in _jobs.values():
            if j.key != key or j.user_id != session.user_id or j.cancelled or j.status in ("error", "cancelled"):
                continue
            if not force or j.status in ("queued", "running"):
                return j, False
        job = SummaryJob(uuid.uuid4().hex, session.id, session.user_id, key)
        _jobs[job.id] = job
        while len(_jobs) > JOB_MAX:
            _jobs.popitem(last=False)
        return job, True


def get_job(job_id: str, user_id: str) -> Optional[SummaryJob]:
    with _lock:
        j = _jobs.get(job_id)
        return j if j is not None and j.user_id == str(user_id) else None
