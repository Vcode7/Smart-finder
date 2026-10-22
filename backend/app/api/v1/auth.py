import secrets
import time
import uuid
import threading
from typing import Dict, List
from fastapi import APIRouter, Response, HTTPException, status, Depends
from pydantic import BaseModel, Field
from app.core.config import settings
from app.core.security import hash_password, verify_password, sign_token
from app.schemas.auth import UserLogin, UserSignup, AuthResponse, UserResponse
from app.database.session import db_get, db_run
from app.api.deps import get_current_user, require_auth

router = APIRouter(prefix="/auth", tags=["auth"])

# Failed-login tracking per account. All traffic arrives through the Next.js proxy
# from 127.0.0.1, so limiting per client IP would be meaningless; limit per email.
_failed_logins: Dict[str, List[float]] = {}
_failed_lock = threading.Lock()


def _lockout_remaining(email: str) -> int:
    window = settings.LOGIN_LOCKOUT_MINUTES * 60
    now = time.time()
    with _failed_lock:
        attempts = [t for t in _failed_logins.get(email, []) if now - t < window]
        _failed_logins[email] = attempts
        if len(attempts) >= settings.LOGIN_MAX_FAILURES:
            return int(window - (now - attempts[0])) + 1
    return 0


def _record_failure(email: str) -> None:
    with _failed_lock:
        _failed_logins.setdefault(email, []).append(time.time())


def _clear_failures(email: str) -> None:
    with _failed_lock:
        _failed_logins.pop(email, None)


def _set_auth_cookie(response: Response, token: str) -> None:
    # HTTP-only cookie read by both the backend and the Next.js proxy (sf_auth)
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        max_age=settings.JWT_EXPIRES_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        path="/"
    )


@router.post("/login", response_model=AuthResponse)
async def login(data: UserLogin, response: Response):
    email = data.email.lower()
    remaining = _lockout_remaining(email)
    if remaining:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-in attempts. Try again in {max(1, remaining // 60)} minute(s)."
        )

    user = db_get("SELECT id, email, username, password_hash, role FROM users WHERE email = ?", (email,))
    if not user or not verify_password(data.password, user["password_hash"]):
        _record_failure(email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    _clear_failures(email)

    token = sign_token({
        "userId": user["id"],
        "email": user["email"],
        "username": user["username"],
        "role": user["role"],
    })
    _set_auth_cookie(response, token)

    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "username": user["username"],
            "role": user["role"],
        }
    }

@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=AuthResponse)
async def signup(data: UserSignup, response: Response):
    if not settings.ALLOW_SIGNUP:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sign-up is disabled on this server. Ask the administrator for an account (set ALLOW_SIGNUP=true in backend/.env to enable it)."
        )

    existing = db_get("SELECT id FROM users WHERE email = ?", (data.email.lower(),))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(data.password)

    db_run(
        "INSERT INTO users (id, email, username, password_hash, role) VALUES (?, ?, ?, ?, 'user')",
        (user_id, data.email.lower(), data.username.strip(), pw_hash),
    )

    token = sign_token({
        "userId": user_id,
        "email": data.email.lower(),
        "username": data.username.strip(),
        "role": "user",
    })
    _set_auth_cookie(response, token)

    return {
        "user": {
            "id": user_id,
            "email": data.email.lower(),
            "username": data.username.strip(),
            "role": "user",
        }
    }


class AdminSignup(UserSignup):
    setupCode: str


@router.post("/signup-admin", status_code=status.HTTP_201_CREATED, response_model=AuthResponse)
async def signup_admin(data: AdminSignup, response: Response):
    """Create an administrator account from the sign-in page, guarded by ADMIN_SETUP_CODE."""
    if not settings.admin_signup_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin sign-up is disabled on this server. Set ADMIN_SETUP_CODE in backend/.env to enable it."
        )

    email = data.email.lower()
    # The setup code is a shared secret, so wrong guesses count against the same
    # per-email lockout as sign-in attempts.
    remaining = _lockout_remaining(email)
    if remaining:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {max(1, remaining // 60)} minute(s)."
        )
    if not secrets.compare_digest(data.setupCode.strip().encode(), settings.ADMIN_SETUP_CODE.strip().encode()):
        _record_failure(email)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin setup code")
    _clear_failures(email)

    if len(data.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    if db_get("SELECT id FROM users WHERE email = ?", (email,)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User with this email already exists")

    user_id = str(uuid.uuid4())
    username = data.username.strip()
    db_run(
        "INSERT INTO users (id, email, username, password_hash, role) VALUES (?, ?, ?, ?, 'admin')",
        (user_id, email, username, hash_password(data.password)),
    )
    _set_auth_cookie(response, sign_token({
        "userId": user_id, "email": email, "username": username, "role": "admin",
    }))
    return {"user": {"id": user_id, "email": email, "username": username, "role": "admin"}}


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str = Field(min_length=8)


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, user: dict = Depends(require_auth)):
    row = db_get("SELECT password_hash FROM users WHERE id = ?", (user["id"],))
    if not row or not verify_password(req.currentPassword, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if req.newPassword == req.currentPassword:
        raise HTTPException(status_code=400, detail="New password must be different from the current one")
    db_run(
        "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
        (hash_password(req.newPassword), user["id"]),
    )
    return {"success": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "username": user["username"],
            "role": user["role"],
        }
    }

@router.get("/config")
async def auth_config():
    """Public flags the login/signup pages need before a user is signed in."""
    return {"allowSignup": settings.ALLOW_SIGNUP, "allowAdminSignup": settings.admin_signup_enabled}

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(
        key=settings.COOKIE_NAME,
        path="/"
    )
    return {"success": True}
