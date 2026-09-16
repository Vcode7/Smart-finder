import os
import re
import json
import uuid
import mimetypes
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, Response, HTTPException, status, Depends, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse

from app.core.config import settings
from app.database.session import db_get, db_all, db_run, get_db_context
from app.api.deps import get_current_user, require_auth, require_admin
from app.processing.queue import enqueue_source_processing
from app.processing.folder_sync import sync_knowledge_folder
from app.schemas.knowledge import ImportInternetRequest, ScrapeSearchRequest, CheckConflictsRequest, CheckConflictsResponse, ConflictItem
from app.search.model_pipeline import get_text_embedding
from app.search.embeddings import float_array_to_blob

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

def get_unique_filename(original_name: str, reserved_names: Optional[set] = None) -> str:
    """
    Check whether a file with this name already exists in knowledge_sources (DB)
    or the knowledge_base storage directory, or within reserved_names in the current batch.
    If it exists, return a unique filename with an incremental suffix (e.g. 'file_1.pdf', 'file_2.pdf').
    If it does not exist, returns original_name unchanged.
    """
    reserved = set(reserved_names or set())
    kb_dir = settings.resolved_kb_dir

    def _is_name_taken(name: str) -> bool:
        if name.lower() in {r.lower() for r in reserved}:
            return True
        row = db_get(
            "SELECT 1 FROM knowledge_sources WHERE original_name = ? COLLATE NOCASE",
            (name,)
        )
        if row:
            return True
        if (kb_dir / name).exists():
            return True
        return False

    if not _is_name_taken(original_name):
        return original_name

    # Separate stem and extension
    if "." in original_name and not original_name.startswith("."):
        stem, ext = original_name.rsplit(".", 1)
        ext_dot = f".{ext}"
    else:
        stem = original_name
        ext_dot = ""

    # Detect if stem already has a trailing _<number>
    match = re.search(r"^(.*)_(\d+)$", stem)
    if match:
        base_stem = match.group(1)
        counter = int(match.group(2)) + 1
    else:
        base_stem = stem
        counter = 1

    while True:
        candidate = f"{base_stem}_{counter}{ext_dot}"
        if not _is_name_taken(candidate):
            return candidate
        counter += 1


@router.post("/check-conflicts", response_model=CheckConflictsResponse)
async def check_conflicts(
    req: CheckConflictsRequest,
    user: Dict[str, Any] = Depends(require_auth)
):
    """
    Checks whether files with the given names already exist in the repository.
    Returns conflicts list with suggested unique filenames (e.g. file_1.pdf).
    """
    kb_dir = settings.resolved_kb_dir
    conflicts: List[ConflictItem] = []
    reserved_batch: set = set()

    # Query all existing names once for rapid case-insensitive lookup
    existing_rows = db_all("SELECT original_name FROM knowledge_sources")
    existing_db_names = {r["original_name"].lower() for r in existing_rows}

    for fname in req.filenames:
        if not fname or not fname.strip():
            continue
        clean_name = fname.strip()
        name_lower = clean_name.lower()
        exists_in_db = name_lower in existing_db_names
        exists_in_kb = (kb_dir / clean_name).exists()
        already_in_batch = name_lower in {r.lower() for r in reserved_batch}

        if exists_in_db or exists_in_kb or already_in_batch:
            suggested = get_unique_filename(clean_name, reserved_batch)
            reserved_batch.add(suggested)
            conflicts.append(ConflictItem(
                originalName=clean_name,
                suggestedName=suggested,
                existsInDb=exists_in_db or exists_in_kb
            ))
        else:
            reserved_batch.add(clean_name)

    return CheckConflictsResponse(
        hasConflicts=len(conflicts) > 0,
        conflicts=conflicts
    )


