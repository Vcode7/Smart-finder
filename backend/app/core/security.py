import datetime
import bcrypt
import jwt
from typing import Optional, Dict, Any
from app.core.config import settings

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def sign_token(payload: Dict[str, Any]) -> str:
    to_encode = payload.copy()
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=settings.JWT_EXPIRES_DAYS)
    to_encode.update({"exp": expire, "iat": datetime.datetime.now(datetime.timezone.utc)})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def verify_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        decoded = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return decoded
    except Exception:
        return None
