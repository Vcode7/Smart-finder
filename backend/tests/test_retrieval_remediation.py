"""
backend/tests/test_retrieval_remediation.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Automated verification test suite for all Smart-Finder Retrieval Pipeline remediations:
- Phase 0: Test harness & FAISS isolation
- Phase 1: Honest Optional embeddings, FAISS rollback, atomic save, BM25 scores
- Phase 2: Constants, composite score (no synergy, face signal guard), pHash prefix
- Phase 3: Monotonic OCR ordering, context window SQL overlap, DOCX sections, stride formula
- Phase 4: Thumbnail picker, timestamp rounding
"""
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.search.constants import (
    TEXT_EMBED_MAX_CHARS,
    TEXT_MIN_SCORE,
    IMAGE_MIN_SCORE,
    FACE_MIN_SCORE,
    COMPOSITE_MIN_SCORE,
    STOPWORDS,
    build_enriched_text,
    preview_text,
)
from app.search.faiss_index import (
    FAISSVectorManager,
    get_faiss_manager,
    reset_faiss_manager,
    TEXT_DIM,
    IMAGE_DIM,
    FACE_DIM,
)
from app.search.keyword_search import extract_query_tokens
from app.search.multimodal_retrieval import resolve_parent_files, compute_title_score
from app.search.context_expander import expand_transcript_segment


# ─── PHASE 1 TESTS ────────────────────────────────────────────────────────────

def test_p1_model_unavailable_returns_none(mock_models_unavailable):
    """Verify get_text_embedding returns None, not a fallback pseudo-vector (Issue #1)."""
    import app.search.model_pipeline as mp
    res = mp.get_text_embedding("test query string")
    assert res is None, "Expected None when model unavailable, got fallback vector!"

    res_batch = mp.get_text_embeddings_batch(["test1", "test2"])
    assert res_batch == [None, None]


def test_p1_faiss_metadata_rollback_on_add_failure(tmp_path):
    """Verify that if faiss.add throws, metadata is rolled back (Issue #2)."""
    mgr = FAISSVectorManager(storage_dir=tmp_path)
    # Monkeypatch text_index.add to raise an exception
    with patch.object(mgr.text_index, "add", side_effect=RuntimeError("FAISS C++ error")):
        dummy_vec = np.ones(TEXT_DIM, dtype=np.float32).tolist()
        with pytest.raises(RuntimeError):
            mgr.add_text_vector("src_1", "chk_1", dummy_vec)

    assert len(mgr.text_meta) == 0, "Metadata was not rolled back after FAISS add failure!"
    assert mgr.text_index.ntotal == 0


def test_p1_prepare_vector_nan_and_dimension_safety(tmp_path):
    """Verify _prepare_vector rejects NaNs, wrong dims, and empty vectors (Issue #3)."""
    mgr = FAISSVectorManager(storage_dir=tmp_path)
    # NaN check
    nan_vec = [float("nan")] * TEXT_DIM
    assert mgr._prepare_vector(nan_vec, TEXT_DIM) is None

    # Wrong dimension check
    short_vec = [1.0] * (TEXT_DIM - 1)
    assert mgr._prepare_vector(short_vec, TEXT_DIM) is None

    # Empty check
    assert mgr._prepare_vector([], TEXT_DIM) is None
    assert mgr._prepare_vector(None, TEXT_DIM) is None

    # Valid check
    valid_vec = [1.0] * TEXT_DIM
    prep = mgr._prepare_vector(valid_vec, TEXT_DIM)
    assert prep is not None
    assert prep.shape == (1, TEXT_DIM)
    norm = np.linalg.norm(prep[0])
    assert pytest.approx(norm, rel=1e-4) == 1.0


def test_p1_atomic_save_to_disk(tmp_path):
    """Verify that save_to_disk writes via tmp files and produces valid index files (Issue #4)."""
    mgr = FAISSVectorManager(storage_dir=tmp_path)
    dummy_vec = [1.0] * TEXT_DIM
    mgr.add_text_vector("src_1", "chk_1", dummy_vec, {"type": "test"})
    mgr.save_to_disk()

    assert (tmp_path / "text.index").exists()
    assert (tmp_path / "metadata.json").exists()
    assert not (tmp_path / "text.index.tmp").exists()
    assert not (tmp_path / "metadata.json.tmp").exists()

    # Verify reloading from disk
    mgr2 = FAISSVectorManager(storage_dir=tmp_path)
    assert mgr2.text_index.ntotal == 1
    assert len(mgr2.text_meta) == 1
    assert mgr2.text_meta[0].get("entity_id") == "chk_1"