@router.get("")
async def list_sources(user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    is_admin = user and user.get("role") == "admin"
    if is_admin:
        sql = """
            SELECT ks.*, u.username as uploader_name
            FROM knowledge_sources ks
            LEFT JOIN users u ON ks.uploaded_by = u.id
            ORDER BY ks.upload_date DESC
        """
        rows = db_all(sql)
    else:
        sql = """
            SELECT ks.*, u.username as uploader_name
            FROM knowledge_sources ks
            LEFT JOIN users u ON ks.uploaded_by = u.id
            WHERE ks.processing_status = 'completed'
            ORDER BY ks.upload_date DESC
        """
        rows = db_all(sql)

    return {"sources": rows, "count": len(rows)}


@router.post("/upload")
async def upload_source(
    request: Request,
    user: Dict[str, Any] = Depends(require_auth)
):
    form = await request.form()
    resolve_duplicates = str(form.get("resolve_duplicates", "false")).lower() in ("true", "1", "yes")

    all_files: List[UploadFile] = []
    for key in ["files", "file"]:
        items = form.getlist(key)
        for item in items:
            if hasattr(item, "filename") and item.filename:
                all_files.append(item)

    if not all_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided for upload."
        )

    upload_dir = settings.resolved_upload_dir
    kb_dir = settings.resolved_kb_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    kb_dir.mkdir(parents=True, exist_ok=True)

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    results = []
    reserved_batch_names: set = set()

    for uploaded_file in all_files:
        original_name = uploaded_file.filename or "uploaded_file"

        # Check if file name conflict exists
        conflict_exists = False
        existing_row = db_get(
            "SELECT 1 FROM knowledge_sources WHERE original_name = ? COLLATE NOCASE",
            (original_name,)
        )
        if existing_row or (kb_dir / original_name).exists() or original_name.lower() in {r.lower() for r in reserved_batch_names}:
            conflict_exists = True

        if conflict_exists and not resolve_duplicates:
            results.append({
                "filename": original_name,
                "error": f"A file named '{original_name}' already exists. Upload cancelled or requires confirmation."
            })
            continue

        if conflict_exists and resolve_duplicates:
            final_name = get_unique_filename(original_name, reserved_batch_names)
        else:
            final_name = original_name

        reserved_batch_names.add(final_name)

        ext = final_name.split(".")[-1].lower() if "." in final_name else "txt"
        source_id = str(uuid.uuid4())
        dest_filename = f"{source_id}.{ext}"

        dest_path = upload_dir / dest_filename
        kb_copy_path = kb_dir / final_name

        try:
            contents = await uploaded_file.read()
            file_size = len(contents)

            if file_size > max_bytes:
                results.append({
                    "filename": final_name,
                    "error": f"File exceeds max size limit of {settings.MAX_FILE_SIZE_MB}MB"
                })
                continue

            with open(dest_path, "wb") as f:
                f.write(contents)

            try:
                shutil.copy2(dest_path, kb_copy_path)
            except Exception:
                pass

            db_run(
                """INSERT INTO knowledge_sources (
                    id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded')""",
                (source_id, dest_filename, final_name, ext, str(dest_path), file_size, user["id"])
            )

            await enqueue_source_processing(source_id)

            results.append({
                "id": source_id,
                "filename": dest_filename,
                "original_name": final_name,
                "file_type": ext,
                "file_size": file_size,
                "processing_status": "uploaded",
                "source": {
                    "id": source_id,
                    "filename": dest_filename,
                    "original_name": final_name,
                    "file_type": ext,
                    "file_size": file_size,
                    "processing_status": "uploaded",
                }
            })
        except Exception as e:
            results.append({
                "filename": original_name,
                "error": str(e)
            })

    first_source = next((r["source"] for r in results if "source" in r), None)
    return {
        "success": any("source" in r for r in results),
        "results": results,
        "source": first_source,
    }

