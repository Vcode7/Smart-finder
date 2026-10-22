import sqlite3
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import require_admin
from app.core.security import hash_password
from app.database.session import db_all, db_get, db_run, get_db_context
from app.library.manager import get_library_manager

router = APIRouter(prefix="/users", tags=["users"])

SYSTEM_USER_ID = "system"


class CreateUserRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8)
    role: Literal["user", "admin"] = "user"


class UpdateUserRequest(BaseModel):
    username: Optional[str] = Field(default=None, min_length=1, max_length=80)
    password: Optional[str] = Field(default=None, min_length=8)
    role: Optional[Literal["user", "admin"]] = None


class LibraryGrantRequest(BaseModel):
    libraryIds: List[str]


def _grants(user_id: str) -> List[str]:
    rows = db_all("SELECT library_id FROM library_access WHERE user_id = ? ORDER BY library_id", (user_id,))
    return [r["library_id"] for r in rows]


def _public(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "username": row["username"],
        "role": row["role"],
        "createdAt": row.get("created_at"),
        "libraryIds": _grants(row["id"]) if row["role"] != "admin" else [],
    }


def _get_user(user_id: str) -> Dict[str, Any]:
    row = None if user_id == SYSTEM_USER_ID else db_get(
        "SELECT id, email, username, role, created_at FROM users WHERE id = ?", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


def _admin_count() -> int:
    row = db_get("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND id != ?", (SYSTEM_USER_ID,))
    return int(row["n"]) if row else 0


@router.get("")
async def list_users(admin: Dict[str, Any] = Depends(require_admin)):
    rows = db_all(
        "SELECT id, email, username, role, created_at FROM users WHERE id != ? ORDER BY created_at, email",
        (SYSTEM_USER_ID,),
    )
    return {"users": [_public(r) for r in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(req: CreateUserRequest, admin: Dict[str, Any] = Depends(require_admin)):
    email = req.email.lower()
    if db_get("SELECT id FROM users WHERE email = ?", (email,)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User with this email already exists")
    user_id = str(uuid.uuid4())
    db_run(
        "INSERT INTO users (id, email, username, password_hash, role) VALUES (?, ?, ?, ?, ?)",
        (user_id, email, req.username.strip(), hash_password(req.password), req.role),
    )
    return {"user": _public(_get_user(user_id))}


@router.patch("/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest, admin: Dict[str, Any] = Depends(require_admin)):
    row = _get_user(user_id)
    if req.role is not None and req.role != row["role"]:
        if user_id == admin["id"]:
            raise HTTPException(status_code=400, detail="You cannot change your own role")
        if row["role"] == "admin" and _admin_count() <= 1:
            raise HTTPException(status_code=400, detail="At least one administrator is required")
    sets, params = [], []
    if req.username is not None:
        sets.append("username = ?")
        params.append(req.username.strip())
    if req.password is not None:
        sets.append("password_hash = ?")
        params.append(hash_password(req.password))
    if req.role is not None:
        sets.append("role = ?")
        params.append(req.role)
    if sets:
        db_run(f"UPDATE users SET {', '.join(sets)}, updated_at = datetime('now') WHERE id = ?",
               tuple(params) + (user_id,))
    return {"user": _public(_get_user(user_id))}


@router.delete("/{user_id}")
async def delete_user(user_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    row = _get_user(user_id)
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if row["role"] == "admin" and _admin_count() <= 1:
        raise HTTPException(status_code=400, detail="At least one administrator is required")
    try:
        with get_db_context() as conn:
            conn.execute("DELETE FROM library_access WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
    except sqlite3.IntegrityError:
        # knowledge_sources.uploaded_by (legacy index) still points at this account
        raise HTTPException(status_code=409, detail="This account owns legacy uploads and cannot be deleted")
    return {"success": True}


@router.get("/{user_id}/libraries")
async def get_user_libraries(user_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    _get_user(user_id)
    return {"libraryIds": _grants(user_id)}


@router.put("/{user_id}/libraries")
async def set_user_libraries(user_id: str, req: LibraryGrantRequest,
                             admin: Dict[str, Any] = Depends(require_admin)):
    row = _get_user(user_id)
    if row["role"] == "admin":
        raise HTTPException(status_code=400, detail="Administrators already have access to every library")
    manager = get_library_manager()
    wanted = list(dict.fromkeys(req.libraryIds))
    unknown = [lib_id for lib_id in wanted if manager.get(lib_id) is None]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown library: {unknown[0]}")
    with get_db_context() as conn:
        conn.execute("DELETE FROM library_access WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO library_access (user_id, library_id, granted_by) VALUES (?, ?, ?)",
            [(user_id, lib_id, admin["id"]) for lib_id in wanted],
        )
        conn.commit()
    return {"libraryIds": _grants(user_id)}
