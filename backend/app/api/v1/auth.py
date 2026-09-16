import uuid
from fastapi import APIRouter, Response, HTTPException, status, Depends
from app.core.config import settings
from app.core.security import hash_password, verify_password, sign_token
from app.schemas.auth import UserLogin, UserSignup, AuthResponse, UserResponse
from app.database.session import db_get, db_run
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=AuthResponse)
async def login(data: UserLogin, response: Response):
    user = db_get("SELECT id, email, username, password_hash, role FROM users WHERE email = ?", (data.email.lower(),))
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    token = sign_token({
        "userId": user["id"],
        "email": user["email"],
        "username": user["username"],
        "role": user["role"],
    })

    # Set HTTP-only cookie matching Next.js sf_auth
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        max_age=settings.JWT_EXPIRES_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        path="/"
    )

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

    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        max_age=settings.JWT_EXPIRES_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        path="/"
    )

    return {
        "user": {
            "id": user_id,
            "email": data.email.lower(),
            "username": data.username.strip(),
            "role": "user",
        }
    }

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

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(
        key=settings.COOKIE_NAME,
        path="/"
    )
    return {"success": True}