@router.get("/{source_id}")
async def get_source_detail(source_id: str, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    src = db_get(
        """SELECT ks.*, u.username as uploader_name
           FROM knowledge_sources ks
           LEFT JOIN users u ON ks.uploaded_by = u.id
           WHERE ks.id = ?""",
        (source_id,)
    )
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    doc = db_get("SELECT id, title, page_count, section_count, full_text FROM documents WHERE source_id = ?", (source_id,))
    sections = []
    chunks = []
    if doc:
        sections = db_all(
            "SELECT id, section_title, page_num, order_idx, length(section_text) as char_count FROM document_sections WHERE doc_id = ? ORDER BY order_idx ASC",
            (doc["id"],)
        )
        chunks = db_all(
            "SELECT id, chunk_order, page_num, length(chunk_text) as char_count, chunk_text FROM document_chunks WHERE doc_id = ? ORDER BY chunk_order ASC LIMIT 20",
            (doc["id"],)
        )

    video = db_get("SELECT id, duration, format, thumbnail_path FROM videos WHERE source_id = ?", (source_id,))
    transcripts = []
    frames = []
    if video:
        transcripts = db_all(
            "SELECT id, start_time, end_time, text FROM video_transcripts WHERE video_id = ? ORDER BY start_time ASC",
            (video["id"],)
        )
        frames = db_all(
            "SELECT id, timestamp, frame_number, scene_id, frame_path, visual_description FROM video_frames WHERE video_id = ? ORDER BY timestamp ASC",
            (video["id"],)
        )

    image = db_get("SELECT id, width, height, ocr_text, description FROM images WHERE source_id = ?", (source_id,))

    processing_info = None
    if src and src.get("metadata_json"):
        try:
            m = json.loads(src["metadata_json"])
            processing_info = m.get("processing_info")
        except Exception:
            pass

    return {
        "source": src,
        "processing_info": processing_info,
        "document": doc,
        "sections": sections,
        "chunks": chunks,
        "video": video,
        "transcripts": transcripts,
        "frames": frames,
        "image": image,
    }

@router.delete("/{source_id}")
async def delete_source(source_id: str, user: Dict[str, Any] = Depends(require_admin)):
    src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (source_id,))
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    # Cascading deletion in database
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM document_chunks WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM chunks_fts WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM document_sections WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM transcripts_fts WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM video_transcripts WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM video_frames WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM videos WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM face_embeddings WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM images WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM knowledge_sources WHERE id = ?", (source_id,))
        conn.commit()

    # Synchronize FAISS Vector Index removal
    try:
        from app.search.faiss_index import get_faiss_manager
        get_faiss_manager().remove_source_vectors(source_id)
    except Exception as e:
        print(f"[Knowledge] FAISS vector removal notice: {e}")

    # Delete physical files
    if src.get("file_path") and Path(src["file_path"]).exists():
        try: os.unlink(src["file_path"])
        except Exception: pass

    frames_dir = settings.resolved_upload_dir / "frames" / source_id
    if frames_dir.exists():
        try: shutil.rmtree(frames_dir)
        except Exception: pass

    faces_dir = settings.resolved_upload_dir / "faces" / source_id
    if faces_dir.exists():
        try: shutil.rmtree(faces_dir)
        except Exception: pass

    doc_img_dir = settings.resolved_upload_dir / "doc_images" / source_id
    if doc_img_dir.exists():
        try: shutil.rmtree(doc_img_dir)
        except Exception: pass

    return {"success": True, "deleted": source_id}

@router.post("/{source_id}/reprocess")
async def reprocess_source(source_id: str, user: Dict[str, Any] = Depends(require_admin)):
    src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (source_id,))
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    # Clear previous artifacts in SQLite
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM document_chunks WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM chunks_fts WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM document_sections WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM transcripts_fts WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM video_transcripts WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM video_frames WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM videos WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM face_embeddings WHERE source_id = ?", (source_id,))
        cursor.execute("DELETE FROM images WHERE source_id = ?", (source_id,))
        cursor.execute("UPDATE knowledge_sources SET processing_status = 'uploaded', error_message = NULL WHERE id = ?", (source_id,))
        conn.commit()

    # Clear previous FAISS vectors
    try:
        from app.search.faiss_index import get_faiss_manager
        get_faiss_manager().remove_source_vectors(source_id)
    except Exception as e:
        print(f"[Knowledge] FAISS vector cleanup notice: {e}")

    await enqueue_source_processing(source_id)
    return {"success": True, "reprocessing": source_id}

@router.post("/reindex-all")
async def reindex_all_sources(user: Dict[str, Any] = Depends(require_admin)):
    """Reindexes all uploaded files using the multimodal FAISS + FTS5 pipeline."""
    from app.search.faiss_index import get_faiss_manager
    sources = db_all("SELECT id, original_name FROM knowledge_sources")
    reindexed_count = 0
    for s in sources:
        sid = s["id"]
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM document_chunks WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM chunks_fts WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM document_sections WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM documents WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM transcripts_fts WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM video_transcripts WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM video_frames WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM videos WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM face_embeddings WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM images WHERE source_id = ?", (sid,))
            cursor.execute("UPDATE knowledge_sources SET processing_status = 'uploaded', error_message = NULL WHERE id = ?", (sid,))
            conn.commit()

        get_faiss_manager().remove_source_vectors(sid)
        await enqueue_source_processing(sid)
        reindexed_count += 1

    return {"success": True, "enqueued": reindexed_count}

