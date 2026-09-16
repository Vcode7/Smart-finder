"""
app/search/constants.py
~~~~~~~~~~~~~~~~~~~~~~~
Single source of truth for retrieval pipeline constants, stopwords,
embedding helpers, and shared score thresholds.
Import from here — never re-define in individual modules.
"""
from __future__ import annotations
import re
from typing import Set

# ── Embedding truncation ──────────────────────────────────────────────────────
# Maximum characters passed to embedding models before encoding.
# Approximates the Qwen3-Embedding-0.6B 8192-token window (~4 chars/token).
TEXT_EMBED_MAX_CHARS: int = 6000

# ── FAISS search thresholds ───────────────────────────────────────────────────
# Both search_by_text and search_by_multimodal_signals use these values.
# Defined once here so they can't drift between code paths (audit issue #8).
TEXT_MIN_SCORE:  float = 0.22
IMAGE_MIN_SCORE: float = 0.22
FACE_MIN_SCORE:  float = 0.48

# Composite score floor — results below this are discarded as noise
COMPOSITE_MIN_SCORE: float = 0.20

# Face match threshold for is_face_match flag
FACE_MATCH_THRESHOLD: float = 0.48

# ── File type sets ────────────────────────────────────────────────────────────
DOCUMENT_EXTENSIONS: Set[str] = {
    'pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx', 'xls',
    'json', 'xml', 'html', 'odt', 'rtf',
}
IMAGE_EXTENSIONS: Set[str] = {
    'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'heic', 'heif', 'tiff', 'tif',
}
VIDEO_EXTENSIONS: Set[str] = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
AUDIO_EXTENSIONS: Set[str] = {'mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac', 'opus'}

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
