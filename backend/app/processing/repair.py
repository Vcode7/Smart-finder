"""
app/processing/repair.py
~~~~~~~~~~~~~~~~~~~~~~~~
Background repair for rows indexed while a model or FTS was unavailable.

Ingestion marks such rows with needs_reembed = 1 (no embedding) or
fts_synced = 0 (FTS insert failed). This pass re-embeds / re-inserts them so
they become searchable without a manual reindex. Safe to run repeatedly.
"""
from typing import Dict, List

from app.database.session import db_all, get_db_context
from app.search.constants import AUDIO_EXTENSIONS, preview_text

_BATCH = 64


def _embed_batch(texts: List[str]):
    from app.search.model_pipeline import get_text_embeddings_batch
    return get_text_embeddings_batch(texts)


def repair_index() -> Dict[str, int]:
    from app.processing.processors import float_array_to_blob
    from app.search.faiss_index import get_faiss_manager

    stats = {"chunks_embedded": 0, "transcripts_embedded": 0, "fts_repaired": 0}
    faiss_mgr = get_faiss_manager()
    names = {r["id"]: (r["original_name"], (r["file_type"] or "").lower())
             for r in db_all("SELECT id, original_name, file_type FROM knowledge_sources")}

    # 1. Document chunks without embeddings
    while True:
        rows = db_all(
            "SELECT id, doc_id, source_id, chunk_text, chunk_order, page_num FROM document_chunks "
            "WHERE needs_reembed = 1 LIMIT ?", (_BATCH,)
        )
        if not rows:
            break
        embs = _embed_batch([r["chunk_text"] for r in rows])
        if all(e is None for e in embs):
            break  # model still unavailable; try again on a later run
        with get_db_context() as conn:
            for r, emb in zip(rows, embs):
                if emb is None:
                    continue
                conn.execute(
                    "UPDATE document_chunks SET embedding = ?, needs_reembed = 0 WHERE id = ?",
                    (float_array_to_blob(emb), r["id"])
                )
                faiss_mgr.add_text_vector(
                    source_id=r["source_id"],
                    chunk_id=r["id"],
                    vector=emb,
                    metadata={
                        "type": "document_chunk",
                        "filename": names.get(r["source_id"], ("Document", ""))[0],
                        "doc_id": r["doc_id"],
                        "chunk_order": r["chunk_order"],
                        "page_num": r["page_num"],
                        "preview": preview_text(r["chunk_text"]),
                    },
                )
                stats["chunks_embedded"] += 1
            conn.commit()

    # 2. Transcript segments without embeddings
    while True:
        rows = db_all(
            "SELECT id, video_id, source_id, start_time, end_time, text FROM video_transcripts "
            "WHERE needs_reembed = 1 LIMIT ?", (_BATCH,)
        )
        if not rows:
            break
        embs = _embed_batch([r["text"] for r in rows])
        if all(e is None for e in embs):
            break
        with get_db_context() as conn:
            for r, emb in zip(rows, embs):
                if emb is None:
                    continue
                conn.execute(
                    "UPDATE video_transcripts SET embedding = ?, needs_reembed = 0 WHERE id = ?",
                    (float_array_to_blob(emb), r["id"])
                )
                fname, ftype = names.get(r["source_id"], ("Media", ""))
                faiss_mgr.add_text_vector(
                    source_id=r["source_id"],
                    chunk_id=r["id"],
                    vector=emb,
                    metadata={
                        "type": "audio_transcript" if ftype in AUDIO_EXTENSIONS else "video_transcript",
                        "filename": fname,
                        "video_id": r["video_id"],
                        "start": r["start_time"],
                        "end": r["end_time"],
                        "preview": r["text"][:150],
                    },
                )
                stats["transcripts_embedded"] += 1
            conn.commit()

    # 3. Rows whose FTS insert failed
    with get_db_context() as conn:
        for r in conn.execute(
            "SELECT id, chunk_text, source_id, doc_id FROM document_chunks WHERE fts_synced = 0"
        ).fetchall():
            conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (r["id"],))
            conn.execute(
                "INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id) VALUES (?, ?, ?, ?)",
                (r["chunk_text"], r["id"], r["source_id"], r["doc_id"])
            )
            conn.execute("UPDATE document_chunks SET fts_synced = 1 WHERE id = ?", (r["id"],))
            stats["fts_repaired"] += 1
        for r in conn.execute(
            "SELECT id, video_id, source_id, start_time, end_time, text FROM video_transcripts WHERE fts_synced = 0"
        ).fetchall():
            conn.execute("DELETE FROM transcripts_fts WHERE transcript_id = ?", (r["id"],))
            conn.execute(
                "INSERT INTO transcripts_fts (text, transcript_id, video_id, source_id, start_time, end_time) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["text"], r["id"], r["video_id"], r["source_id"], r["start_time"], r["end_time"])
            )
            conn.execute("UPDATE video_transcripts SET fts_synced = 1 WHERE id = ?", (r["id"],))
            stats["fts_repaired"] += 1
        conn.commit()

    if any(stats.values()):
        faiss_mgr.save_to_disk()
        print(f"[Repair] Index repair complete: {stats}")
    return stats
