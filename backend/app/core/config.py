import os
from pathlib import Path
from typing import List, Dict
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Built-in fallbacks. Running with these is only tolerated in development.
DEFAULT_JWT_SECRET = "smart-find-super-secret-jwt-key-change-in-production"
DEFAULT_ADMIN_PASSWORD = "Admin@123456"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # The backend only listens on loopback; the Next.js frontend is the
    # network-facing entry point and proxies /api/* to it.
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"

    # Storage paths
    DB_PATH: str = "data/smartfind.db"
    UPLOAD_DIR: str = "data/uploads"
    KB_DIR: str = "data/knowledge_base"
    SEED_DEMO_KNOWLEDGE: bool = False
    # Built-in library receiving browser uploads (searched like any other library).
    # Must differ from UPLOAD_DIR even in letter case: Windows paths are case-insensitive.
    UPLOADS_LIBRARY_DIR: str = "data/uploads-library"
    # Index location for libraries whose folder is read-only, and for the Linked library
    LIBRARY_FALLBACK_DIR: str = "data/libraries"

    # OCR / model caches
    OCR_ENGINE: str = "paddle"                  # paddle (PP-OCRv6) | tesseract
    OCR_PADDLE_MODEL: str = ""                  # PP-OCRv6 tier: tiny | small | medium; empty = medium on a GPU, small on CPU
    # PP-OCRv6 has no Devanagari model: lines it reads below this confidence are re-read
    # by Tesseract when Hindi is in OCR_LANGUAGES
    OCR_PADDLE_MIN_CONFIDENCE: float = 0.80
    TESSDATA_DIR: str = "tessdata"
    OCR_LANGUAGES: str = "eng+hin"
    HF_HOME: str = ""
    # Qwen3-VL-Reranker re-judges the best pictures for a typed query (~4 GB more VRAM):
    # auto = on for GPUs with at least 12 GB | on | off
    VISUAL_RERANK: str = "auto"

    # Auth
    JWT_SECRET: str = DEFAULT_JWT_SECRET
    ADMIN_EMAIL: str = "admin@smartfind.ai"
    ADMIN_PASSWORD: str = DEFAULT_ADMIN_PASSWORD
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRES_DAYS: int = 7
    COOKIE_NAME: str = "sf_auth"
    # Open self-registration is off by default: the frontend is reachable from the
    # local network, and every account can read the whole knowledge base.
    ALLOW_SIGNUP: bool = False
    # Secret code that lets someone create an administrator account from the sign-in page.
    # Empty (or the .env.example placeholder) disables public admin sign-up; admins can
    # always create further accounts from the Users page.
    ADMIN_SETUP_CODE: str = ""
    LOGIN_MAX_FAILURES: int = 10
    LOGIN_LOCKOUT_MINUTES: int = 15

    # Ollama Local LLM
    OLLAMA_ENDPOINT: str = "http://localhost:11434"
    OLLAMA_MODEL: str = ""
    OLLAMA_TIMEOUT: float = 12.0

    # Groq AI
    GROQ_API_KEY: str = ""
    GROQ_API_KEY_FALLBACK1: str = ""
    GROQ_API_KEY_FALLBACK2: str = ""
    GROQ_API_KEY_FALLBACK3: str = ""
    GROQ_MODEL: str = "qwen/qwen3.8-27b"
    GROQ_FAST_MODEL: str = "qwen/qwen3.8-27b"

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
    def admin_signup_enabled(self) -> bool:
        code = self.ADMIN_SETUP_CODE.strip()
        return bool(code) and code != "choose-a-setup-code"

    def insecure_defaults(self) -> List[str]:
        """Names of security-sensitive settings still using their built-in defaults."""
        issues = []
        if self.JWT_SECRET == DEFAULT_JWT_SECRET:
            issues.append("JWT_SECRET")
        if self.ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD:
            issues.append("ADMIN_PASSWORD")
        return issues

    @staticmethod
    def _resolve(raw: str) -> Path:
        p = Path(raw)
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        return p

    @property
    def resolved_db_path(self) -> Path:
        return self._resolve(self.DB_PATH)

    @property
    def resolved_upload_dir(self) -> Path:
        return self._resolve(self.UPLOAD_DIR)

    @property
    def resolved_kb_dir(self) -> Path:
        return self._resolve(self.KB_DIR)

    @property
    def resolved_tessdata_dir(self) -> Path:
        return self._resolve(self.TESSDATA_DIR)

    @property
    def resolved_uploads_library_dir(self) -> Path:
        return self._resolve(self.UPLOADS_LIBRARY_DIR)

    @property
    def resolved_library_fallback_dir(self) -> Path:
        return self._resolve(self.LIBRARY_FALLBACK_DIR)

settings = Settings()


def _apply_runtime_environment() -> None:
    """Export environment variables that third-party libraries read at import time."""
    tessdata = settings.resolved_tessdata_dir
    if "TESSDATA_PREFIX" not in os.environ and tessdata.is_dir():
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    if settings.HF_HOME.strip() and "HF_HOME" not in os.environ:
        os.environ["HF_HOME"] = str(settings._resolve(settings.HF_HOME.strip()))
    # PaddleOCR: no network round-trip at startup when its models are already downloaded
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


_apply_runtime_environment()
