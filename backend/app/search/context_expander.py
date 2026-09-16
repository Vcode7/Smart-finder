from typing import Optional, Dict, Any
from app.database.session import db_get, db_all

def expand_document_chunk(chunk_id: str, score: float = 0.0) -> Optional[Dict[str, Any]]:
    chunk = db_get(
        "SELECT id, section_id, doc_id, source_id, chunk_text, page_num FROM document_chunks WHERE id = ?",
        (chunk_id,)
    )
    if not chunk:
        return None

    doc = db_get(
        "SELECT id, source_id, title, page_count FROM documents WHERE id = ?",
        (chunk["doc_id"],)
    )

    section = None
    if chunk.get("section_id"):
        section = db_get(
            "SELECT id, section_title, section_text FROM document_sections WHERE id = ?",
            (chunk["section_id"],)
        )

    src = db_get(
        "SELECT original_name FROM knowledge_sources WHERE id = ?",
        (chunk["source_id"],)
    )

    source_name = src.get("original_name") if src else "Document"
    full_doc_title = doc.get("title") if doc else source_name
    section_title = section.get("section_title") if section else "Overview"
    section_text = section.get("section_text") if section else chunk["chunk_text"]

    return {
        "chunkId": chunk["id"],
        "sourceId": chunk["source_id"],
        "docId": chunk["doc_id"],
        "sectionId": chunk.get("section_id"),
        "sourceName": source_name,
        "fullDocTitle": full_doc_title,
        "sectionTitle": section_title,
        "sectionText": section_text,
        "chunkText": chunk["chunk_text"],
        "pageNum": chunk.get("page_num", 1),
        "score": score,
    }

def expand_transcript_segment(transcript_id: str, score: float = 0.0) -> Optional[Dict[str, Any]]:
    segment = db_get(
        "SELECT id, video_id, source_id, start_time, end_time, text FROM video_transcripts WHERE id = ?",
        (transcript_id,)
    )
    if not segment:
        return None

    window_start = max(0.0, segment["start_time"] - 25.0)
    window_end = segment["end_time"] + 25.0

    surrounding = db_all(
        """SELECT text FROM video_transcripts
           WHERE video_id = ? AND start_time >= ? AND end_time <= ?
           ORDER BY start_time ASC""",
        (segment["video_id"], window_start, window_end)
    )

    combined_text = " ".join([r["text"] for r in surrounding]) if surrounding else segment["text"]

    return {
        "transcriptId": segment["id"],
        "sourceId": segment["source_id"],
        "videoId": segment["video_id"],
        "startTime": segment["start_time"],
        "endTime": segment["end_time"],
        "segmentText": segment["text"],
        "transcriptText": combined_text,
        "score": score,
    }
