import uuid
import datetime
from typing import Dict, Any, Iterable, Optional
from fastapi import APIRouter, HTTPException, Depends

from app.database.session import db_all, db_get, db_run
from app.api.deps import require_auth

router = APIRouter(prefix="/search-history", tags=["search-history"])

MAX_PER_USER = 100      # oldest searches beyond this are dropped
MAX_QUERY_CHARS = 500


def record_search(user_id: str, query: str, internet: bool, result_count: int,
                  sources: Optional[Iterable[str]] = None) -> None:
    """Remember a typed search; repeating one moves it to the top instead of adding a copy."""
    query = (query or "").strip()[:MAX_QUERY_CHARS]
    if not query:
        return
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    flag = 1 if internet else 0
    used = ",".join(sorted(set(sources or [])))
    existing = db_get(
        "SELECT id FROM search_history WHERE user_id = ? AND query = ? AND internet = ? AND sources = ?",
        (user_id, query, flag, used),
    )
    if existing:
        db_run("UPDATE search_history SET result_count = ?, updated_at = ? WHERE id = ?",
               (result_count, now, existing["id"]))
        return
    db_run(
        "INSERT INTO search_history (id, user_id, query, internet, sources, result_count, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), user_id, query, flag, used, result_count, now, now),
    )
    db_run(
        "DELETE FROM search_history WHERE user_id = ? AND id NOT IN "
        "(SELECT id FROM search_history WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?)",
        (user_id, user_id, MAX_PER_USER),
    )


@router.get("")
async def list_search_history(user: Dict[str, Any] = Depends(require_auth)):
    rows = db_all(
        "SELECT id, query, internet, sources, result_count, updated_at FROM search_history "
        "WHERE user_id = ? ORDER BY updated_at DESC",
        (user["id"],),
    )
    return {"searches": [
        {"id": r["id"], "query": r["query"], "internet": bool(r["internet"]),
         "sources": [s for s in (r["sources"] or "").split(",") if s],
         "resultCount": r["result_count"], "updatedAt": r["updated_at"]}
        for r in rows
    ]}


@router.delete("")
async def clear_search_history(user: Dict[str, Any] = Depends(require_auth)):
    db_run("DELETE FROM search_history WHERE user_id = ?", (user["id"],))
    return {"success": True}


@router.delete("/{search_id}")
async def delete_search(search_id: str, user: Dict[str, Any] = Depends(require_auth)):
    if not db_get("SELECT id FROM search_history WHERE id = ? AND user_id = ?", (search_id, user["id"])):
        raise HTTPException(status_code=404, detail="Search not found")
    db_run("DELETE FROM search_history WHERE id = ?", (search_id,))
    return {"success": True, "deleted": search_id}
