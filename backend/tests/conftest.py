"""
pytest conftest for Smart-Finder backend tests.

Provides fixtures that allow isolated, reproducible tests:
  - Temporary SQLite database (no shared state between test runs)
  - Temporary FAISS storage directory (indexes created fresh per test)
  - Model monkeypatches that return deterministic fixed-size vectors
    (never uses generate_fallback_embedding — that's the production bug we're fixing)
"""
import os
import pytest
import numpy as np
from pathlib import Path
from typing import Optional, List
from unittest.mock import MagicMock

# ── Ensure backend root is importable ────────────────────────────────────────
import sys
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"


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

def fake_text_embedding(text: str) -> Optional[List[float]]:
    return _unit_vector(hash(text) % (2**31), TEXT_DIM)

def fake_image_embedding(image_input) -> Optional[List[float]]:
    seed = hash(str(image_input)) % (2**31)
    return _unit_vector(seed, IMAGE_DIM)

def fake_multimodal_text_embedding(text: str) -> Optional[List[float]]:
    return _unit_vector(hash("clip:" + text) % (2**31), IMAGE_DIM)


# ── Settings / DB path override ───────────────────────────────────────────────
@pytest.fixture(scope="function")
def tmp_db(tmp_path, monkeypatch):
    """
    Points settings.resolved_db_path at a fresh temp SQLite file
    and runs all migrations, returning the temp db path.
    """
    db_path = tmp_path / "test_smartfind.db"
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "DB_PATH", str(db_path), raising=False)

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
    monkeypatch.setattr(mp, "_get_qwen_model", lambda: None)
    monkeypatch.setattr(mp, "_get_jina_clip_model", lambda: None)
    monkeypatch.setattr(mp, "_get_insightface_app", lambda: None)
    monkeypatch.setattr(mp, "_get_whisper_model", lambda: None)


@pytest.fixture(scope="function")
def mock_models_available(monkeypatch):
    """
    Injects deterministic fake model functions that return reproducible
    unit-length vectors (correct dimensionality, no fallback hashing).
    """
    import app.search.model_pipeline as mp
    monkeypatch.setattr(mp, "get_text_embedding", fake_text_embedding)
    monkeypatch.setattr(mp, "get_image_embedding", fake_image_embedding)
    monkeypatch.setattr(mp, "get_multimodal_text_embedding", fake_multimodal_text_embedding)

    def fake_batch(texts):
        return [fake_text_embedding(t or "") for t in texts]
    monkeypatch.setattr(mp, "get_text_embeddings_batch", fake_batch)
