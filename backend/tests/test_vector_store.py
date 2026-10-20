"""
Vector store tests: SQLite-backed FAISS indexes with checkpoint/replay and tiering.
"""
import numpy as np
import pytest

from app.library.db import LibraryDB
from app.library import vector_store as vs


def _vec(seed: int, dim: int = 1024) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def store(tmp_path):
    db = LibraryDB(tmp_path / "index.db")
    s = vs.VectorStore(db, tmp_path / "vectors")
    yield s, db, tmp_path
    db.close()


def test_add_search_and_remove(store):
    s, db, _ = store
    ids = s.add("text", [(i, f"src{i % 3}", _vec(i)) for i in range(30)])
    assert len(ids) == 30
    hits = s.search("text", _vec(7), k=3)
    assert hits[0][0] == ids[7] and hits[0][1] == pytest.approx(1.0, abs=1e-3)

    s.remove_source("src1")
    remaining = {r["source_id"] for r in db.all("SELECT source_id FROM vectors")}
    assert remaining == {"src0", "src2"}
    hit_ids = {i for i, _ in s.search("text", _vec(7), k=30)}
    assert ids[7] not in hit_ids  # 7 % 3 == 1 → removed
    assert s.spaces["text"].ntotal == 20


def test_filtered_search_exact_and_selector(store, monkeypatch):
    s, _, _ = store
    ids = s.add("face", [(i, "src", _vec(i, 512)) for i in range(50)])
    allowed = ids[10:20]
    hits = s.search("face", _vec(15, 512), k=5, allowed_ids=allowed)
    assert hits[0][0] == ids[15]
    assert all(h[0] in allowed for h in hits)

    # Force the FAISS selector path instead of exact scoring
    monkeypatch.setattr(vs, "EXACT_SUBSET_LIMIT", 0)
    hits = s.search("face", _vec(15, 512), k=5, allowed_ids=allowed)
    assert hits[0][0] == ids[15]
    assert all(h[0] in allowed for h in hits)


def test_checkpoint_replay_and_tombstones_survive_restart(store):
    s, db, tmp = store
    first = s.add("clip", [(i, "keep", _vec(i)) for i in range(10)])
    s.checkpoint()
    # Added after the checkpoint (must be replayed), and deleted after it (tombstoned)
    later = s.add("clip", [(100 + i, "late", _vec(100 + i)) for i in range(5)])
    s.remove_source("keep")
    # Simulate a crash: no checkpoint; reopen from disk
    s2 = vs.VectorStore(db, tmp / "vectors")
    assert s2.spaces["clip"].ntotal == 5
    top = s2.search("clip", _vec(102), k=1)
    assert top[0][0] == later[2]
    assert all(h[0] not in first for h in s2.search("clip", _vec(3), k=15))


def test_missing_index_file_is_rebuilt_from_sqlite(store):
    s, db, tmp = store
    ids = s.add("text", [(i, "src", _vec(i)) for i in range(12)])
    s.checkpoint()
    (tmp / "vectors" / "text.faiss").unlink()
    s2 = vs.VectorStore(db, tmp / "vectors")
    assert s2.spaces["text"].ntotal == 12
    assert s2.search("text", _vec(4), k=1)[0][0] == ids[4]


def test_ivfpq_tier_with_exact_rerank(store, monkeypatch):
    s, db, tmp = store
    monkeypatch.setattr(vs, "IVF_THRESHOLD", 1000)
    rows = [(i, f"s{i % 7}", _vec(i, 512)) for i in range(3000)]
    with db.write() as c:
        ids = vs.VectorStore.insert_rows(c, "face", rows)
    s.spaces["face"].rebuild()
    assert s.spaces["face"].kind == "ivfpq"
    hits = s.search("face", _vec(1234, 512), k=5)
    assert hits[0][0] == ids[1234]
    assert hits[0][1] == pytest.approx(1.0, abs=2e-3)  # re-scored exactly, not PQ-approximate

    allowed = ids[1200:1300]
    monkeypatch.setattr(vs, "EXACT_SUBSET_LIMIT", 0)
    hits = s.search("face", _vec(1234, 512), k=3, allowed_ids=allowed)
    assert hits[0][0] == ids[1234]

    # Survives reload as IVF-PQ
    s2 = vs.VectorStore(db, tmp / "vectors")
    assert s2.spaces["face"].kind == "ivfpq"
    assert s2.search("face", _vec(42, 512), k=1)[0][0] == ids[42]


def test_unicode_storage_path(tmp_path):
    folder = tmp_path / "परीक्षा फ़ोल्डर" / ".smartfind"
    db = LibraryDB(folder / "index.db")
    s = vs.VectorStore(db, folder / "vectors")
    ids = s.add("text", [(1, "src", _vec(1))])
    s.checkpoint()
    s2 = vs.VectorStore(db, folder / "vectors")
    assert s2.search("text", _vec(1), k=1)[0][0] == ids[0]
    db.close()
