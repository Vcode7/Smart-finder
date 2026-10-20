"""
app/search/keyword_search.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SQLite FTS5 keyword search for document chunks and video transcripts.

Scoring: uses the real BM25-derived `rank` from FTS5.
  - FTS5 rank is negative BM25; more negative = stronger match.
  - rank_score = log1p(|rank|) / (1 + log1p(|rank|))  → (0, 1)
  - final score = 0.70 * rank_score + 0.30 * token_coverage
    (token_coverage is 1.0 for rows from the all-terms AND query)

Search strategy per function:
  1. AND query (all tokens required) — best precision
  2. OR query (any token) — fills remaining slots for recall
  3. LIKE fallback (FTS5 virtual table missing or corrupt) — last resort

Tokenization is Unicode-aware (constants.tokenize), so Hindi and other
non-Latin queries produce real FTS terms.
"""
import math
from typing import List, Dict, Any, Callable
from app.database.session import db_all
from app.search.constants import tokenize


def extract_query_tokens(query: str) -> List[str]:
    return tokenize(query)


def _rank_to_score(rank: float) -> float:
    """Convert FTS5 rank (negative BM25) to a [0, 1) relevance score.

    |rank| = 1.0 → 0.41, 5.0 → 0.64, 10.0 → 0.71
    """
    v = abs(float(rank))
    return round(min(0.99, math.log1p(v) / (1.0 + math.log1p(v))), 4)


def _coverage(text: str, tokens: List[str]) -> float:
    lower_text = (text or "").lower()
    matched = [t for t in tokens if t in lower_text]
    return len(matched) / len(tokens) if tokens else 0.0


def _fts_query(tokens: List[str], joiner: str) -> str:
    return f" {joiner} ".join(f'"{t}"*' for t in tokens)


def _run_fts(
    sql: str,
    tokens: List[str],
    limit: int,
    text_key: str,
    to_result: Callable[[Dict[str, Any], float], Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """AND query first, then OR query to fill the remaining slots. Raises if FTS is unusable."""
    results: List[Dict[str, Any]] = []
    seen = set()

    if len(tokens) > 1:
        for r in db_all(sql, (_fts_query(tokens, "AND"), limit)):
            score = round(0.70 * _rank_to_score(r["rank"]) + 0.30, 4)
            item = to_result(r, score)
            seen.add(item["id"])
            results.append(item)
        if len(results) >= limit:
            return results

    for r in db_all(sql, (_fts_query(tokens, "OR"), limit)):
        score = round(0.70 * _rank_to_score(r["rank"]) + 0.30 * _coverage(r[text_key], tokens), 4)
        item = to_result(r, score)
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        results.append(item)
        if len(results) >= limit:
            break

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def search_document_chunks(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    tokens = extract_query_tokens(query.strip() if query else "")
    if not tokens:
        return []

    def to_result(r: Dict[str, Any], score: float) -> Dict[str, Any]:
        return {
            "id": r["chunk_id"],
            "text": r["chunk_text"],
            "sourceId": r["source_id"],
            "docId": r["doc_id"],
            "type": "chunk",
            "score": score,
        }

    try:
        return _run_fts(
            """SELECT chunk_id, chunk_text, source_id, doc_id, rank
               FROM chunks_fts
               WHERE chunk_text MATCH ?
               ORDER BY rank
               LIMIT ?""",
            tokens, limit, "chunk_text", to_result,
        )
    except Exception as e:
        print(f"[KeywordSearch] FTS5 chunk search unavailable ({e}); using LIKE fallback")

    # Fallback: LIKE query on document_chunks (FTS5 unavailable)
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
        return [
            {
                "id": r["id"],
                "text": r["chunk_text"],
                "sourceId": r["source_id"],
                "docId": r["doc_id"],
                "pageNum": r.get("page_num", 1),
                "type": "chunk",
                "score": round(_coverage(r["chunk_text"], tokens) * 0.85, 4),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[KeywordSearch] Document search error: {e}")
        return []


def search_transcripts(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    tokens = extract_query_tokens(query.strip() if query else "")
    if not tokens:
        return []

    def to_result(r: Dict[str, Any], score: float) -> Dict[str, Any]:
        return {
            "id": r["transcript_id"],
            "text": r["text"],
            "sourceId": r["source_id"],
            "videoId": r["video_id"],
            "startTime": r["start_time"],
            "endTime": r["end_time"],
            "type": "transcript",
            "score": score,
        }

    try:
        return _run_fts(
            """SELECT transcript_id, text, video_id, source_id, start_time, end_time, rank
               FROM transcripts_fts
               WHERE text MATCH ?
               ORDER BY rank
               LIMIT ?""",
            tokens, limit, "text", to_result,
        )
    except Exception as e:
        print(f"[KeywordSearch] FTS5 transcript search unavailable ({e}); using LIKE fallback")

    # Fallback: LIKE query on video_transcripts
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
        return [
            {
                "id": r["id"],
                "text": r["text"],
                "sourceId": r["source_id"],
                "videoId": r["video_id"],
                "startTime": r["start_time"],
                "endTime": r["end_time"],
                "type": "transcript",
                "score": round(_coverage(r["text"], tokens) * 0.85, 4),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[KeywordSearch] Transcript search error: {e}")
        return []
