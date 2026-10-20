import asyncio
import json
import inspect
import traceback
from typing import Any, Coroutine, Optional, Set
from app.database.session import db_run, db_get, db_all

MAX_ATTEMPTS = 3

# In-memory background task queue. The database stays the source of truth: sources
# with status 'uploaded' are pending, and are re-queued at every startup.
# The queue is created by start_background_worker(): an asyncio.Queue binds to the
# event loop that first uses it, so a module-level instance breaks when the app is
# started more than once in a process (tests, reloads).
_task_queue: Optional[asyncio.Queue] = None
_queued_ids: Set[str] = set()   # queued or currently processing — prevents duplicate runs


def _get_queue() -> asyncio.Queue:
    global _task_queue
    if _task_queue is None:
        _task_queue = asyncio.Queue()
    return _task_queue

# The event loop keeps only weak references to tasks; hold strong ones so long-lived
# background tasks can't be garbage-collected mid-run.
_background_tasks: Set[asyncio.Task] = set()


def spawn_background(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def enqueue_source_processing(source_id: str) -> bool:
    """Queue a source for ingestion. Returns False if it is already queued or running."""
    if source_id in _queued_ids:
        return False
    _queued_ids.add(source_id)
    await _get_queue().put({"type": "process", "source_id": source_id})
    return True


def is_source_queued(source_id: str) -> bool:
    return source_id in _queued_ids


def recover_stale_sources() -> None:
    """Re-queue sources left in 'processing'/'indexing' by an interrupted run (bounded retries)."""
    try:
        stale = db_all(
            "SELECT id, original_name, processing_status, attempts FROM knowledge_sources "
            "WHERE processing_status IN ('processing', 'indexing')"
        )
        for s in stale:
            attempts = int(s.get("attempts") or 0)
            if attempts >= MAX_ATTEMPTS:
                msg = f"Processing was interrupted {attempts} times (last status '{s['processing_status']}'); giving up"
                db_run(
                    "UPDATE knowledge_sources SET processing_status = 'failed', error_message = ? WHERE id = ?",
                    (msg, s["id"])
                )
                print(f"[IngestionPipeline] Source {s['id']} marked failed after {attempts} interrupted attempts")
            else:
                db_run(
                    "UPDATE knowledge_sources SET processing_status = 'uploaded', error_message = ? WHERE id = ?",
                    ("Re-queued after an interrupted run", s["id"])
                )
                print(f"[IngestionPipeline] Re-queueing interrupted source {s['id']} ({s['original_name']})")
    except Exception as e:
        print(f"[IngestionPipeline] Error during stale source recovery: {e}")


async def enqueue_pending_sources() -> int:
    """Queue every source still waiting in 'uploaded' (the in-memory queue does not survive restarts)."""
    rows = db_all("SELECT id FROM knowledge_sources WHERE processing_status = 'uploaded' ORDER BY upload_date ASC")
    count = 0
    for r in rows:
        if await enqueue_source_processing(r["id"]):
            count += 1
    if count:
        print(f"[IngestionPipeline] Re-queued {count} pending source(s) from a previous run")
    return count


def _mark_failed(source_id: str, src: dict, file_type: str, err_msg: str) -> None:
    db_run("UPDATE knowledge_sources SET processing_status = 'failed', error_message = ? WHERE id = ?", (err_msg, source_id))
    src_curr = db_get("SELECT metadata_json FROM knowledge_sources WHERE id = ?", (source_id,))
    meta = {}
    if src_curr and src_curr.get("metadata_json"):
        try:
            meta = json.loads(src_curr["metadata_json"])
        except Exception:
            meta = {}
    info = meta.get("processing_info") or {
        "source_id": source_id,
        "filename": src.get("original_name"),
        "file_type": file_type,
        "logs": [{"timestamp": "", "prefix": "[Storage]", "message": f"Failed: {err_msg}"}],
    }
    info["processing_status"] = "failed"
    info["error_message"] = err_msg
    meta["processing_info"] = info
    db_run("UPDATE knowledge_sources SET metadata_json = ? WHERE id = ?", (json.dumps(meta), source_id))


async def _process_source(source_id: str) -> None:
    from app.processing.purge import is_internet_source, purge_derived_data
    from app.search.constants import classify_extension

    src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (source_id,))
    if not src:
        print(f"[IngestionPipeline] Source {source_id} not found in database")
        return

    file_type = (src.get("file_type") or "").lower()
    if is_internet_source(src):
        # Internet imports are chunked and embedded at import time; there is no file to process.
        db_run("UPDATE knowledge_sources SET processing_status = 'completed', error_message = NULL WHERE id = ?", (source_id,))
        return

    kind = classify_extension(file_type)
    if kind == "unsupported":
        _mark_failed(source_id, src, file_type, f"Unsupported file type '.{file_type}'")
        return

    proc_name = "unknown"
    try:
        db_run(
            "UPDATE knowledge_sources SET processing_status = 'processing', error_message = NULL, "
            "attempts = COALESCE(attempts, 0) + 1 WHERE id = ?",
            (source_id,)
        )

        from app.processing.processors import (
            process_document,
            process_image,
            process_video,
            process_audio,
        )
        processor = {
            "document": process_document,
            "image": process_image,
            "video": process_video,
            "audio": process_audio,
        }[kind]
        proc_name = processor.__name__

        # Idempotent re-runs: clear anything a previous (interrupted) attempt left behind
        await asyncio.to_thread(purge_derived_data, source_id)

        print(f"[IngestionPipeline] Starting {proc_name} for source {source_id} ({src.get('original_name')})")
        if inspect.iscoroutinefunction(processor):
            await processor(source_id)
        else:
            await asyncio.to_thread(processor, source_id)

        db_run(
            "UPDATE knowledge_sources SET processing_status = 'completed', error_message = NULL, attempts = 0 WHERE id = ?",
            (source_id,)
        )
        print(f"[IngestionPipeline] Ingestion completed for source {source_id} ({src.get('original_name')})")
    except Exception as e:
        err_msg = f"[{proc_name}] {type(e).__name__}: {str(e)}"
        # Persist the failure before printing: a console encoding error must not
        # leave the source stuck in 'processing'.
        try:
            _mark_failed(source_id, src, file_type, err_msg)
        except Exception as dbe:
            print(f"[IngestionPipeline] Failed to update error status in DB for source {source_id}: {dbe}")
        print(f"[IngestionPipeline] Ingestion failed for source {source_id}: {err_msg}")
        traceback.print_exc()


async def background_worker() -> None:
    print("[IngestionPipeline] Background worker started")
    while True:
        try:
            task = await _get_queue().get()
            source_id = ""
            try:
                if isinstance(task, str):
                    source_id = task
                    await _process_source(task)
                elif isinstance(task, dict) and task.get("type") == "process":
                    source_id = task.get("source_id", "")
                    await _process_source(source_id)
                else:
                    print(f"[IngestionPipeline] Unrecognized task format: {task!r}")
            except Exception as e:
                print(f"[IngestionPipeline] Unhandled exception processing task {task!r}: {type(e).__name__}: {e}")
                traceback.print_exc()
            finally:
                _queued_ids.discard(source_id)
                _get_queue().task_done()
        except asyncio.CancelledError:
            print("[IngestionPipeline] Background worker cancelled")
            break
        except Exception as e:
            print(f"[IngestionPipeline] Worker loop unexpected error: {type(e).__name__}: {e}")
            traceback.print_exc()
            await asyncio.sleep(1.0)


def start_background_worker() -> asyncio.Task:
    global _task_queue
    _task_queue = asyncio.Queue()  # bound to the running event loop
    _queued_ids.clear()
    return spawn_background(background_worker())
