"""Which libraries a signed-in user may query.

Admins see every library. A regular user sees only the libraries an admin has shared
with them (`library_access`); a user with no grants sees nothing.
"""
from typing import Any, Dict, Iterable, List, Optional, Set

from app.database.session import db_all


def is_admin(user: Optional[Dict[str, Any]]) -> bool:
    return bool(user) and user.get("role") == "admin"


def visible_library_ids(user: Optional[Dict[str, Any]]) -> Optional[Set[str]]:
    """None means "no restriction" (admin); otherwise the set of shared library ids."""
    if is_admin(user):
        return None
    if not user:
        return set()
    rows = db_all("SELECT library_id FROM library_access WHERE user_id = ?", (user["id"],))
    return {r["library_id"] for r in rows}


def can_access_library(user: Optional[Dict[str, Any]], lib_id: str) -> bool:
    allowed = visible_library_ids(user)
    return allowed is None or lib_id in allowed


def can_access_source(user: Optional[Dict[str, Any]], source_id: str) -> bool:
    allowed = visible_library_ids(user)
    if allowed is None:
        return True
    from app.library.manager import get_library_manager
    found = get_library_manager().find_source(source_id)
    return found is not None and found[0].id in allowed


def filter_libraries(user: Optional[Dict[str, Any]], libs: Iterable[Any]) -> List[Any]:
    allowed = visible_library_ids(user)
    return list(libs) if allowed is None else [lib for lib in libs if lib.id in allowed]
