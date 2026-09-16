import os
from pathlib import Path
from typing import List, Dict
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"

    # Storage paths
    DB_PATH: str = "../workspace/data/smartfind.db"
    UPLOAD_DIR: str = "../workspace/uploads"
    KB_DIR: str = "../workspace/knowledge_base"
    MAX_FILE_SIZE_MB: int = 500
    SEED_DEMO_KNOWLEDGE: bool = False

    # Auth
    JWT_SECRET: str = "smart-find-super-secret-jwt-key-change-in-production"
    ADMIN_EMAIL: str = "admin@smartfind.ai"
    ADMIN_PASSWORD: str = "Admin@123456"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRES_DAYS: int = 7
    COOKIE_NAME: str = "sf_auth"

    # Groq AI
    GROQ_API_KEY: str = ""
    GROQ_API_KEY_FALLBACK1: str = ""
    GROQ_API_KEY_FALLBACK2: str = ""
    GROQ_API_KEY_FALLBACK3: str = ""
    GROQ_MODEL: str = "qwen/qwen3.6-27b"
    GROQ_FAST_MODEL: str = "qwen/qwen3.6-27b"

    def get_groq_api_keys(self) -> List[Dict[str, str]]:
        """Return configured Groq API keys in prioritized sequence (primary -> fallback 1..3)."""
        candidates = [
            ("Primary key", self.GROQ_API_KEY),
            ("Fallback key 1", self.GROQ_API_KEY_FALLBACK1),
            ("Fallback key 2", self.GROQ_API_KEY_FALLBACK2),
            ("Fallback key 3", self.GROQ_API_KEY_FALLBACK3),
        ]
        return [{"label": label, "key": key.strip()} for label, key in candidates if key and key.strip()]

    # External Search Keys
    YOUTUBE_API_KEY: str = ""
    SERP_API_KEY: str = ""
    NEWS_API_KEY: str = ""
    SEMANTIC_SCHOLAR_API_KEY: str = ""

    def get_cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def resolved_db_path(self) -> Path:
        p = Path(self.DB_PATH)
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        return p

    @property
    def resolved_upload_dir(self) -> Path:
        p = Path(self.UPLOAD_DIR)
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        return p

    @property
    def resolved_kb_dir(self) -> Path:
        p = Path(self.KB_DIR)
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        return p

settings = Settings()
