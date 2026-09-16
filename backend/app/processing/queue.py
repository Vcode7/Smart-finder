import asyncio
import json
import inspect
import traceback
from typing import Dict, Any, Optional, Set
from app.database.session import db_run, db_get, db_all

# In-memory background task queue
_task_queue: asyncio.Queue = asyncio.Queue()
_worker_running: bool = False

# Sources pending FAISS removal (guard against stale results before rebuild runs)
# Audit #10: FAISS index is not immediately consistent with SQLite deletes.
_pending_deletion: Set[str] = set()

async def enqueue_source_processing(source_id: str) -> None:
    await _task_queue.put({"type": "process", "source_id": source_id})

async def enqueue_faiss_removal(source_id: str) -> None:
    """
    Enqueues an async FAISS vector removal for a deleted source.
    Also adds source_id to _pending_deletion so search results can filter
    it out immediately, before the background rebuild completes.
    """
    _pending_deletion.add(source_id)
    await _task_queue.put({"type": "remove_faiss", "source_id": source_id})

def is_pending_deletion(source_id: str) -> bool:
    """Returns True if this source's FAISS vectors are pending removal."""
    return source_id in _pending_deletion

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
            task = await _task_queue.get()
            try:
                # Support both legacy string tasks and new dict tasks
                if isinstance(task, str):
                    await _process_source(task)
                elif isinstance(task, dict):
                    task_type = task.get("type")
                    source_id = task.get("source_id", "")
                    if task_type == "process":
                        await _process_source(source_id)
                    elif task_type == "remove_faiss":
                        try:
                            print(f"[IngestionPipeline] Removing FAISS vectors for source {source_id}...")
                            from app.search.faiss_index import get_faiss_manager
                            faiss_mgr = get_faiss_manager()
                            await asyncio.to_thread(faiss_mgr.remove_source_vectors, source_id)
                            _pending_deletion.discard(source_id)
                            print(f"[IngestionPipeline] FAISS vectors removed for source {source_id}.")
                        except Exception as e:
                            print(f"[IngestionPipeline] FAISS removal failed for {source_id}: {e}")
                            _pending_deletion.discard(source_id)
                    else:
                        print(f"[IngestionPipeline] Unknown task type: {task_type}")
                else:
                    print(f"[IngestionPipeline] Unrecognized task format: {task!r}")
            except Exception as e:
                print(f"[IngestionPipeline] Unhandled exception processing task {task!r}: {type(e).__name__}: {e}")
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