@router.get("/{source_id}/file")
async def stream_source_file(source_id: str, request: Request):
    src = db_get("SELECT file_path, original_name, file_type, metadata_json FROM knowledge_sources WHERE id = ?", (source_id,))
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    # If internet source with URL
    if src.get("file_type") == "internet":
        try:
            import json
            meta = json.loads(src.get("metadata_json") or "{}")
            if meta.get("url"):
                return RedirectResponse(meta["url"])
        except Exception:
            pass

    file_path = Path(src["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Physical file not found on disk")

    file_size = file_path.stat().st_size
    content_type, _ = mimetypes.guess_type(str(file_path))
    if not content_type:
        content_type = "application/octet-stream"

    # Support HTTP 206 Partial Content for video/audio seeking
    range_header = request.headers.get("Range")
    if range_header:
        range_match = re.match(r"bytes=(\d+)-(\d+)?", range_header)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            start = max(0, start)
            end = min(file_size - 1, end)
            chunk_length = end - start + 1

            def iterfile():
                with open(file_path, "rb") as f:
                    f.seek(start)
                    bytes_left = chunk_length
                    while bytes_left > 0:
                        chunk = f.read(min(65536, bytes_left))
                        if not chunk:
                            break
                        bytes_left -= len(chunk)
                        yield chunk

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_length),
                "Content-Type": content_type,
            }
            return StreamingResponse(iterfile(), status_code=206, headers=headers)

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Disposition": f'inline; filename="{src["original_name"]}"',
    }
    return FileResponse(path=file_path, media_type=content_type, headers=headers)

@router.get("/{source_id}/frames/{frame_id}")
async def get_video_frame(source_id: str, frame_id: str):
    frame = db_get("SELECT frame_path FROM video_frames WHERE id = ? AND source_id = ?", (frame_id, source_id))
    if not frame or not frame.get("frame_path") or not Path(frame["frame_path"]).exists():
        raise HTTPException(status_code=404, detail="Frame not found")

    return FileResponse(path=frame["frame_path"], media_type="image/jpeg")

@router.post("/sync")
@router.get("/sync")
async def sync_folder(user: Dict[str, Any] = Depends(require_admin)):
    result = await sync_knowledge_folder()
    return result

@router.post("/reset")
async def reset_knowledge(user: Dict[str, Any] = Depends(require_admin)):
    with get_db_context() as conn:
        cursor = conn.cursor()
        for t in ["document_chunks", "chunks_fts", "document_sections", "documents",
                  "video_transcripts", "transcripts_fts", "video_frames", "videos",
                  "face_embeddings", "images", "knowledge_sources"]:
            try: cursor.execute(f"DELETE FROM {t}")
            except Exception: pass
        conn.commit()

    upload_dir = settings.resolved_upload_dir
    for sub in ["frames", "faces", "temp", "doc_images"]:
        d = upload_dir / sub
        if d.exists():
            try: shutil.rmtree(d)
            except Exception: pass
        d.mkdir(parents=True, exist_ok=True)

    try:
        from app.search.faiss_index import get_faiss_manager
        get_faiss_manager().clear_all()
    except Exception as e:
        print(f"[Knowledge] FAISS reset notice: {e}")

    from app.database.seed import seed_system_user, seed_demo_knowledge
    seed_system_user()
    if settings.SEED_DEMO_KNOWLEDGE:
        seed_demo_knowledge()
    return {"success": True, "message": "Knowledge base reset and cleared successfully."}

