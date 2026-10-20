import asyncio
import shutil
import uuid
from typing import Dict, Any
from app.core.config import settings
from app.database.session import db_get, db_run
from app.processing.queue import enqueue_source_processing, MAX_ATTEMPTS
from app.search.constants import SUPPORTED_EXTENSIONS


async def sync_knowledge_folder() -> Dict[str, Any]:
    """Import supported files dropped into KB_DIR (top level) into the knowledge base."""
    from app.database.seed import seed_system_user
    seed_system_user()

    kb_dir = settings.resolved_kb_dir
    upload_dir = settings.resolved_upload_dir
    kb_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    synced_files = []
    skipped_files = []
    errors = []

    files = await asyncio.to_thread(lambda: sorted(kb_dir.glob("*")))
    for file_path in files:
        if file_path.is_dir() or file_path.name.startswith("."):
            continue

        ext = file_path.suffix.lstrip(".").lower()
        if ext not in SUPPORTED_EXTENSIONS:
            skipped_files.append({"filename": file_path.name, "reason": "unsupported_extension"})
            continue

        original_name = file_path.name
        file_size = file_path.stat().st_size
        existing = db_get(
            "SELECT id, processing_status, file_size, attempts FROM knowledge_sources "
            "WHERE original_name = ? COLLATE NOCASE",
            (original_name,)
        )

        changed = bool(existing) and int(existing.get("file_size") or 0) != file_size
        if existing and not changed:
            status = existing["processing_status"]
            if status in ("completed", "processing", "indexing"):
                skipped_files.append({"filename": original_name, "reason": "already_indexed", "id": existing["id"]})
                continue
            if status == "uploaded":
                await enqueue_source_processing(existing["id"])
                skipped_files.append({"filename": original_name, "reason": "already_queued", "id": existing["id"]})
                continue
            if status == "failed" and int(existing.get("attempts") or 0) >= MAX_ATTEMPTS:
                skipped_files.append({"filename": original_name, "reason": "failed", "id": existing["id"]})
                continue

        source_id = existing["id"] if existing else str(uuid.uuid4())
        dest_filename = f"{source_id}.{ext}"
        dest_path = upload_dir / dest_filename

        try:
            await asyncio.to_thread(shutil.copy2, file_path, dest_path)

            if existing:
                db_run(
                    "UPDATE knowledge_sources SET file_path = ?, file_size = ?, processing_status = 'uploaded', "
                    "attempts = CASE WHEN ? THEN 0 ELSE attempts END WHERE id = ?",
                    (str(dest_path), file_size, 1 if changed else 0, source_id)
                )
            else:
                db_run(
                    """INSERT INTO knowledge_sources (
                        id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'system', 'uploaded')""",
                    (source_id, dest_filename, original_name, ext, str(dest_path), file_size)
                )

            await enqueue_source_processing(source_id)
            synced_files.append({"id": source_id, "originalName": original_name, "fileType": ext, "status": "queued"})
        except Exception as e:
            errors.append({"filename": original_name, "error": str(e)})

    return {
        "scanned": len(files),
        "synced": len(synced_files),
        "skipped": len(skipped_files),
        "errors": len(errors),
        "syncedFiles": synced_files,
        "skippedFiles": skipped_files,
        "errorDetails": errors,
        "message": f"Scanned {len(files)} file(s): {len(synced_files)} queued, {len(skipped_files)} skipped, {len(errors)} error(s).",
    }