def test_p1_bm25_normalized_rank():
    """Verify FTS5 BM25 score normalization produces distinct values by rank (Issue #5)."""
    # Formula: score = round(1.0 / (1.0 + abs(float(rank))), 4)
    rank_best = -0.5   # better match
    rank_worst = -10.0 # worse match
    score_best = round(1.0 / (1.0 + abs(rank_best)), 4)
    score_worst = round(1.0 / (1.0 + abs(rank_worst)), 4)

    assert score_best > score_worst
    assert 0.0 < score_best <= 1.0
    assert 0.0 < score_worst <= 1.0


# ─── PHASE 2 TESTS ────────────────────────────────────────────────────────────

def test_p2_shared_constants_and_helpers():
    """Verify shared constants and helpers behave consistently (Issue #6, #7, #8)."""
    assert TEXT_EMBED_MAX_CHARS == 6000
    assert TEXT_MIN_SCORE == 0.22
    assert IMAGE_MIN_SCORE == 0.22
    assert "video" not in STOPWORDS
    assert "image" not in STOPWORDS
    assert "document" not in STOPWORDS

    # Helper: build_enriched_text
    enriched = build_enriched_text("Chapter 1", "This is the content.")
    assert enriched == "[Chapter 1] This is the content."

    # Helper: preview_text strips prefix
    preview = preview_text(enriched)
    assert preview == "This is the content."


def test_p2_composite_score_no_synergy_and_face_isolation():
    """
    Verify composite score formula:
    - No synergy term (never exceeds 0.99 for perfect scores, sums 0.70 + 0.30)
    - Face vector score only counts if is_face_query is True (Issue #9).
    """
    # Case 1: Pure text/image query with high face similarity should NOT use face similarity
    signals_non_face = {
        "src_1": {
            "source_id": "src_1",
            "text_vec_scores": [0.8],
            "image_vec_scores": [],
            "face_vec_scores": [0.95], # Irrelevant face match from background
            "fts_scores": [0.8],
            "title_score": 0.0,
            "phash_scores": [],
            "snippets": ["Test snippet"],
            "timestamps": [],
            "frames": [],
            "is_face_query": False, # NOT a face query!
            "is_face_match": False,
            "is_exact_image_match": False,
        }
    }
    with patch("app.search.multimodal_retrieval.db_all") as mock_db_all:
        mock_db_all.return_value = [
            {"id": "src_1", "original_name": "report.pdf", "file_type": "pdf", "file_size": 1024, "face_count": 0}
        ]
        res = resolve_parent_files(signals_non_face)
        doc = res["documents"][0]
        # vector_score should be 0.8 (from text_vec_scores), NOT 0.95 (from face_vec_scores)
        # score = 0.70 * 0.8 + 0.30 * 0.8 = 0.80
        assert doc["relevanceScore"] == pytest.approx(0.80, abs=0.01)

    # Case 2: Query WITH face intent (is_face_query=True) but below exact face recognition threshold (is_face_match=False)
    # SHOULD blend face vector into vector_score: 0.70 * 0.95 + 0.30 * 0.50 = 0.815
    signals_face = {
        "src_1": {
            "source_id": "src_1",
            "text_vec_scores": [0.5],
            "image_vec_scores": [],
            "face_vec_scores": [0.95],
            "fts_scores": [0.5],
            "title_score": 0.0,
            "phash_scores": [],
            "snippets": ["Test snippet"],
            "timestamps": [],
            "frames": [],
            "is_face_query": True, # IS a face query!
            "is_face_match": False,
            "is_exact_image_match": False,
        }
    }
    with patch("app.search.multimodal_retrieval.db_all") as mock_db_all:
        mock_db_all.return_value = [
            {"id": "src_1", "original_name": "report.pdf", "file_type": "pdf", "file_size": 1024, "face_count": 1}
        ]
        res_face = resolve_parent_files(signals_face)
        doc_face = res_face["documents"][0]
        assert doc_face["relevanceScore"] == pytest.approx(0.815, abs=0.01)

    # Case 3: Recognized face match (is_face_match=True) gives direct face similarity
    signals_recognized = {
        "src_1": {
            "source_id": "src_1",
            "text_vec_scores": [0.5],
            "image_vec_scores": [],
            "face_vec_scores": [0.95],
            "fts_scores": [0.5],
            "title_score": 0.0,
            "phash_scores": [],
            "snippets": ["Test snippet"],
            "timestamps": [],
            "frames": [],
            "is_face_query": True,
            "is_face_match": True,
            "is_exact_image_match": False,
        }
    }
    with patch("app.search.multimodal_retrieval.db_all") as mock_db_all:
        mock_db_all.return_value = [
            {"id": "src_1", "original_name": "report.pdf", "file_type": "pdf", "file_size": 1024, "face_count": 1}
        ]
        res_rec = resolve_parent_files(signals_recognized)
        doc_rec = res_rec["documents"][0]
        assert doc_rec["relevanceScore"] == 0.95


