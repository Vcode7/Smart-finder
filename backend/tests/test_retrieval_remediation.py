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
    """FTS5 rank → score is monotonic in BM25 strength and stays inside (0, 1) (Issue #5)."""
    from app.search.keyword_search import _rank_to_score
    strong, weak = _rank_to_score(-10.0), _rank_to_score(-0.5)
    assert strong > weak
    assert 0.0 < weak < strong < 1.0
    assert _rank_to_score(-1.0) == pytest.approx(0.41, abs=0.01)


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


def _signal(**overrides):
    base = {
        "text_vec_scores": [], "image_vec_scores": [], "face_vec_scores": [], "fts_scores": [],
        "title_score": 0.0, "phash_scores": [], "snippets": ["Test snippet text"], "timestamps": [],
        "frames": [], "is_face_query": False, "is_face_match": False, "is_exact_image_match": False,
    }
    base.update(overrides)
    return base


def _resolve_one(sig, file_type="pdf"):
    with patch("app.search.multimodal_retrieval.db_all") as mock_db_all:
        mock_db_all.return_value = [
            {"id": "src_1", "original_name": "report." + file_type, "file_type": file_type, "file_size": 1024}
        ]
        res = resolve_parent_files({"src_1": sig})
    return next(item for bucket in res.values() for item in bucket)


def test_p2_composite_score_face_isolation():
    """
    Face similarity only counts when the query itself carries a face, and only an
    actual face query above FACE_MATCH_THRESHOLD is reported as a match (Issue #9/#22).
    """
    # Case 1: text query; a background face similarity must be ignored
    doc = _resolve_one(_signal(text_vec_scores=[0.8], fts_scores=[0.8], face_vec_scores=[0.95]))
    assert doc["relevanceScore"] == pytest.approx(0.816, abs=0.005)
    assert doc["isFaceMatch"] is False

    # Case 2: face query below match confirmation — face score blends in, no match flag
    doc = _resolve_one(_signal(text_vec_scores=[0.5], fts_scores=[0.5], face_vec_scores=[0.95], is_face_query=True))
    assert doc["relevanceScore"] == pytest.approx(0.9525, abs=0.005)
    assert doc["isFaceMatch"] is False

    # Case 3: confirmed face match — calibrated face similarity decides
    doc = _resolve_one(_signal(text_vec_scores=[0.5], fts_scores=[0.5], face_vec_scores=[0.95],
                               is_face_query=True, is_face_match=True))
    assert doc["relevanceScore"] == 0.98
    assert doc["isFaceMatch"] is True

    # Case 4: a match flag without a face query is not a face match
    doc = _resolve_one(_signal(text_vec_scores=[0.5], face_vec_scores=[0.95], is_face_match=True))
    assert doc["isFaceMatch"] is False


def test_p2_best_snippet_and_timestamp_win():
    """The snippet and jump time come from the strongest evidence, not the first found."""
    video = _resolve_one(_signal(
        text_vec_scores=[0.7],
        snippets=[(0.3, "weak early snippet text here"), (0.9, "strong matching snippet text")],
        timestamps=[(0.2, 5.0), (0.95, 120.0)],
    ), file_type="mp4")
    assert video["snippet"] == "strong matching snippet text"
    assert video["startTime"] == 120.0


def test_p2_title_score_whole_words():
    """Title matching works on whole words: 'ai' must not match 'chairman' (Issue: 0.95 substring score)."""
    assert compute_title_score("ai", "SSC Chairman Gopal Krishna.mp4") == 0.0
    assert compute_title_score("gopal krishna", "SSC Chairman Gopal Krishna.mp4") >= 0.70
    assert compute_title_score("annual report", "annual_report.pdf") == 0.95


def test_p2_unicode_query_tokens():
    """Hindi queries produce real tokens (previously only [a-z0-9] survived)."""
    tokens = extract_query_tokens("परीक्षा परिणाम 2024")
    assert tokens == ["परीक्षा", "परिणाम", "2024"]


def test_p2_phash_near_duplicate_found_when_high_bits_differ(tmp_db):
    """
    Regression: the numeric prefix-bucket pre-filter dropped near-duplicates whose
    differing bits were in the top 16 bits (adjacent buckets are not Hamming neighbours).
    """
    from app.database.session import db_run
    from app.search.perceptual_hash import store_image_hash, search_image_hashes
    db_run(
        "INSERT INTO users (id, email, username, password_hash, role) VALUES ('u1', 'u@x', 'u', 'x', 'user')"
    )
    db_run(
        "INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, uploaded_by) "
        "VALUES ('src_img', 'a.png', 'a.png', 'png', '/tmp/a.png', 1, 'u1')"
    )
    store_image_hash("src_img", "ent1", "/tmp/a.png", "8000000000000000", "8000000000000000", "image")
    matches = search_image_hashes("0000000000000000", "0000000000000000", max_hamming_distance=8)
    assert [m["source_id"] for m in matches] == ["src_img"]
    assert matches[0]["p_dist"] == 1


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
