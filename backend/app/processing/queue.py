import asyncio
import json
import inspect
import traceback
from typing import Dict, Any, Optional
from app.database.session import db_run, db_get, db_all

# In-memory background task queue
_task_queue: asyncio.Queue = asyncio.Queue()
_worker_running: bool = False

async def enqueue_source_processing(source_id: str) -> None:
    await _task_queue.put(source_id)

def recover_stale_sources() -> None:
    """Reset any sources left stuck in 'processing' or 'indexing' state across restarts."""
    try:
        stale = db_all(
            "SELECT id, original_name, processing_status FROM knowledge_sources WHERE processing_status IN ('processing', 'indexing')"
        )
        if stale:
            for s in stale:
                msg = f"Processing interrupted: server restart while source was in '{s['processing_status']}' status"
                print(f"[IngestionPipeline] Recovering stale source {s['id']} ({s['original_name']}): marking failed")
                db_run(
                    "UPDATE knowledge_sources SET processing_status = 'failed', error_message = ? WHERE id = ?",
                    (msg, s["id"])
                )
    except Exception as e:
        print(f"[IngestionPipeline] Error during stale source recovery: {e}")

async def _process_source(source_id: str) -> None:
    src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (source_id,))
    if not src:
        print(f"[IngestionPipeline] Source {source_id} not found in database")
        return

    try:
        db_run("UPDATE knowledge_sources SET processing_status = 'processing', error_message = NULL WHERE id = ?", (source_id,))

        file_type = (src.get("file_type") or "").lower()
        from app.processing.processors import (
            process_document,
            process_image,
            process_video,
            process_audio,
        )

        DOCUMENT_EXTS = {'pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx', 'xls', 'json', 'xml', 'html'}
        IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}
        VIDEO_EXTS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
        AUDIO_EXTS = {'mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac'}

        if file_type in DOCUMENT_EXTS:
            processor = process_document
        elif file_type in IMAGE_EXTS:
            processor = process_image
        elif file_type in VIDEO_EXTS:
            processor = process_video
        elif file_type in AUDIO_EXTS:
            processor = process_audio
        else:
            processor = process_document

        proc_name = processor.__name__
        print(f"[IngestionPipeline] Starting {proc_name} for source {source_id} ({src.get('original_name')})")

        if inspect.iscoroutinefunction(processor):
            await processor(source_id)
        else:
            await asyncio.to_thread(processor, source_id)

        db_run("UPDATE knowledge_sources SET processing_status = 'completed', error_message = NULL WHERE id = ?", (source_id,))
        print(f"[IngestionPipeline] Ingestion completed for source {source_id} ({src.get('original_name')})")
    except Exception as e:
        processor_name = proc_name if 'proc_name' in locals() else 'unknown'
        err_msg = f"[{processor_name}] {type(e).__name__}: {str(e)}"
        print(f"[IngestionPipeline] Ingestion failed for source {source_id} ({src.get('original_name', 'unknown')}): {err_msg}")
        traceback.print_exc()
        try:
            db_run("UPDATE knowledge_sources SET processing_status = 'failed', error_message = ? WHERE id = ?", (err_msg, source_id))
            src_curr = db_get("SELECT metadata_json FROM knowledge_sources WHERE id = ?", (source_id,))
            meta = {}
            if src_curr and src_curr.get("metadata_json"):
                try: meta = json.loads(src_curr["metadata_json"])
                except Exception: meta = {}
            if "processing_info" not in meta:
                meta["processing_info"] = {
                    "source_id": source_id,
                    "filename": src.get("original_name"),
                    "file_type": file_type,
                    "processing_status": "failed",
                    "error_message": err_msg,
                    "logs": [{"timestamp": "", "prefix": "[Storage]", "message": f"Failed: {err_msg}"}]
                }
            else:
                meta["processing_info"]["processing_status"] = "failed"
                meta["processing_info"]["error_message"] = err_msg
            db_run("UPDATE knowledge_sources SET metadata_json = ? WHERE id = ?", (json.dumps(meta), source_id))
        except Exception as dbe:
            print(f"[IngestionPipeline] Failed to update error status in DB for source {source_id}: {dbe}")

async def background_worker() -> None:
    global _worker_running
    _worker_running = True
    print("[IngestionPipeline] Background worker started")
    while True:
        try:
            source_id = await _task_queue.get()
            try:
                await _process_source(source_id)
            except Exception as e:
                print(f"[IngestionPipeline] Unhandled exception processing source {source_id}: {type(e).__name__}: {e}")
                traceback.print_exc()
            finally:
                _task_queue.task_done()
        except asyncio.CancelledError:
            print("[IngestionPipeline] Background worker cancelled")
            break
        except Exception as e:
            print(f"[IngestionPipeline] Worker loop unexpected error: {type(e).__name__}: {e}")
            traceback.print_exc()
            await asyncio.sleep(1.0)

def start_background_worker() -> None:
    asyncio.create_task(background_worker())

