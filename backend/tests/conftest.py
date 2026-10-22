"""
pytest conftest for Smart-Finder backend tests.

Provides fixtures that allow isolated, reproducible tests:
  - Temporary SQLite database, upload and knowledge_base folders (never the live data)
  - Temporary FAISS storage directory (indexes created fresh per test)
  - Model monkeypatches that return deterministic fixed-size vectors
  - An authenticated TestClient for API tests
"""
import contextlib
import os
import pytest
import numpy as np
from pathlib import Path
from typing import List, Optional

# ── Ensure backend root is importable ────────────────────────────────────────
import sys
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

TEST_ADMIN_EMAIL = "admin@smartfind-tests.dev"
TEST_ADMIN_PASSWORD = "Test-Admin-Password-1"


# ── Deterministic fake embeddings (test-only, never in production) ────────────
TEXT_DIM  = 1024
IMAGE_DIM = 1024
FACE_DIM  = 512

def _unit_vector(seed: int, dim: int) -> List[float]:
    """Returns a reproducible unit-length float32 vector of length dim."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()

def _stable_seed(text: str) -> int:
    import zlib
    return zlib.crc32(text.encode("utf-8")) & 0x7FFFFFFF

def fake_text_embedding(text: str) -> Optional[List[float]]:
    return _unit_vector(_stable_seed(text or ""), TEXT_DIM) if text and text.strip() else None

def fake_image_embedding(image_input) -> Optional[List[float]]:
    return _unit_vector(_stable_seed(str(image_input)), IMAGE_DIM)

def fake_multimodal_text_embedding(text: str) -> Optional[List[float]]:
    return _unit_vector(_stable_seed("clip:" + (text or "")), IMAGE_DIM) if text else None

def fake_batch(texts):
    return [fake_text_embedding(t or "") for t in texts]

def fake_rerank(query, passages, instruction=None):
    """Share of the query's words found in each passage (deterministic stand-in)."""
    import re
    q = set(re.findall(r"\w+", (query or "").lower()))
    return [len(q & set(re.findall(r"\w+", (p or "").lower()))) / max(1, len(q)) for p in passages]

def fake_florence(images, task="<MORE_DETAILED_CAPTION>", max_new_tokens=96):
    """Captions that name the dominant colour, so tests can search for them."""
    out = []
    for im in images:
        r, g, b = im.convert("RGB").resize((1, 1)).getpixel((0, 0))
        colour = max((("red", r), ("green", g), ("blue", b)), key=lambda kv: kv[1])[0]
        out.append(f"A mostly {colour} picture with a bright rectangle" if "CAPTION" in task else None)
    return out

def fake_clap_windows(path, should_stop=None):
    """One 10 s window per file, with a vector derived from the file name."""
    from pathlib import Path as _P
    return [(0.0, 10.0, _unit_vector(_stable_seed("clap-win:" + _P(path).name), 512))]

def fake_image_batch(images, batch_size: int = 16):
    """Content-derived vectors: identical pixels give identical embeddings."""
    import zlib
    out = []
    for im in images:
        thumb = im.convert("RGB").resize((16, 16))
        out.append(_unit_vector(zlib.crc32(thumb.tobytes()) & 0x7FFFFFFF, IMAGE_DIM))
    return out


# Modules that import model functions by name at import time; each needs patching.
_MODEL_FUNCTION_HOMES = (
    "app.search.model_pipeline",
    "app.processing.processors",
    "app.search.multimodal_retrieval",
    "app.search.query_understanding",
)


def _patch_everywhere(monkeypatch, name, fn):
    import importlib
    for mod_name in _MODEL_FUNCTION_HOMES:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, fn)


# ── Settings / DB path override ───────────────────────────────────────────────
@pytest.fixture(scope="function")
def tmp_db(tmp_path, monkeypatch):
    """
    Points the database, uploads and knowledge_base folders at fresh temp locations
    and runs all migrations, returning the temp db path.
    """
    db_path = tmp_path / "test_smartfind.db"
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(cfg.settings, "UPLOAD_DIR", str(tmp_path / "uploads"), raising=False)
    monkeypatch.setattr(cfg.settings, "KB_DIR", str(tmp_path / "knowledge_base"), raising=False)
    monkeypatch.setattr(cfg.settings, "UPLOADS_LIBRARY_DIR", str(tmp_path / "uploads-library"), raising=False)
    monkeypatch.setattr(cfg.settings, "LIBRARY_FALLBACK_DIR", str(tmp_path / "libraries"), raising=False)
    monkeypatch.setattr(cfg.settings, "ADMIN_EMAIL", TEST_ADMIN_EMAIL, raising=False)
    monkeypatch.setattr(cfg.settings, "ADMIN_PASSWORD", TEST_ADMIN_PASSWORD, raising=False)
    monkeypatch.setattr(cfg.settings, "DEMO_ADMIN_EMAIL", "", raising=False)

    from app.database.session import run_migrations
    run_migrations()
    return db_path


# ── Isolated FAISS manager ────────────────────────────────────────────────────
@pytest.fixture(scope="function")
def tmp_faiss(tmp_path):
    """
    Creates a fresh FAISSVectorManager in a temp directory and ensures
    the global singleton is reset after the test.
    """
    from app.search.faiss_index import get_faiss_manager, reset_faiss_manager
    faiss_dir = tmp_path / "faiss"
    mgr = get_faiss_manager(storage_dir=faiss_dir)
    yield mgr
    reset_faiss_manager()