@router.post("/scrape-search")
async def scrape_search(req: ScrapeSearchRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    from app.search.providers.academic import search_papers
    from app.search.providers.news import search_news
    from app.search.providers.web import search_web
    from app.search.providers.youtube import search_videos
    from app.search.providers.images import search_internet_images

    # Run providers in parallel
    import asyncio
    papers_task = search_papers(query, {"limit": 6})
    news_task = search_news(query, {"limit": 6})
    web_task = search_web(query, {"limit": 6})
    video_task = search_videos(query, {"maxResults": 6})
    images_task = search_internet_images(query, 6)

    papers_res, news_res, web_res, video_res, images_res = await asyncio.gather(
        papers_task, news_task, web_task, video_task, images_task, return_exceptions=True
    )

    papers = papers_res.get("sources", []) if isinstance(papers_res, dict) else []
    articles = news_res.get("articles", []) if isinstance(news_res, dict) else []
    reports = news_res.get("reports", []) if isinstance(news_res, dict) else []
    web = web_res.get("sources", []) if isinstance(web_res, dict) else []
    videos = video_res.get("sources", []) if isinstance(video_res, dict) else []
    images = images_res if isinstance(images_res, list) else []

    scraped_papers = []
    for p in papers:
        scraped_papers.append({
            "id": p.get("id") or str(uuid.uuid4()),
            "category": "paper",
            "title": p.get("title") or "Research Paper",
            "url": p.get("url") or "",
            "snippet": p.get("description") or p.get("abstract") or "",
            "domain": p.get("journal") or "academic",
            "platform": p.get("provider") or "Semantic Scholar / arXiv",
            "publishedDate": p.get("date"),
            "author": p.get("author") or "Academic Authors",
            "relevanceScore": float(p.get("relevanceScore") or 92.0),
        })

    scraped_articles = []
    for a in articles:
        scraped_articles.append({
            "id": a.get("id") or str(uuid.uuid4()),
            "category": "article",
            "title": a.get("title") or "News Article",
            "url": a.get("url") or "",
            "snippet": a.get("description") or "",
            "domain": a.get("provider") or "news",
            "platform": a.get("provider") or "News & Analysis",
            "publishedDate": a.get("date"),
            "author": a.get("author"),
            "thumbnail": a.get("thumbnail"),
            "relevanceScore": float(a.get("relevanceScore") or 88.0),
        })
    for w in web:
        scraped_articles.append({
            "id": w.get("id") or str(uuid.uuid4()),
            "category": "article",
            "title": w.get("title") or "Web Reference",
            "url": w.get("url") or "",
            "snippet": w.get("description") or "",
            "domain": w.get("provider") or "web",
            "platform": w.get("provider") or "Organic Web",
            "publishedDate": w.get("date"),
            "thumbnail": w.get("thumbnail"),
            "relevanceScore": float(w.get("relevanceScore") or 85.0),
        })

    scraped_news = []
    for r in reports:
        scraped_news.append({
            "id": r.get("id") or str(uuid.uuid4()),
            "category": "news",
            "title": r.get("title") or "Policy Report",
            "url": r.get("url") or "",
            "snippet": r.get("description") or "",
            "domain": r.get("provider") or "policy",
            "platform": r.get("provider") or "Policy / Think Tanks",
            "publishedDate": r.get("date"),
            "author": r.get("author"),
            "thumbnail": r.get("thumbnail"),
            "relevanceScore": float(r.get("relevanceScore") or 90.0),
        })
    for a in articles:
        scraped_news.append({
            "id": str(uuid.uuid4()),
            "category": "news",
            "title": a.get("title") or "Live News",
            "url": a.get("url") or "",
            "snippet": a.get("description") or "",
            "domain": a.get("provider") or "news",
            "platform": a.get("provider") or "Live News",
            "publishedDate": a.get("date"),
            "author": a.get("author"),
            "thumbnail": a.get("thumbnail"),
            "relevanceScore": float(a.get("relevanceScore") or 88.0),
        })

    scraped_videos = []
    for v in videos:
        scraped_videos.append({
            "id": v.get("id") or str(uuid.uuid4()),
            "category": "video",
            "title": v.get("title") or "Video Source",
            "url": v.get("url") or "",
            "snippet": v.get("description") or "",
            "domain": "youtube.com",
            "platform": v.get("channel") or "YouTube",
            "publishedDate": v.get("date"),
            "author": v.get("author") or v.get("channel"),
            "thumbnail": v.get("thumbnail"),
            "relevanceScore": float(v.get("relevanceScore") or 86.0),
        })

    scraped_images = []
    for img in images:
        scraped_images.append({
            "id": img.get("id") or str(uuid.uuid4()),
            "category": "image",
            "title": img.get("title") or "Web Image",
            "url": img.get("url") or "",
            "snippet": img.get("title") or img.get("domain") or "Web Image Source",
            "domain": img.get("domain") or "image",
            "platform": "Web Images",
            "thumbnail": img.get("thumbnail") or img.get("url"),
            "relevanceScore": float(img.get("relevanceScore") or 84.0),
        })

    all_sources = scraped_papers + scraped_articles + scraped_news + scraped_videos + scraped_images
    total_count = len(all_sources)

    categories = {
        "papers": scraped_papers,
        "articles": scraped_articles,
        "news": scraped_news,
        "videos": scraped_videos,
        "images": scraped_images,
        "others": [],
    }

    return {
        "query": query,
        "categories": categories,
        "sources": all_sources,
        "counts": {
            "total": total_count,
            "all": total_count,
            "papers": len(scraped_papers),
            "articles": len(scraped_articles),
            "news": len(scraped_news),
            "videos": len(scraped_videos),
            "images": len(scraped_images),
            "others": 0,
            "paper": len(scraped_papers),
            "article": len(scraped_articles),
            "report": len(reports),
            "web": len(web),
            "video": len(scraped_videos),
            "image": len(scraped_images),
        }
    }

@router.post("/import-internet")
async def import_internet(req: ImportInternetRequest, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    if not req.sources:
        raise HTTPException(status_code=400, detail="No sources provided for import")

    # Resolve uploader user ID with admin fallback
    uploader_id = user["id"] if (user and user.get("id")) else None
    if not uploader_id:
        admin_row = db_get("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        uploader_id = admin_row["id"] if admin_row else "system"

    imported = []
    from app.processing.processors import chunk_text
    from app.search.faiss_index import get_faiss_manager
    faiss_mgr = get_faiss_manager()

    with get_db_context() as conn:
        cursor = conn.cursor()
        for item in req.sources:
            source_id = str(uuid.uuid4())
            import json
            meta = {
                "source_type": "internet",
                "url": item.url,
                "original_url": item.url,
                "category": item.category,
                "domain": item.domain,
                "platform": item.platform,
                "author": item.author,
                "publishedDate": item.publishedDate,
                "thumbnail": item.thumbnail,
            }
            file_category = item.category or "internet"
            cursor.execute("""
                INSERT INTO knowledge_sources (
                    id, filename, original_name, file_type, file_path, file_size, uploaded_by,
                    processing_status, chunk_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, 1024, ?, 'completed', 1, ?)
            """, (source_id, f"internet_{source_id}", item.title, file_category, item.url, uploader_id, json.dumps(meta)))

            content_text = item.fullText or item.snippet or item.title
            doc_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO documents (id, source_id, title, full_text, page_count, section_count)
                VALUES (?, ?, ?, ?, 1, 1)
            """, (doc_id, source_id, item.title, content_text))

            chunks = chunk_text(content_text, 800, 150)
            for idx, ch in enumerate(chunks):
                chunk_id = str(uuid.uuid4())
                emb = get_text_embedding(ch)
                cursor.execute("""
                    INSERT INTO document_chunks (id, doc_id, source_id, chunk_text, chunk_order, embedding)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (chunk_id, doc_id, source_id, ch, idx, float_array_to_blob(emb)))
                try:
                    cursor.execute("""
                        INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id)
                        VALUES (?, ?, ?, ?)
                    """, (ch, chunk_id, source_id, doc_id))
                except Exception:
                    pass

                faiss_mgr.add_text_vector(
                    source_id=source_id,
                    chunk_id=chunk_id,
                    vector=emb,
                    metadata={
                        "type": "scraped_chunk",
                        "title": item.title,
                        "url": item.url,
                        "preview": ch[:150],
                    }
                )

            cursor.execute("UPDATE knowledge_sources SET chunk_count = ? WHERE id = ?", (len(chunks), source_id))
            imported.append({"id": source_id, "title": item.title, "category": item.category})
        conn.commit()

    faiss_mgr.save_to_disk()
    return {"success": True, "count": len(imported), "imported": imported}
