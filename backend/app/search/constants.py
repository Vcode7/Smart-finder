"""
app/search/constants.py
~~~~~~~~~~~~~~~~~~~~~~~
Single source of truth for retrieval pipeline constants, stopwords,
embedding helpers, and shared score thresholds.
Import from here — never re-define in individual modules.
"""
from __future__ import annotations
import re
from typing import List, Set

try:
    import regex as _regex
    # Letters + combining marks + numbers: keeps Devanagari words (whose vowel
    # signs are combining marks) intact, matching SQLite FTS5's unicode61 tokens.
    _TOKEN_RE = _regex.compile(r"[\p{L}\p{M}\p{N}]+")
except ImportError:  # pragma: no cover - regex ships with transformers
    _TOKEN_RE = re.compile(r"\w+")

# ── Embedding truncation ──────────────────────────────────────────────────────
# Maximum characters passed to embedding models before encoding.
# Approximates the Qwen3-Embedding-0.6B 8192-token window (~4 chars/token).
TEXT_EMBED_MAX_CHARS: int = 6000

# ── Image models ──────────────────────────────────────────────────────────────
# Each library records which model made its image ("clip" space) vectors; when this
# changes, they are dropped and re-made by the "images" enrichment pass.
IMAGE_EMBED_MODEL: str = "Qwen/Qwen3-VL-Embedding-2B"
VISUAL_RERANK_MODEL: str = "Qwen/Qwen3-VL-Reranker-2B"

# ── FAISS search thresholds ───────────────────────────────────────────────────
# Both search_by_text and search_by_multimodal_signals use these values.
# Defined once here so they can't drift between code paths (audit issue #8).
TEXT_MIN_SCORE:  float = 0.22
IMAGE_MIN_SCORE: float = 0.22
# Face candidates below FACE_MATCH_THRESHOLD only contribute a blended similarity;
# at or above it the face counts as the same person (is_face_match).
FACE_MIN_SCORE:  float = 0.40

# Composite score floor — results below this are discarded as noise
COMPOSITE_MIN_SCORE: float = 0.20

# Face match threshold for is_face_match flag (must stay above FACE_MIN_SCORE)
FACE_MATCH_THRESHOLD: float = 0.48

# ── File type sets ────────────────────────────────────────────────────────────
# The only definition of supported types: ingestion routing, folder sync,
# thumbnails and the frontend upload picker (GET /api/knowledge/supported-types)
# all read these sets.
PLAIN_TEXT_EXTENSIONS: Set[str] = {'txt', 'md', 'json', 'xml', 'html', 'htm', 'log', 'tsv'}
# Legacy/binary office formats converted through LibreOffice when it is installed.
LIBREOFFICE_EXTENSIONS: Set[str] = {'doc', 'odt', 'rtf'}
DOCUMENT_EXTENSIONS: Set[str] = {
    'pdf', 'docx', 'pptx', 'csv', 'xlsx', 'xls',
} | PLAIN_TEXT_EXTENSIONS | LIBREOFFICE_EXTENSIONS
IMAGE_EXTENSIONS: Set[str] = {
    'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'heic', 'heif', 'tiff', 'tif',
}
VIDEO_EXTENSIONS: Set[str] = {'mp4', 'avi', 'mov', 'mkv', 'webm', 'm4v', 'wmv', 'mpg', 'mpeg', '3gp'}
AUDIO_EXTENSIONS: Set[str] = {'mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac', 'opus', 'wma'}
SUPPORTED_EXTENSIONS: Set[str] = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


def classify_extension(ext: str) -> str:
    """Return 'document', 'image', 'video', 'audio', or 'unsupported' for a file extension."""
    e = (ext or "").lower().lstrip(".")
    if e in DOCUMENT_EXTENSIONS:
        return "document"
    if e in IMAGE_EXTENSIONS:
        return "image"
    if e in VIDEO_EXTENSIONS:
        return "video"
    if e in AUDIO_EXTENSIONS:
        return "audio"
    return "unsupported"

# ── Stopwords ─────────────────────────────────────────────────────────────────
# Shared between keyword_search.py and multimodal_retrieval.py.
# Note: intentionally does NOT include "video", "image", "document" —
# those are meaningful content words in user queries.
STOPWORDS: Set[str] = {
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'and', 'or', 'but',
    'if', 'in', 'on', 'at', 'to', 'for', 'with', 'about', 'against',
    'between', 'into', 'through', 'during', 'before', 'after', 'above',
    'below', 'from', 'up', 'down', 'of', 'off', 'over', 'under', 'again',
    'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why',
    'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other',
    'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
    'than', 'too', 'very', 'can', 'will', 'just', 'don', 'should', 'now',
    'this', 'that', 'these', 'those',
}


def tokenize(text: str, min_len: int = 2, drop_stopwords: bool = True) -> List[str]:
    """Unicode-aware query tokenizer (lower-cased words in any script)."""
    tokens = _TOKEN_RE.findall((text or "").lower())
    return [
        t for t in tokens
        if len(t) >= min_len and not (drop_stopwords and t in STOPWORDS)
    ]

# ── Chunk enrichment helpers ──────────────────────────────────────────────────
def build_enriched_text(section_title: str, chunk: str) -> str:
    """
    Prepend section title to chunk text in the canonical format used
    for both SQLite storage and FAISS embedding.
    Always call this — never inline the format string.
    """
    if section_title:
        return f"[{section_title}] {chunk}"
    return chunk


def preview_text(enriched: str, length: int = 150) -> str:
    """
    Strip the [section title] prefix from an enriched chunk and return
    at most `length` characters — suitable for the FAISS metadata preview field
    and user-visible snippets.
    """
    stripped = re.sub(r"^\[.*?\]\s*", "", enriched)
    return stripped[:length]
