import re
from typing import List, Dict, Any, Set
from app.database.session import db_all

STOPWORDS: Set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "and", "or", "but", "if", "in", "on",
    "at", "to", "for", "with", "about", "against", "between", "into", "through", "during",
    "before", "after", "above", "below", "from", "up", "down", "of", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just",
    "don", "should", "now", "this", "that", "these", "those"
}

def extract_query_tokens(query: str) -> List[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", query.lower())
    tokens = [w for w in cleaned.split() if len(w) >= 2 and w not in STOPWORDS]
    return tokens

def search_document_chunks(query: str, limit: int = 20) -> List[Dict[str, Any]]:
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
                        "score": round(0.75 + 0.25 * max(0.0, 1.0 - (i / max(limit, 1))), 4)
                    }
                    for i, r in enumerate(rows)
                ]
        except Exception:
            pass

    # 2. Standard FTS5 OR query
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
            for i, r in enumerate(rows):
                lower_text = r["chunk_text"].lower()
                matched = [t for t in tokens if t in lower_text]
                token_ratio = len(matched) / len(tokens)
                rank_decay = max(0.0, 1.0 - (i / max(limit, 1)))
                score = round((token_ratio * 0.75) + (rank_decay * 0.25), 4)
                results.append({
                    "id": r["chunk_id"],
                    "text": r["chunk_text"],
                    "sourceId": r["source_id"],
                    "docId": r["doc_id"],
                    "type": "chunk",
                    "score": score
                })
            return results
    except Exception:
        pass

    # 3. Fallback: LIKE query on document_chunks
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
                "score": round(token_ratio * 0.85, 4)
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
                        "score": round(0.75 + 0.25 * max(0.0, 1.0 - (i / max(limit, 1))), 4)
                    }
                    for i, r in enumerate(rows)
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
            for i, r in enumerate(rows):
                lower_text = r["text"].lower()
                matched = [t for t in tokens if t in lower_text]
                token_ratio = len(matched) / len(tokens)
                rank_decay = max(0.0, 1.0 - (i / max(limit, 1)))
                score = round((token_ratio * 0.75) + (rank_decay * 0.25), 4)
                results.append({
                    "id": r["transcript_id"],
                    "text": r["text"],
                    "sourceId": r["source_id"],
                    "videoId": r["video_id"],
                    "startTime": r["start_time"],
                    "endTime": r["end_time"],
                    "type": "transcript",
                    "score": score
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
                "score": round(token_ratio * 0.85, 4)
            })
        return results
    except Exception as e:
        print(f"[KeywordSearch] Transcript search error: {e}")
        return []
