from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, status, Depends
from app.core.config import settings
from app.core.security import verify_token
from app.database.session import db_get

async def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    # Identity comes only from a signed JWT (cookie or Bearer header). Client-supplied
    # identity headers such as x-user-id are never trusted.
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        return None

    payload = verify_token(token)
    if not payload:
        return None

    user_id = payload.get("userId") or payload.get("id")
    if not user_id:
        return None

    user = db_get("SELECT id, email, username, role FROM users WHERE id = ?", (user_id,))
    return user

async def require_auth(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Dict[str, Any]:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    return user

async def require_admin(user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return user
