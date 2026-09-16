"""
app/search/keyword_search.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SQLite FTS5 keyword search for document chunks and video transcripts.

Scoring: Uses real BM25-derived `rank` from FTS5 (NOT a fabricated position score).
  - FTS5 rank is negative; lower (more negative) = less relevant.
  - rank_score = 1 / (1 + abs(rank))  → maps to (0, 1], higher is better.
  - OR-path also blends token_ratio: 0.70 * rank_score + 0.30 * token_ratio

Search strategy per function:
  1. AND query (all tokens required) — best precision
  2. OR query (any token, scored by token coverage) — wider recall
  3. LIKE fallback (FTS5 virtual table missing or corrupt) — last resort
"""
import re
from typing import List, Dict, Any
from app.database.session import db_all
from app.search.constants import STOPWORDS


def extract_query_tokens(query: str) -> List[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", query.lower())
    return [w for w in cleaned.split() if len(w) >= 2 and w not in STOPWORDS]


def _rank_to_score(rank: float) -> float:
    """Convert FTS5 rank (negative BM25) to a [0, 1) relevance score."""
    return round(1.0 / (1.0 + abs(float(rank))), 4)


def search_document_chunks(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    clean_q = query.strip()
    if not clean_q:
        return []

    tokens = extract_query_tokens(clean_q)
    if not tokens:
        return []

    # 1. Strict FTS5 AND query (all tokens required)
    if len(tokens) > 1:
        strict_fts = " AND ".join([f'"{t}"*' for t in tokens])
        try:
            rows = db_all(
                """SELECT chunk_id, chunk_text, source_id, doc_id, rank
                   FROM chunks_fts
                   WHERE chunk_text MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (strict_fts, limit)
            )
            if rows:
                return [
                    {
                        "id": r["chunk_id"],
                        "text": r["chunk_text"],
                        "sourceId": r["source_id"],
                        "docId": r["doc_id"],
                        "type": "chunk",
                        "score": _rank_to_score(r["rank"]),
                    }
                    for r in rows
                ]
        except Exception:
            pass

    # 2. Standard FTS5 OR query (blend rank + token coverage)
    try:
        or_fts = " OR ".join([f'"{t}"*' for t in tokens])
        rows = db_all(
            """SELECT chunk_id, chunk_text, source_id, doc_id, rank
               FROM chunks_fts
               WHERE chunk_text MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (or_fts, limit)
        )
        if rows:
            results = []
            for r in rows:
                lower_text = r["chunk_text"].lower()
                matched = [t for t in tokens if t in lower_text]
                token_ratio = len(matched) / len(tokens)
                rank_score = _rank_to_score(r["rank"])
                score = round(0.70 * rank_score + 0.30 * token_ratio, 4)
                results.append({
                    "id": r["chunk_id"],
                    "text": r["chunk_text"],
                    "sourceId": r["source_id"],
                    "docId": r["doc_id"],
                    "type": "chunk",
                    "score": score,
                })
            return results
    except Exception:
        pass

    # 3. Fallback: LIKE query on document_chunks (FTS5 unavailable)
    try:
        like_clauses = " AND ".join(["chunk_text LIKE ?"] * len(tokens))
        params = tuple([f"%{t}%" for t in tokens] + [limit])
        rows = db_all(
            f"""SELECT id, chunk_text, source_id, doc_id, page_num
                FROM document_chunks
                WHERE {like_clauses}
                LIMIT ?""",
            params
        )
        if not rows:
            or_clauses = " OR ".join(["chunk_text LIKE ?"] * len(tokens))
            rows = db_all(
                f"""SELECT id, chunk_text, source_id, doc_id, page_num
                    FROM document_chunks
                    WHERE {or_clauses}
                    LIMIT ?""",
                params
            )
        results = []
        for r in rows:
            lower_text = r["chunk_text"].lower()
            matched = [t for t in tokens if t in lower_text]
            token_ratio = len(matched) / len(tokens)
            results.append({
                "id": r["id"],
                "text": r["chunk_text"],
                "sourceId": r["source_id"],
                "docId": r["doc_id"],
                "pageNum": r.get("page_num", 1),
                "type": "chunk",
                "score": round(token_ratio * 0.85, 4),
            })
        return results
    except Exception as e:
        print(f"[KeywordSearch] Document search error: {e}")
        return []


def search_transcripts(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    clean_q = query.strip()
    if not clean_q:
        return []

    tokens = extract_query_tokens(clean_q)
    if not tokens:
        return []

    # 1. Strict FTS5 AND query
    if len(tokens) > 1:
        strict_fts = " AND ".join([f'"{t}"*' for t in tokens])
        try:
            rows = db_all(
                """SELECT transcript_id, text, video_id, source_id, start_time, end_time, rank
                   FROM transcripts_fts
                   WHERE text MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (strict_fts, limit)
            )
            if rows:
                return [
                    {
                        "id": r["transcript_id"],
                        "text": r["text"],
                        "sourceId": r["source_id"],
                        "videoId": r["video_id"],
                        "startTime": r["start_time"],
                        "endTime": r["end_time"],
                        "type": "transcript",
                        "score": _rank_to_score(r["rank"]),
                    }
                    for r in rows
                ]
        except Exception:
            pass

    # 2. Standard FTS5 OR query
    try:
        or_fts = " OR ".join([f'"{t}"*' for t in tokens])
        rows = db_all(
            """SELECT transcript_id, text, video_id, source_id, start_time, end_time, rank
               FROM transcripts_fts
               WHERE text MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (or_fts, limit)
        )
        if rows:
            results = []
            for r in rows:
                lower_text = r["text"].lower()
                matched = [t for t in tokens if t in lower_text]
                token_ratio = len(matched) / len(tokens)
                rank_score = _rank_to_score(r["rank"])
                score = round(0.70 * rank_score + 0.30 * token_ratio, 4)
                results.append({
                    "id": r["transcript_id"],
                    "text": r["text"],
                    "sourceId": r["source_id"],
                    "videoId": r["video_id"],
                    "startTime": r["start_time"],
                    "endTime": r["end_time"],
                    "type": "transcript",
                    "score": score,
                })
            return results
    except Exception:
        pass

    # 3. Fallback: LIKE query on video_transcripts
    try:
        like_clauses = " AND ".join(["text LIKE ?"] * len(tokens))
        params = tuple([f"%{t}%" for t in tokens] + [limit])
        rows = db_all(
            f"""SELECT id, text, video_id, source_id, start_time, end_time
                FROM video_transcripts
                WHERE {like_clauses}
                LIMIT ?""",
            params
        )
        if not rows:
            or_clauses = " OR ".join(["text LIKE ?"] * len(tokens))
            rows = db_all(
                f"""SELECT id, text, video_id, source_id, start_time, end_time
                    FROM video_transcripts
                    WHERE {or_clauses}
                    LIMIT ?""",
                params
            )
        results = []
        for r in rows:
            lower_text = r["text"].lower()
            matched = [t for t in tokens if t in lower_text]
            token_ratio = len(matched) / len(tokens)
            results.append({
                "id": r["id"],
                "text": r["text"],
                "sourceId": r["source_id"],
                "videoId": r["video_id"],
                "startTime": r["start_time"],
                "endTime": r["end_time"],
                "type": "transcript",
                "score": round(token_ratio * 0.85, 4),
            })
        return results
    except Exception as e:
        print(f"[KeywordSearch] Transcript search error: {e}")
        return []
