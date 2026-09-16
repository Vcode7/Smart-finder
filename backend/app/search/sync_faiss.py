import sys
import json
from pathlib import Path
from typing import List
import numpy as np

from app.database.session import db_all, db_get
from app.search.faiss_index import get_faiss_manager
from app.search.model_pipeline import (
    get_text_embeddings_batch,
    get_image_embedding,
    TEXT_DIM,
    IMAGE_DIM,
    FACE_DIM
)

def sync_existing_data_to_faiss():
    """
    Syncs existing SQLite records into FAISS:
    - document_chunks -> FAISS text_index (1024-dim Qwen3)
    - video_transcripts -> FAISS text_index (1024-dim Qwen3)
    - video_frames & images -> FAISS image_index (1024-dim Jina CLIP)
    - face_embeddings -> FAISS face_index (512-dim InsightFace)
    """
    sys.stdout.reconfigure(encoding="utf-8")
    faiss_mgr = get_faiss_manager()
    print("[SyncFAISS] Initializing FAISS Vector sync...", flush=True)

    sources_map = {s["id"]: s["original_name"] for s in db_all("SELECT id, original_name FROM knowledge_sources")}

    # 1. Document chunks
    doc_chunks = db_all("SELECT id, source_id, doc_id, chunk_text, chunk_order, page_num FROM document_chunks")
    print(f"[SyncFAISS] Indexing {len(doc_chunks)} document chunks...", flush=True)

    batch_size = 16
    for i in range(0, len(doc_chunks), batch_size):
        batch = doc_chunks[i:i + batch_size]
        texts = [b["chunk_text"] for b in batch]
        embs = get_text_embeddings_batch(texts)
        for b, emb in zip(batch, embs):
            faiss_mgr.add_text_vector(
                source_id=b["source_id"],
                chunk_id=b["id"],
                vector=emb,
                metadata={
                    "type": "document_chunk",
                    "filename": sources_map.get(b["source_id"], "Document"),
                    "doc_id": b["doc_id"],
                    "page_num": b.get("page_num", 1),
                    "preview": b["chunk_text"][:150]
                }
            )
        print(f"[SyncFAISS] Chunks indexed: {min(i + batch_size, len(doc_chunks))}/{len(doc_chunks)}", flush=True)

    # 2. Video Transcripts
    transcripts = db_all("SELECT id, source_id, video_id, start_time, end_time, text FROM video_transcripts")
    print(f"[SyncFAISS] Indexing {len(transcripts)} video transcripts...", flush=True)
    for i in range(0, len(transcripts), batch_size):
        batch = transcripts[i:i + batch_size]
        texts = [b["text"] for b in batch]
        embs = get_text_embeddings_batch(texts)
        for b, emb in zip(batch, embs):
            faiss_mgr.add_text_vector(
                source_id=b["source_id"],
                chunk_id=b["id"],
                vector=emb,
                metadata={
                    "type": "video_transcript",
                    "filename": sources_map.get(b["source_id"], "Video"),
                    "start": b["start_time"],
                    "end": b["end_time"],
                    "preview": b["text"][:150]
                }
            )
        print(f"[SyncFAISS] Transcripts indexed: {min(i + batch_size, len(transcripts))}/{len(transcripts)}", flush=True)

    # 3. Video Frames
    frames = db_all("SELECT id, source_id, video_id, timestamp, frame_path FROM video_frames")
    print(f"[SyncFAISS] Indexing {len(frames)} video frames...", flush=True)
    for fr in frames:
        fp = fr.get("frame_path")
        emb = get_image_embedding(fp) if fp and Path(fp).exists() else None
        if emb:
            faiss_mgr.add_image_vector(
                source_id=fr["source_id"],
                entity_id=fr["id"],
                vector=emb,
                metadata={
                    "type": "video_frame",
                    "filename": sources_map.get(fr["source_id"], "Video"),
                    "timestamp": fr["timestamp"],
                    "frame_path": fp
                }
            )

    # 4. Standalone Images
    images = db_all("SELECT id, source_id FROM images")
    print(f"[SyncFAISS] Indexing {len(images)} images...", flush=True)
    for img in images:
        src = db_get("SELECT file_path FROM knowledge_sources WHERE id = ?", (img["source_id"],))
        if src and src.get("file_path") and Path(src["file_path"]).exists():
            emb = get_image_embedding(src["file_path"])
            faiss_mgr.add_image_vector(
                source_id=img["source_id"],
                entity_id=img["id"],
                vector=emb,
                metadata={
                    "type": "image",
                    "filename": sources_map.get(img["source_id"], "Image"),
                    "image_path": src["file_path"]
                }
            )

    # 5. Face embeddings
    face_rows = db_all("SELECT id, source_id, timestamp, bbox_json, embedding FROM face_embeddings")
    print(f"[SyncFAISS] Indexing {len(face_rows)} face records...", flush=True)
    for f in face_rows:
        blob = f.get("embedding")
        if blob:
            arr = np.frombuffer(blob, dtype=np.float32).tolist()
            if len(arr) == FACE_DIM:
                faiss_mgr.add_face_vector(
                    source_id=f["source_id"],
                    face_id=f["id"],
                    vector=arr,
                    metadata={
                        "type": "face",
                        "filename": sources_map.get(f["source_id"], "File"),
                        "timestamp": f.get("timestamp")
                    }
                )

    faiss_mgr.save_to_disk()
    stats = faiss_mgr.get_stats()
    print(f"[SyncFAISS] SUCCESS! FAISS Index Stats: {stats}", flush=True)
    return stats

if __name__ == "__main__":
    sync_existing_data_to_faiss()
