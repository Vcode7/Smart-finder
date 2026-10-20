"""
app/ingest/chunking.py
~~~~~~~~~~~~~~~~~~~~~~
Text units for retrieval.

* chunk_text: ~400-token chunks (character budget) with ~15% overlap, split on
  paragraph, line, sentence and finally word boundaries — never mid-word.
* transcript_windows: Whisper segments merged into ~40 s windows with 10 s overlap;
  single segments are too short to embed meaningfully.
* row_chunks: spreadsheet rows grouped into chunks with the header repeated, so a
  "column: value" match keeps its column names.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, Iterator, List, Sequence

MAX_CHARS = 1600      # ≈ 400 tokens of English text
OVERLAP_CHARS = 240   # ≈ 15%
MIN_CHARS = 12

# Sentence ends in Latin scripts and Devanagari (danda)
_SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")


def _split(text: str, max_chars: int) -> List[str]:
    """Recursively split text into pieces no longer than max_chars at natural boundaries."""
    if len(text) <= max_chars:
        return [text]
    for pattern in (r"\n\s*\n", r"\n", None, r"\s+"):
        parts = _SENTENCE_END.split(text) if pattern is None else re.split(pattern, text)
        parts = [p for p in parts if p and p.strip()]
        if len(parts) > 1:
            out: List[str] = []
            for p in parts:
                out.extend(_split(p, max_chars))
            return out
    # A single unbroken run longer than max_chars (e.g. a base64 blob)
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> List[str]:
    clean = (text or "").replace("\r\n", "\n").strip()
    if not clean:
        return []
    pieces = _split(clean, max_chars)
    chunks: List[str] = []
    current = ""
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        candidate = f"{current}\n{piece}" if current else piece
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            # Carry the tail of the previous chunk as overlap, starting at a word boundary
            tail = current[-overlap:] if overlap else ""
            if tail and " " in tail:
                tail = tail[tail.index(" ") + 1:]
            current = f"{tail}\n{piece}".strip() if tail and len(tail) + len(piece) + 1 <= max_chars else piece
        else:
            current = piece
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= MIN_CHARS]


def transcript_windows(
    segments: Sequence[Dict[str, object]],
    window: float = 40.0,
    overlap: float = 10.0,
    max_chars: int = MAX_CHARS,
) -> List[Dict[str, object]]:
    """Merge [{"start","end","text"}] segments into overlapping time windows."""
    segs = [s for s in segments if str(s.get("text", "")).strip()]
    if not segs:
        return []
    windows: List[Dict[str, object]] = []
    i = 0
    while i < len(segs):
        start = float(segs[i]["start"])
        texts: List[str] = []
        end = start
        j = i
        while j < len(segs) and (float(segs[j]["end"]) - start <= window or j == i):
            candidate = " ".join(texts + [str(segs[j]["text"]).strip()])
            if len(candidate) > max_chars and texts:
                break
            texts.append(str(segs[j]["text"]).strip())
            end = float(segs[j]["end"])
            j += 1
        windows.append({"ts_start": round(start, 2), "ts_end": round(end, 2), "text": " ".join(texts)})
        if j >= len(segs):
            break
        # Next window starts `overlap` seconds before this one ended (but always advances)
        next_i = j
        while next_i - 1 > i and float(segs[next_i - 1]["start"]) >= end - overlap:
            next_i -= 1
        i = max(next_i, i + 1)
    return windows


def iter_row_chunks(
    header: Sequence[object], rows: Iterable[Sequence[object]], max_chars: int = MAX_CHARS
) -> Iterator[str]:
    """Spreadsheet rows as chunks, each starting with the header row (streams any number of rows)."""
    head = " | ".join(str(h) for h in header if h is not None and str(h).strip())
    current: List[str] = []
    size = len(head)
    for row in rows:
        line = " | ".join(str(v) for v in row if v is not None and str(v).strip())
        if not line:
            continue
        if current and size + len(line) + 1 > max_chars:
            yield _join_rows(head, current)
            current, size = [], len(head)
        current.append(line[:max_chars])
        size += len(line) + 1
    if current:
        yield _join_rows(head, current)


def _join_rows(head: str, lines: List[str]) -> str:
    return "\n".join([head] + lines) if head else "\n".join(lines)


def row_chunks(header: Sequence[object], rows: Sequence[Sequence[object]], max_chars: int = MAX_CHARS) -> List[str]:
    return list(iter_row_chunks(header, rows, max_chars))
