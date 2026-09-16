"""
backend/reindex_text.py
~~~~~~~~~~~~~~~~~~~~~~~~
OFFLINE BACKFILL SCRIPT — run once after deploying the audit remediation.

Re-embeds ALL document_chunks and video_transcripts using the real Qwen3-Embedding-0.6B
model. Wipes the FAISS text index first to eliminate any stale fallback vectors that
were silently indexed before the Optional-embedding fix was deployed.

Mirrors the same pattern used by reindex_media.py for image vectors.

Usage (from backend/ directory with venv active):
  python reindex_text.py

Requirements:
  - Qwen3-Embedding-0.6B must be loadable (will raise if not)
  - DB must be accessible at the path in .env
  - ~2GB RAM for the model; GPU optional but recommended
"""
import os
import sys

# Fix OpenMP conflict on Windows
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import faiss
import numpy as np

from app.database.session import db_all, db_run
from app.search.faiss_index import get_faiss_manager
from app.search.model_pipeline import (
    _get_qwen_model,
    get_text_embeddings_batch,
    TEXT_DIM,
)
from app.search.embeddings import float_array_to_blob
from app.search.constants import TEXT_EMBED_MAX_CHARS


def reindex_all_text():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 70)
    print("STARTING COMPLETE TEXT RE-INDEXING (REAL Qwen3-Embedding-0.6B)")
    print("=" * 70)

    # 1. Verify model loads — abort immediately if it doesn't
    print("[1/5] Verifying Qwen3-Embedding-0.6B model...")
    qwen_model = _get_qwen_model()
    if qwen_model is None:
        raise RuntimeError(
            "CRITICAL: Failed to load Qwen3-Embedding-0.6B. "
            "Halting re-indexing — text vectors would be missing, not fallback."
        )
    print("[1/5] Qwen3-Embedding-0.6B model verified and ready.")

    # 2. Wipe FAISS text index (leaves image + face untouched)
    print("[2/5] Clearing FAISS text index (image + face indexes untouched)...")
    faiss_mgr = get_faiss_manager()
    faiss_mgr.text_index = faiss.IndexFlatIP(TEXT_DIM)
    faiss_mgr.text_meta = []
    print("[2/5] FAISS text index reset. Old (possibly stale) text vectors purged.")

    # 3. Load all document chunks
    print("[3/5] Loading document chunks from SQLite...")
    doc_chunks = db_all(
        "SELECT id, source_id, doc_id, chunk_text, chunk_order, page_num FROM document_chunks"
    )
    transcripts = db_all(
        "SELECT id, source_id, video_id, start_time, end_time, text FROM video_transcripts"
    )
    sources_map = {
        s["id"]: s["original_name"]
        for s in db_all("SELECT id, original_name FROM knowledge_sources")
    }
    print(f"[3/5] Found {len(doc_chunks)} document chunks and {len(transcripts)} transcript segments.")

    BATCH = 16
    total_embedded = 0
    total_skipped = 0

    # 4a. Re-embed document chunks
    print(f"[4/5] Re-embedding {len(doc_chunks)} document chunks in batches of {BATCH}...")
    for i in range(0, len(doc_chunks), BATCH):
        batch = doc_chunks[i : i + BATCH]
        texts = [b["chunk_text"][:TEXT_EMBED_MAX_CHARS] for b in batch]
        embs = get_text_embeddings_batch(texts)

        for b, emb in zip(batch, embs):
            if emb is None:
                print(f"  [WARN] Embedding returned None for chunk {b['id']} — marking needs_reembed")
                db_run(
                    "UPDATE document_chunks SET needs_reembed = 1 WHERE id = ?",
                    (b["id"],)
                )
                total_skipped += 1
                continue

            # Update SQLite embedding blob
            db_run(
                "UPDATE document_chunks SET embedding = ?, needs_reembed = 0 WHERE id = ?",
                (float_array_to_blob(emb), b["id"])
            )

            faiss_mgr.add_text_vector(
                source_id=b["source_id"],
                chunk_id=b["id"],
                vector=emb,
                metadata={
                    "type": "document_chunk",
                    "filename": sources_map.get(b["source_id"], "Document"),
                    "doc_id": b["doc_id"],
                    "page_num": b.get("page_num", 1),
                    "preview": b["chunk_text"][:150],
                },
            )
            total_embedded += 1

        if (i // BATCH + 1) % 10 == 0 or i + BATCH >= len(doc_chunks):
            print(f"  Chunks: {min(i + BATCH, len(doc_chunks))}/{len(doc_chunks)} (embedded={total_embedded}, skipped={total_skipped})")

    # 4b. Re-embed transcript segments
    print(f"[4/5] Re-embedding {len(transcripts)} transcript segments...")
    for i in range(0, len(transcripts), BATCH):
        batch = transcripts[i : i + BATCH]
        texts = [b["text"][:TEXT_EMBED_MAX_CHARS] for b in batch]
        embs = get_text_embeddings_batch(texts)

        for b, emb in zip(batch, embs):
            if emb is None:
                print(f"  [WARN] Embedding returned None for transcript {b['id']} — marking needs_reembed")
                db_run(
                    "UPDATE video_transcripts SET needs_reembed = 1 WHERE id = ?",
                    (b["id"],)
                )
                total_skipped += 1
                continue

            db_run(
                "UPDATE video_transcripts SET embedding = ?, needs_reembed = 0 WHERE id = ?",
                (float_array_to_blob(emb), b["id"])
            )

            faiss_mgr.add_text_vector(
                source_id=b["source_id"],
                chunk_id=b["id"],
                vector=emb,
                metadata={
                    "type": "video_transcript",
                    "filename": sources_map.get(b["source_id"], "Video"),
                    "start": b["start_time"],
                    "end": b["end_time"],
                    "preview": b["text"][:150],
                },
            )
            total_embedded += 1

        if (i // BATCH + 1) % 10 == 0 or i + BATCH >= len(transcripts):
            print(f"  Transcripts: {min(i + BATCH, len(transcripts))}/{len(transcripts)}")

    # 5. Persist and report
    print("[5/5] Persisting new FAISS text index to disk...")
    faiss_mgr.save_to_disk()

    stats = faiss_mgr.get_stats()
    print()
    print("=" * 70)
    print("RE-INDEXING COMPLETE")
    print(f"  Total text vectors in FAISS : {stats['textVectors']}")
    print(f"  Chunks embedded             : {total_embedded}")
    print(f"  Chunks skipped (needs_reembed=1): {total_skipped}")
    print("=" * 70)
    if total_skipped > 0:
        print(
            f"WARNING: {total_skipped} chunk(s) could not be embedded.\n"
            "Re-run this script after ensuring the Qwen3 model is fully loaded."
        )
    return stats


if __name__ == "__main__":
    reindex_all_text()