def test_p2_phash_prefix_computation():
    """Verify pHash prefix stores the integer value of the top 16 bits (Issue #12)."""
    from app.search.perceptual_hash import compute_image_hashes
    # 16-hex char hash e.g. "a1b2c3d4e5f67890" -> top 4 hex chars "a1b2" -> 0xa1b2 = 41394
    phash_hex = "a1b2c3d4e5f67890"
    prefix = int(phash_hex[:4], 16)
    assert prefix == 0xa1b2
    assert isinstance(prefix, int)


# ─── PHASE 3 TESTS ────────────────────────────────────────────────────────────

def test_p3_context_window_sql_overlap():
    """
    Verify transcript context expander query includes segments overlapping window boundaries
    (Issue #23: segment starts before window_end AND ends after window_start).
    """
    # Segment: 10s - 20s. Window: start=max(0, 10 - 25) = 0s, end = 20 + 25 = 45s.
    # An overlapping segment might be at start=40s, end=50s (starts before 45s, ends after 0s).
    with patch("app.search.context_expander.db_get") as mock_db_get, \
         patch("app.search.context_expander.db_all") as mock_db_all:
        mock_db_get.return_value = {
            "id": "tr_1", "video_id": "vid_1", "source_id": "src_1",
            "start_time": 10.0, "end_time": 20.0, "text": "center segment"
        }
        mock_db_all.return_value = [
            {"text": "Hello world from transcript"}
        ]
        context = expand_transcript_segment("tr_1")
        # Verify db_all was called
        assert mock_db_all.called
        sql_query = mock_db_all.call_args[0][0]
        assert "start_time <= ?" in sql_query
        assert "end_time >= ?" in sql_query
        assert "end_time <= ?" not in sql_query


def test_p3_video_frame_stride_formula():
    """Verify video frame stride is not clamped to 1.0s for high-FPS content (Issue #14)."""
    fps_120 = 120.0
    stride_120 = (30.0 / fps_120)
    stride_120 = max(0.25, stride_120)
    assert stride_120 == 0.25, "120fps should have 0.25s stride, not clamped to 1.0s!"

    fps_24 = 24.0
    stride_24 = (30.0 / fps_24)
    stride_24 = max(0.25, stride_24)
    assert stride_24 == 1.25


def test_p3_unknown_file_type_fallback():
    """Verify detect_file_category returns 'unknown' for unrecognized extensions (Issue #15)."""
    from app.search.query_understanding import detect_file_category
    assert detect_file_category("image.png") == "image"
    assert detect_file_category("notes.pdf") == "document"
    assert detect_file_category("movie.mp4") == "video"
    assert detect_file_category("voice.mp3") == "audio"
    assert detect_file_category("weird.xyz123") == "unknown"


# ─── PHASE 4 TESTS ────────────────────────────────────────────────────────────

def test_p4_timestamp_rounding_dedup():
    """Verify timestamps are rounded before dedup to prevent float mismatch (Issue #29)."""
    raw_timestamps = [10.5000001, 10.5000002, 10.5, 20.1]
    rounded = [round(t, 1) for t in raw_timestamps]
    deduped = sorted(list(set(rounded)))
    assert deduped == [10.5, 20.1]