# ── Model monkeypatches ───────────────────────────────────────────────────────
@pytest.fixture(scope="function")
def mock_models_unavailable(monkeypatch):
    """
    Makes all model getters return None (simulates cold start / unavailable models).
    Used to verify that code paths handle Optional embeddings correctly.
    """
    import app.search.model_pipeline as mp
    monkeypatch.setattr(mp, "_get_qwen_model", lambda *a, **k: None)
    monkeypatch.setattr(mp, "_get_image_model", lambda *a, **k: None)
    monkeypatch.setattr(mp, "_get_insightface_app", lambda *a, **k: None)
    monkeypatch.setattr(mp, "_get_whisper_model", lambda *a, **k: None)


@pytest.fixture(scope="function")
def mock_models_available(monkeypatch):
    """
    Injects deterministic fake model functions that return reproducible
    unit-length vectors (correct dimensionality, no fallback hashing).
    Faces, OCR and transcription return nothing.
    """
    _patch_everywhere(monkeypatch, "get_text_embedding", fake_text_embedding)
    _patch_everywhere(monkeypatch, "get_text_query_embedding", fake_text_embedding)
    _patch_everywhere(monkeypatch, "get_text_embeddings_batch", fake_batch)
    _patch_everywhere(monkeypatch, "get_image_embedding", fake_image_embedding)
    _patch_everywhere(monkeypatch, "get_image_embeddings_batch", fake_image_batch)
    _patch_everywhere(monkeypatch, "get_multimodal_text_embedding", fake_multimodal_text_embedding)
    # No picture+words vector and no picture reranker unless a test asks for them
    _patch_everywhere(monkeypatch, "get_composed_query_embedding", lambda *a, **k: None)
    _patch_everywhere(monkeypatch, "visual_rerank_enabled", lambda *a, **k: False)
    _patch_everywhere(monkeypatch, "pictures_on_gpu", contextlib.nullcontext)
    _patch_everywhere(monkeypatch, "rerank_images", lambda *a, **k: None)
    _patch_everywhere(monkeypatch, "text_likelihood", lambda *a, **k: 1.0)
    _patch_everywhere(monkeypatch, "detect_and_embed_faces", lambda *a, **k: [])
    _patch_everywhere(monkeypatch, "transcribe_audio", lambda *a, **k: [])
    _patch_everywhere(monkeypatch, "transcribe_media",
                      lambda *a, **k: {"segments": [], "language": None, "language_probability": None, "duration": None})
    _patch_everywhere(monkeypatch, "run_ocr", lambda *a, **k: "")
    _patch_everywhere(monkeypatch, "release_transcription_model", lambda *a, **k: False)
    _patch_everywhere(monkeypatch, "prepare_for_transcription", lambda *a, **k: None)
    _patch_everywhere(monkeypatch, "finish_transcription", lambda *a, **k: None)
    _patch_everywhere(monkeypatch, "release_cached_vram", lambda *a, **k: None)
    _patch_everywhere(monkeypatch, "rerank", fake_rerank)
    _patch_everywhere(monkeypatch, "trim_vram", lambda *a, **k: None)
    _patch_everywhere(monkeypatch, "florence_describe", fake_florence)
    _patch_everywhere(monkeypatch, "clap_audio_windows", fake_clap_windows)
    _patch_everywhere(monkeypatch, "clap_audio_embedding", lambda path: _unit_vector(_stable_seed("clap-audio"), 512))
    _patch_everywhere(monkeypatch, "clap_text_embedding",
                      lambda text: _unit_vector(_stable_seed("clap:" + text), 512) if text else None)
    for hook in ("prepare_for_captions", "finish_captions", "prepare_for_sounds", "finish_sounds",
                 "prepare_for_image_vectors", "finish_image_vectors", "prepare_for_pictures",
                 "settle_for_search", "release_indexing_models"):
        _patch_everywhere(monkeypatch, hook, lambda *a, **k: None)


# ── Folder libraries ──────────────────────────────────────────────────────────
def _reset_library_singletons():
    from app.library.manager import reset_library_manager
    from app.library.service import reset_library_service
    from app.ingest.pipeline import reset_pipeline
    from app.search.engine import reset_engine
    reset_library_service()
    reset_pipeline()
    reset_engine()
    reset_library_manager()


@pytest.fixture(scope="function")
def manager(tmp_db):
    """A fresh LibraryManager whose built-in libraries live in the temp folder (see tmp_db)."""
    from app.library.manager import get_library_manager
    _reset_library_singletons()
    m = get_library_manager()
    m.load_all()
    yield m
    _reset_library_singletons()


# ── API client ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="function")
def client(tmp_db, tmp_faiss, mock_models_available, monkeypatch):
    """TestClient running the full app lifespan against the isolated data dirs."""
    from fastapi.testclient import TestClient
    from app.api.v1 import auth as auth_module
    auth_module._failed_logins.clear()
    # LLM calls must never leave the test process, and real models must not warm up
    from app.core import config as cfg
    for key in ("GROQ_API_KEY", "GROQ_API_KEY_FALLBACK1", "GROQ_API_KEY_FALLBACK2", "GROQ_API_KEY_FALLBACK3"):
        monkeypatch.setattr(cfg.settings, key, "", raising=False)
    monkeypatch.setattr(cfg.settings, "ENVIRONMENT", "test", raising=False)

    _reset_library_singletons()
    from app.main import app
    with TestClient(app) as c:
        yield c
    _reset_library_singletons()


@pytest.fixture(scope="function")
def admin_client(client):
    """TestClient holding an authenticated admin session cookie."""
    res = client.post("/api/auth/login", json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD})
    assert res.status_code == 200, res.text
    return client
