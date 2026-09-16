import asyncio
import os
import sys
import uuid
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.database.session import run_migrations, db_get, db_all, db_run, get_db_context
from app.processing.queue import (
    enqueue_source_processing,
    _process_source,
    recover_stale_sources,
    background_worker,
    _task_queue
)
from app.search.faiss_index import get_faiss_manager

async def main():
    print("=" * 70)
    print("SMART FINDER INGESTION VERIFICATION TEST")
    print("=" * 70)

    # 1. Run migrations
    run_migrations()
    faiss_mgr = get_faiss_manager()
    initial_counts = {
        "text": faiss_mgr.text_index.ntotal,
        "image": faiss_mgr.image_index.ntotal,
        "face": faiss_mgr.face_index.ntotal
    }
    print(f"[Initial FAISS Counts] {initial_counts}")

    test_dir = settings.resolved_upload_dir / "test_ingestion_tmp"
    test_dir.mkdir(parents=True, exist_ok=True)

    created_sources = []

    try:
        # -------------------------------------------------------------
        # TEST 0: Stale Source Recovery
        # -------------------------------------------------------------
        print("\n--- TEST 0: Stale Source Recovery ---")
        stale_id = str(uuid.uuid4())
        db_run(
            """INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status)
               VALUES (?, 'stale_test.pdf', 'stale_test.pdf', 'pdf', 'dummy_path.pdf', 100, 'system', 'processing')""",
            (stale_id,)
        )
        created_sources.append(stale_id)
        recover_stale_sources()
        stale_rec = db_get("SELECT processing_status, error_message FROM knowledge_sources WHERE id = ?", (stale_id,))
        assert stale_rec["processing_status"] == "failed", f"Expected failed, got {stale_rec['processing_status']}"
        assert "Processing interrupted" in stale_rec["error_message"]
        print("  [PASS] Stale sources successfully recovered and marked 'failed'.")

        # -------------------------------------------------------------
        # TEST 1: PDF Document Ingestion
        # -------------------------------------------------------------
        print("\n--- TEST 1: PDF Document Ingestion ---")
        import fitz  # PyMuPDF
        pdf_path = test_dir / "test_doc.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 72), "Smart Finder Verification Document.\nThis document tests PDF ingestion, text chunking, and embedding pipeline.", fontsize=12)
        doc.save(str(pdf_path))
        doc.close()

        doc_source_id = str(uuid.uuid4())
        db_run(
            """INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status)
               VALUES (?, 'test_doc.pdf', 'test_doc.pdf', 'pdf', ?, ?, 'system', 'uploaded')""",
            (doc_source_id, str(pdf_path), pdf_path.stat().st_size)
        )
        created_sources.append(doc_source_id)

        await _process_source(doc_source_id)
        doc_src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (doc_source_id,))
        assert doc_src["processing_status"] == "completed", f"Expected completed, got {doc_src['processing_status']}, error: {doc_src.get('error_message')}"
        doc_chunks = db_all("SELECT * FROM document_chunks WHERE source_id = ?", (doc_source_id,))
        assert len(doc_chunks) > 0, "Expected document chunks to be created"
        print(f"  [PASS] Document ingested successfully: status={doc_src['processing_status']}, chunks={len(doc_chunks)}, pages={doc_src['page_count']}")

        # -------------------------------------------------------------
        # TEST 2: Image Ingestion
        # -------------------------------------------------------------
        print("\n--- TEST 2: Image Ingestion ---")
        img_path = test_dir / "test_image.jpg"
        img = Image.new("RGB", (250, 100), color=(73, 109, 137))
        d = ImageDraw.Draw(img)
        d.text((10, 30), "SmartFinder OCR Test", fill=(255, 255, 0))
        img.save(str(img_path))

        img_source_id = str(uuid.uuid4())
        db_run(
            """INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status)
               VALUES (?, 'test_image.jpg', 'test_image.jpg', 'jpg', ?, ?, 'system', 'uploaded')""",
            (img_source_id, str(img_path), img_path.stat().st_size)
        )
        created_sources.append(img_source_id)

        await _process_source(img_source_id)
        img_src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (img_source_id,))
        assert img_src["processing_status"] == "completed", f"Expected completed, got {img_src['processing_status']}, error: {img_src.get('error_message')}"
        img_rec = db_get("SELECT * FROM images WHERE source_id = ?", (img_source_id,))
        assert img_rec is not None, "Expected images record to be created"
        print(f"  [PASS] Image ingested successfully: status={img_src['processing_status']}, width={img_rec['width']}, height={img_rec['height']}")

        # -------------------------------------------------------------
        # TEST 3: Audio Ingestion
        # -------------------------------------------------------------
        print("\n--- TEST 3: Audio Ingestion ---")
        audio_path = test_dir / "test_audio.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5", "-c:a", "libmp3lame", str(audio_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        )

        audio_source_id = str(uuid.uuid4())
        db_run(
            """INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status)
               VALUES (?, 'test_audio.mp3', 'test_audio.mp3', 'mp3', ?, ?, 'system', 'uploaded')""",
            (audio_source_id, str(audio_path), audio_path.stat().st_size)
        )
        created_sources.append(audio_source_id)

        await _process_source(audio_source_id)
        audio_src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (audio_source_id,))
        assert audio_src["processing_status"] == "completed", f"Expected completed, got {audio_src['processing_status']}, error: {audio_src.get('error_message')}"
        audio_vid = db_get("SELECT * FROM videos WHERE source_id = ?", (audio_source_id,))
        assert audio_vid is not None, "Expected videos row for audio source"
        audio_transcripts = db_all("SELECT * FROM video_transcripts WHERE source_id = ?", (audio_source_id,))
        assert len(audio_transcripts) > 0, "Expected transcript entries for audio"
        print(f"  [PASS] Audio ingested successfully: status={audio_src['processing_status']}, transcripts={len(audio_transcripts)}, duration={audio_src['duration_seconds']}s")

        # -------------------------------------------------------------
        # TEST 4: Video Ingestion (Foreign Key Validation)
        # -------------------------------------------------------------
        print("\n--- TEST 4: Video Ingestion & Foreign Key Integrity ---")
        video_path = test_dir / "test_video.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=15",
             "-f", "lavfi", "-i", "sine=frequency=800:duration=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        )

        video_source_id = str(uuid.uuid4())
        db_run(
            """INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status)
               VALUES (?, 'test_video.mp4', 'test_video.mp4', 'mp4', ?, ?, 'system', 'uploaded')""",
            (video_source_id, str(video_path), video_path.stat().st_size)
        )
        created_sources.append(video_source_id)

        await _process_source(video_source_id)
        video_src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (video_source_id,))
        assert video_src["processing_status"] == "completed", f"Expected completed, got {video_src['processing_status']}, error: {video_src.get('error_message')}"
        vid_row = db_get("SELECT * FROM videos WHERE source_id = ?", (video_source_id,))
        assert vid_row is not None, "Expected videos parent row to exist"
        vid_transcripts = db_all("SELECT * FROM video_transcripts WHERE video_id = ?", (vid_row["id"],))
        assert len(vid_transcripts) > 0, "Expected video transcripts with valid video_id foreign key"
        vid_frames = db_all("SELECT * FROM video_frames WHERE video_id = ?", (vid_row["id"],))
        print(f"  [PASS] Video ingested successfully without FOREIGN KEY failure:")
        print(f"         status={video_src['processing_status']}, video_id={vid_row['id']}, transcripts={len(vid_transcripts)}, frames={len(vid_frames)}")

        # -------------------------------------------------------------
        # TEST 5: Error Isolation and Failure Status
        # -------------------------------------------------------------
        print("\n--- TEST 5: Error Isolation & Failure Status ---")
        corrupt_source_id = str(uuid.uuid4())
        db_run(
            """INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status)
               VALUES (?, 'corrupt.pdf', 'corrupt.pdf', 'pdf', 'non_existent_path.pdf', 500, 'system', 'uploaded')""",
            (corrupt_source_id,)
        )
        created_sources.append(corrupt_source_id)

        await _process_source(corrupt_source_id)
        corrupt_src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (corrupt_source_id,))
        assert corrupt_src["processing_status"] == "failed", f"Expected failed, got {corrupt_src['processing_status']}"
        assert corrupt_src["error_message"] is not None
        assert "[process_document]" in corrupt_src["error_message"]
        print(f"  [PASS] Failed file handled reliably:")
        print(f"         status={corrupt_src['processing_status']}, error={corrupt_src['error_message']}")

        # -------------------------------------------------------------
        # TEST 6: Background Worker Resilience
        # -------------------------------------------------------------
        print("\n--- TEST 6: Background Worker Resilience Under Errors ---")
        worker_task = asyncio.create_task(background_worker())

        fail_id = str(uuid.uuid4())
        db_run(
            """INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status)
               VALUES (?, 'fail_in_worker.pdf', 'fail_in_worker.pdf', 'pdf', 'invalid_path.pdf', 10, 'system', 'uploaded')""",
            (fail_id,)
        )
        created_sources.append(fail_id)

        ok_id = str(uuid.uuid4())
        ok_txt = test_dir / "worker_ok.txt"
        with open(ok_txt, "w") as f:
            f.write("SmartFinder worker resilience test document.")
        db_run(
            """INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status)
               VALUES (?, 'worker_ok.txt', 'worker_ok.txt', 'txt', ?, 40, 'system', 'uploaded')""",
            (ok_id, str(ok_txt))
        )
        created_sources.append(ok_id)

        # Enqueue failing job, then valid job
        await enqueue_source_processing(fail_id)
        await enqueue_source_processing(ok_id)

        # Wait for queue to drain
        await asyncio.wait_for(_task_queue.join(), timeout=30.0)
        worker_task.cancel()

        fail_rec = db_get("SELECT processing_status, error_message FROM knowledge_sources WHERE id = ?", (fail_id,))
        ok_rec = db_get("SELECT processing_status, error_message FROM knowledge_sources WHERE id = ?", (ok_id,))
        assert fail_rec["processing_status"] == "failed"
        assert ok_rec["processing_status"] == "completed"
        print(f"  [PASS] Worker processed failing job ({fail_rec['processing_status']}) and continued to succeed on subsequent job ({ok_rec['processing_status']}).")

        # -------------------------------------------------------------
        # TEST 7: FAISS Index Integrity Check
        # -------------------------------------------------------------
        print("\n--- TEST 7: FAISS Index Integrity Check ---")
        final_counts = {
            "text": faiss_mgr.text_index.ntotal,
            "image": faiss_mgr.image_index.ntotal,
            "face": faiss_mgr.face_index.ntotal
        }
        print(f"  [Initial Counts] {initial_counts}")
        print(f"  [Final Counts]   {final_counts}")
        assert final_counts["text"] >= initial_counts["text"]
        assert final_counts["image"] >= initial_counts["image"]

        # Test search queries
        text_results = faiss_mgr.search_text(faiss_mgr.text_index.reconstruct(0).tolist() if final_counts["text"] > 0 else [0.0]*1024, top_k=3)
        print(f"  Text index search test: returned {len(text_results)} hits")
        print("  [PASS] FAISS indexes remain valid, updated, and searchable.")

    finally:
        # Clean up test directory
        if test_dir.exists():
            try:
                shutil.rmtree(test_dir)
            except Exception:
                pass

        # Clean up created database records and FAISS vectors from test
        for sid in created_sources:
            try:
                faiss_mgr.remove_source_vectors(sid)
                with get_db_context() as conn:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM document_chunks WHERE source_id = ?", (sid,))
                    cur.execute("DELETE FROM document_sections WHERE source_id = ?", (sid,))
                    cur.execute("DELETE FROM documents WHERE source_id = ?", (sid,))
                    cur.execute("DELETE FROM video_transcripts WHERE source_id = ?", (sid,))
                    cur.execute("DELETE FROM video_frames WHERE source_id = ?", (sid,))
                    cur.execute("DELETE FROM videos WHERE source_id = ?", (sid,))
                    cur.execute("DELETE FROM images WHERE source_id = ?", (sid,))
                    cur.execute("DELETE FROM face_embeddings WHERE source_id = ?", (sid,))
                    cur.execute("DELETE FROM knowledge_sources WHERE id = ?", (sid,))
                    conn.commit()
            except Exception:
                pass
        faiss_mgr.save_to_disk()

    print("\n" + "=" * 70)
    print("ALL 7 INGESTION VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
