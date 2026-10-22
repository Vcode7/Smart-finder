import json
import uuid
import asyncio
import mimetypes
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, HTTPException, status, Depends, UploadFile, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse

from app.core.config import settings
from app.core.files import sanitize_filename, is_within
from app.database.session import db_get, db_all, db_run, get_db_context
from app.api.deps import require_auth, require_admin
from app.core.access import can_access_library, is_admin as user_is_admin, visible_library_ids
from app.processing.queue import enqueue_source_processing, is_source_queued
from app.processing.purge import delete_source as purge_and_delete_source, purge_derived_data, is_internet_source
from app.schemas.knowledge import ImportInternetRequest, ScrapeSearchRequest, CheckConflictsRequest, CheckConflictsResponse, ConflictItem
from app.search.constants import (
    DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
    SUPPORTED_EXTENSIONS, preview_text,
)
from app.library import compat
from app.library.manager import get_library_manager

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _wake_indexer() -> None:
    from app.ingest.pipeline import get_pipeline
    get_pipeline().wake()


async def _library_source(source_id: str, user: Optional[Dict[str, Any]] = None):
    """(library, source row) when the id belongs to a folder library, else None.

    With `user` given, a non-admin only gets sources of libraries shared with them; anything
    else (including legacy-index rows, which belong to no library) is a 404."""
    found = await run_in_threadpool(compat.find, source_id.removeprefix("src-"))
    if user is not None and not user_is_admin(user):
        if found is None or not can_access_library(user, found[0].id):
            raise HTTPException(status_code=404, detail="Source not found")
    return found

# Columns returned by the list endpoint. metadata_json is slimmed (logs removed) below.
_LIST_COLUMNS = (
    "ks.id, ks.filename, ks.original_name, ks.file_type, ks.file_path, ks.file_size, ks.upload_date, "
    "ks.uploaded_by, ks.processing_status, ks.error_message, ks.metadata_json, ks.tags_json, "
    "ks.chunk_count, ks.transcript_count, ks.face_count, ks.frame_count, ks.duration_seconds, ks.page_count"
)


def _slim_metadata(raw: Optional[str]) -> str:
    """Drop the (potentially huge) processing logs from metadata_json for list responses."""
    if not raw:
        return "{}"
    try:
        meta = json.loads(raw)
    except Exception:
        return "{}"
    meta.pop("processing_info", None)
    return json.dumps(meta)


def _name_taken(name: str, reserved: set) -> bool:
    if name.lower() in reserved:
        return True
    if compat.uploads_name_taken(name):
        return True
    if db_get("SELECT 1 FROM knowledge_sources WHERE original_name = ? COLLATE NOCASE", (name,)):
        return True
    return (settings.resolved_kb_dir / name).exists()


def get_unique_filename(original_name: str, reserved_names: Optional[set] = None) -> str:
    """
    Return original_name, or 'name (1).ext', 'name (2).ext', ... if a source or
    knowledge_base file with that name exists (or it is already used in this batch).
    """
    reserved = {r.lower() for r in (reserved_names or set())}
    if not _name_taken(original_name, reserved):
        return original_name
    stem, dot, ext = original_name.rpartition(".")
    if not dot:
        stem, ext = original_name, ""
    counter = 1
    while True:
        candidate = f"{stem} ({counter}).{ext}" if ext else f"{stem} ({counter})"
        if not _name_taken(candidate, reserved):
            return candidate
        counter += 1


def _sniff_is_text(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        return b"\x00" not in head
    except Exception:
        return False


# ─── Collection routes (registered before /{source_id} so they are reachable) ──

@router.get("")
async def list_sources(
    user: Dict[str, Any] = Depends(require_auth),
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    q: Optional[str] = Query(None),
):
    is_admin = user.get("role") == "admin"
    where = ["ks.id NOT IN (SELECT source_id FROM legacy_migrated)"]   # listed from their library instead
    params: List[Any] = []
    if not is_admin:
        where.append("0 = 1")   # the legacy index belongs to no library, so it is admin-only
    elif status_filter:
        where.append("ks.processing_status = ?")
        params.append(status_filter)
    if q and q.strip():
        where.append("ks.original_name LIKE ?")
        params.append(f"%{q.strip()}%")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    total_row = db_get(f"SELECT COUNT(*) AS n FROM knowledge_sources ks {where_sql}", tuple(params))
    rows = db_all(
        f"""SELECT {_LIST_COLUMNS}, u.username as uploader_name
            FROM knowledge_sources ks
            LEFT JOIN users u ON ks.uploaded_by = u.id
            {where_sql}
            ORDER BY ks.upload_date DESC
            LIMIT ?""",
        tuple(params) + (limit + offset,)
    )
    for r in rows:
        r["metadata_json"] = _slim_metadata(r.get("metadata_json"))

    # Folder libraries (newest first, merged with the legacy index)
    lib_rows, lib_total = await run_in_threadpool(
        compat.list_rows, get_library_manager(), is_admin, status_filter, q, limit + offset,
        visible_library_ids(user))
    merged = sorted(rows + lib_rows, key=lambda r: r.get("upload_date") or "", reverse=True)[offset:offset + limit]
    total = (total_row["n"] if total_row else len(rows)) + lib_total
    return {"sources": merged, "count": len(merged), "total": total}


@router.get("/supported-types")
async def supported_types(user: Dict[str, Any] = Depends(require_auth)):
    """The single list of indexable extensions, for upload pickers."""
    return {
        "document": sorted(DOCUMENT_EXTENSIONS),
        "image": sorted(IMAGE_EXTENSIONS),
        "video": sorted(VIDEO_EXTENSIONS),
        "audio": sorted(AUDIO_EXTENSIONS),
        "all": sorted(SUPPORTED_EXTENSIONS),
        "accept": ",".join(f".{e}" for e in sorted(SUPPORTED_EXTENSIONS)),
    }


@router.post("/check-conflicts", response_model=CheckConflictsResponse)
async def check_conflicts(
    req: CheckConflictsRequest,
    user: Dict[str, Any] = Depends(require_admin)
):
    """
    Checks whether files with the given names already exist in the repository.
    Returns conflicts list with suggested unique filenames (e.g. 'file (1).pdf').
    """
    kb_dir = settings.resolved_kb_dir
    conflicts: List[ConflictItem] = []
    reserved_batch: set = set()

    existing_rows = db_all("SELECT original_name FROM knowledge_sources")
    existing_db_names = {r["original_name"].lower() for r in existing_rows}

    for fname in req.filenames:
        if not fname or not fname.strip():
            continue
        clean_name = sanitize_filename(fname.strip())
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


@router.post("/upload")
async def upload_source(
    request: Request,
    user: Dict[str, Any] = Depends(require_admin)
):
    # No size or file-count limit: each file is streamed to disk in 1 MB blocks.
    form = await request.form(max_files=float("inf"), max_fields=float("inf"))
    resolve_duplicates = str(form.get("resolve_duplicates", "false")).lower() in ("true", "1", "yes")

    all_files: List[UploadFile] = []
    for key in ["files", "file"]:
        for item in form.getlist(key):
            if hasattr(item, "filename") and item.filename:
                all_files.append(item)

    if not all_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided for upload."
        )

    # Uploads go to the Uploads library, streamed to disk under their real names and
    # indexed like any other library file (searched together with every library).
    results = []
    for uploaded_file in all_files:
        original_name = sanitize_filename(uploaded_file.filename or "uploaded_file")
        try:
            result = await run_in_threadpool(
                compat.save_upload, uploaded_file.file, original_name, user["id"], resolve_duplicates)
            results.append(result)
        except Exception as e:
            results.append({"filename": original_name, "error": str(e)})
        finally:
            try:
                await uploaded_file.close()
            except Exception:
                pass
    if any("source" in r for r in results):
        _wake_indexer()

    first_source = next((r["source"] for r in results if "source" in r), None)
    return {
        "success": any("source" in r for r in results),
        "results": results,
        "source": first_source,
    }


@router.post("/sync")
@router.get("/sync")
async def sync_folder(user: Dict[str, Any] = Depends(require_admin)):
    """Rescan every library folder (new, changed, renamed and deleted files)."""
    from app.library.service import get_library_service
    service = get_library_service()
    started = [lib.name for lib in get_library_manager().online() if service.scan(lib.id)]
    return {
        "success": True,
        "message": f"Rescanning {len(started)} librar{'y' if len(started) == 1 else 'ies'}; "
                   "changes are indexed in the background.",
        "libraries": started,
    }


async def _reset_and_enqueue(source_id: str) -> None:
    await run_in_threadpool(purge_derived_data, source_id)
    db_run(
        "UPDATE knowledge_sources SET processing_status = 'uploaded', error_message = NULL, attempts = 0 WHERE id = ?",
        (source_id,)
    )
    await enqueue_source_processing(source_id)


@router.post("/reindex-all")
async def reindex_all_sources(user: Dict[str, Any] = Depends(require_admin)):
    """Re-runs ingestion for every file-based source (internet imports have no file to re-read)."""
    sources = db_all("SELECT id, file_path, metadata_json FROM knowledge_sources")
    reindexed_count = 0
    skipped_internet = 0
    for s in sources:
        if is_internet_source(s):
            skipped_internet += 1
            continue
        if is_source_queued(s["id"]):
            continue
        await _reset_and_enqueue(s["id"])
        reindexed_count += 1

    def _requeue_libraries() -> int:
        n = 0
        for lib in get_library_manager().online():
            n += lib.db.execute(
                "UPDATE sources SET status = 'queued', attempts = 0, error = NULL "
                "WHERE status NOT IN ('missing', 'excluded', 'processing')")
        return n
    library_count = await run_in_threadpool(_requeue_libraries)
    if library_count:
        _wake_indexer()
    return {"success": True, "enqueued": reindexed_count + library_count, "skippedInternet": skipped_internet}


@router.post("/repair")
async def repair_index_route(user: Dict[str, Any] = Depends(require_admin)):
    """Embed rows stored without vectors and re-insert rows missing from FTS."""
    from app.processing.repair import repair_index
    return {"success": True, **(await run_in_threadpool(repair_index))}


@router.post("/reset")
async def reset_knowledge(user: Dict[str, Any] = Depends(require_admin)):
    tables = ["document_chunks", "chunks_fts", "document_sections", "documents",
              "video_transcripts", "transcripts_fts", "video_frames", "videos",
              "face_embeddings", "images", "image_perceptual_hashes", "knowledge_sources"]

    def _reset():
        with get_db_context() as conn:
            cursor = conn.cursor()
            for t in tables:
                try:
                    cursor.execute(f"DELETE FROM {t}")
                except Exception:
                    pass
            conn.commit()

        # Only derived data is removed. The files in the uploads root are the stored
        # originals of browser uploads (and scripts/migrate_legacy.py --rollback reads
        # them); they are deleted only by migrate_legacy.py --finalize.
        upload_dir = settings.resolved_upload_dir
        for sub in ["frames", "faces", "temp", "doc_images"]:
            d = upload_dir / sub
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)

        try:
            from app.search.faiss_index import get_faiss_manager
            get_faiss_manager().clear_all()
        except Exception as e:
            print(f"[Knowledge] FAISS reset notice: {e}")

    await run_in_threadpool(_reset)

    from app.database.seed import seed_system_user, seed_demo_knowledge
    seed_system_user()
    if settings.SEED_DEMO_KNOWLEDGE:
        seed_demo_knowledge()
    return {
        "success": True,
        "message": "Legacy index cleared. Stored files were kept, and folder libraries are not affected.",
    }


@router.post("/scrape-search")
async def scrape_search(req: ScrapeSearchRequest, user: Dict[str, Any] = Depends(require_admin)):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    from app.search.providers.academic import search_papers
    from app.search.providers.news import search_news
    from app.search.providers.web import search_web
    from app.search.providers.youtube import search_videos
    from app.search.providers.images import search_internet_images

    # Run providers in parallel
    papers_res, news_res, web_res, video_res, images_res = await asyncio.gather(
        search_papers(query, {"limit": 6}),
        search_news(query, {"limit": 6}),
        search_web(query, {"limit": 6}),
        search_videos(query, {"maxResults": 6}),
        search_internet_images(query, 6),
        return_exceptions=True
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

    return {
        "query": query,
        "categories": {
            "papers": scraped_papers,
            "articles": scraped_articles,
            "news": scraped_news,
            "videos": scraped_videos,
            "images": scraped_images,
            "others": [],
        },
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
async def import_internet(req: ImportInternetRequest, user: Dict[str, Any] = Depends(require_admin)):
    if not req.sources:
        raise HTTPException(status_code=400, detail="No sources provided for import")

    # Each item becomes a Markdown file in Uploads/Internet/ — an ordinary file that is
    # indexed (and re-indexed) like any other, searched together with everything else.
    def _import_as_files() -> List[Dict[str, Any]]:
        return [compat.import_internet_item(item, user["id"]) for item in req.sources]

    imported_files = await run_in_threadpool(_import_as_files)
    if imported_files:
        _wake_indexer()
        return {"success": True, "count": len(imported_files), "imported": imported_files}

    from app.processing.processors import chunk_text, float_array_to_blob
    from app.search.model_pipeline import get_text_embeddings_batch
    from app.search.faiss_index import get_faiss_manager

    def _import() -> List[Dict[str, Any]]:
        imported = []
        faiss_mgr = get_faiss_manager()
        with get_db_context() as conn:
            cursor = conn.cursor()
            for item in req.sources:
                source_id = str(uuid.uuid4())
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
                content_text = item.fullText or item.snippet or item.title
                chunks = chunk_text(content_text, 800, 150) or [content_text]
                # Embed before writing so the transaction stays short
                embs = get_text_embeddings_batch(chunks)

                cursor.execute("""
                    INSERT INTO knowledge_sources (
                        id, filename, original_name, file_type, file_path, file_size, uploaded_by,
                        processing_status, chunk_count, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
                """, (source_id, f"internet_{source_id}", item.title, item.category or "internet", item.url,
                      len(content_text.encode("utf-8")), user["id"], len(chunks), json.dumps(meta)))

                doc_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO documents (id, source_id, title, full_text, page_count, section_count)
                    VALUES (?, ?, ?, ?, 1, 1)
                """, (doc_id, source_id, item.title, content_text))

                for idx, (ch, emb) in enumerate(zip(chunks, embs)):
                    chunk_id = str(uuid.uuid4())
                    cursor.execute("""
                        INSERT INTO document_chunks (id, doc_id, source_id, chunk_text, chunk_order, embedding, needs_reembed)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (chunk_id, doc_id, source_id, ch, idx,
                          float_array_to_blob(emb) if emb is not None else None, 0 if emb is not None else 1))
                    cursor.execute("""
                        INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id)
                        VALUES (?, ?, ?, ?)
                    """, (ch, chunk_id, source_id, doc_id))
                    if emb is not None:
                        faiss_mgr.add_text_vector(
                            source_id=source_id,
                            chunk_id=chunk_id,
                            vector=emb,
                            metadata={
                                "type": "scraped_chunk",
                                "title": item.title,
                                "url": item.url,
                                "preview": preview_text(ch),
                            }
                        )
                imported.append({"id": source_id, "title": item.title, "category": item.category})
            conn.commit()
        faiss_mgr.save_to_disk()
        return imported

    imported = await run_in_threadpool(_import)
    return {"success": True, "count": len(imported), "imported": imported}


# ─── Per-source routes ─────────────────────────────────────────────────────────

def _get_source_or_404(source_id: str, columns: str = "*") -> Dict[str, Any]:
    src = db_get(f"SELECT {columns} FROM knowledge_sources WHERE id = ?", (source_id.removeprefix("src-"),))
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    return src


@router.get("/{source_id}")
async def get_source_detail(source_id: str, user: Dict[str, Any] = Depends(require_auth)):
    found = await _library_source(source_id, user)
    if found:
        return await run_in_threadpool(compat.detail, *found)
    source_id = source_id.removeprefix("src-")
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
    if src.get("metadata_json"):
        try:
            processing_info = json.loads(src["metadata_json"]).get("processing_info")
        except Exception:
            pass
    src["metadata_json"] = _slim_metadata(src.get("metadata_json"))

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


@router.get("/{source_id}/logs")
async def get_source_logs(source_id: str, user: Dict[str, Any] = Depends(require_auth)):
    found = await _library_source(source_id, user)
    if found:
        lib, src = found
        log = await run_in_threadpool(lib.db.one, "SELECT info_json FROM source_logs WHERE source_id = ?", (src["id"],))
        return {"sourceId": src["id"], "processing_info": json.loads(log["info_json"]) if log else None}
    src = _get_source_or_404(source_id, "id, metadata_json")
    try:
        info = json.loads(src.get("metadata_json") or "{}").get("processing_info")
    except Exception:
        info = None
    return {"sourceId": src["id"], "processing_info": info}


@router.delete("/{source_id}")
async def delete_source(source_id: str, user: Dict[str, Any] = Depends(require_admin)):
    found = await _library_source(source_id)
    if found:
        return {"success": True, **(await run_in_threadpool(compat.delete, *found))}
    source_id = source_id.removeprefix("src-")
    deleted = await run_in_threadpool(purge_and_delete_source, source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"success": True, "deleted": source_id}


@router.post("/{source_id}/reprocess")
async def reprocess_source(source_id: str, user: Dict[str, Any] = Depends(require_admin)):
    found = await _library_source(source_id)
    if found:
        await run_in_threadpool(compat.reprocess, *found)
        _wake_indexer()
        return {"success": True, "reprocessing": found[1]["id"]}
    src = _get_source_or_404(source_id)
    if is_internet_source(src):
        raise HTTPException(status_code=400, detail="Internet imports have no local file to reprocess.")
    if is_source_queued(src["id"]):
        return {"success": True, "reprocessing": src["id"], "alreadyQueued": True}
    await _reset_and_enqueue(src["id"])
    return {"success": True, "reprocessing": src["id"]}


@router.api_route("/{source_id}/file", methods=["GET", "HEAD"])
async def stream_source_file(source_id: str, user: Dict[str, Any] = Depends(require_auth)):
    found = await _library_source(source_id, user)
    if found:
        lib, lsrc = found
        url = compat.internet_url(lsrc)
        if url:
            return RedirectResponse(url)
        path = await run_in_threadpool(compat.source_file, lib, lsrc)
        if path is None:
            raise HTTPException(status_code=404, detail="The file is not available (moved, deleted or its drive is offline)")
        content_type, _ = mimetypes.guess_type(lsrc["name"])
        return FileResponse(path=path, media_type=content_type or "application/octet-stream",
                            filename=lsrc["name"], content_disposition_type="inline")
    src = _get_source_or_404(source_id, "id, file_path, original_name, file_type, metadata_json")

    if is_internet_source(src):
        url = src.get("file_path") or ""
        try:
            meta = json.loads(src.get("metadata_json") or "{}")
            url = meta.get("url") or meta.get("original_url") or url
        except Exception:
            pass
        if url.startswith(("http://", "https://")):
            return RedirectResponse(url)
        raise HTTPException(status_code=404, detail="Internet source has no URL")

    file_path = Path(src["file_path"])
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Physical file not found on disk")

    content_type, _ = mimetypes.guess_type(src.get("original_name") or str(file_path))
    # Starlette's FileResponse handles Range/If-Range (seeking in audio/video), 416 for
    # unsatisfiable ranges, and RFC 5987 encoding for non-Latin filenames.
    return FileResponse(
        path=file_path,
        media_type=content_type or "application/octet-stream",
        filename=src.get("original_name") or file_path.name,
        content_disposition_type="inline",
    )


@router.get("/{source_id}/frames/{frame_id}")
async def get_video_frame(source_id: str, frame_id: str, user: Dict[str, Any] = Depends(require_auth)):
    found = await _library_source(source_id, user)
    if found:
        path = await run_in_threadpool(compat.frame, found[0], found[1], frame_id)
        if path is None:
            raise HTTPException(status_code=404, detail="Frame not found")
        return FileResponse(path=path, media_type="image/webp")
    source_id = source_id.removeprefix("src-")
    frame = db_get("SELECT frame_path FROM video_frames WHERE id = ? AND source_id = ?", (frame_id, source_id))
    if not frame or not frame.get("frame_path") or not Path(frame["frame_path"]).is_file():
        raise HTTPException(status_code=404, detail="Frame not found")
    if not is_within(frame["frame_path"], settings.resolved_upload_dir):
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(path=frame["frame_path"], media_type="image/jpeg")


@router.get("/{source_id}/faces/{face_id}")
async def get_face_crop(source_id: str, face_id: str, user: Dict[str, Any] = Depends(require_auth)):
    found = await _library_source(source_id, user)
    path = await run_in_threadpool(compat.face_crop, found[0], found[1], face_id) if found else None
    if path is None:
        raise HTTPException(status_code=404, detail="Face not found")
    return FileResponse(path=path, media_type="image/webp")


def _render_pdf_thumbnail(pdf_path: str, thumb_path: Path) -> bool:
    import fitz
    doc = fitz.open(pdf_path)
    try:
        if len(doc) == 0:
            return False
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        doc[0].get_pixmap(dpi=100).save(str(thumb_path))
        return True
    finally:
        doc.close()


@router.get("/{source_id}/thumbnail")
async def get_source_thumbnail(source_id: str, user: Dict[str, Any] = Depends(require_auth)):
    found = await _library_source(source_id, user)
    if found:
        lib, lsrc = found
        path = await run_in_threadpool(compat.thumbnail, lib, lsrc)
        if path is not None:
            ct, _ = mimetypes.guess_type(path.name)
            return FileResponse(path=path, media_type=ct or "image/webp")
        remote = json.loads(lsrc.get("meta_json") or "{}").get("remoteThumbnail")
        if isinstance(remote, str) and remote.startswith(("http://", "https://")):
            return RedirectResponse(remote)
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    src = _get_source_or_404(source_id, "id, file_type, file_path, original_name, metadata_json")
    sid = src["id"]
    file_type = (src.get("file_type") or "").lower()
    file_path = src.get("file_path") or ""
    upload_dir = settings.resolved_upload_dir

    if is_internet_source(src):
        try:
            thumb = json.loads(src.get("metadata_json") or "{}").get("thumbnail")
        except Exception:
            thumb = None
        if thumb and str(thumb).startswith(("http://", "https://")):
            return RedirectResponse(thumb)
        raise HTTPException(status_code=404, detail="Thumbnail not available")

    # 1. Video: chosen thumbnail, else first frame
    if file_type in VIDEO_EXTENSIONS:
        v = db_get("SELECT thumbnail_path FROM videos WHERE source_id = ?", (sid,))
        if v and v.get("thumbnail_path") and Path(v["thumbnail_path"]).is_file():
            return FileResponse(path=v["thumbnail_path"], media_type="image/jpeg")
        frame = db_get("SELECT frame_path FROM video_frames WHERE source_id = ? ORDER BY timestamp ASC LIMIT 1", (sid,))
        if frame and frame.get("frame_path") and Path(frame["frame_path"]).is_file():
            return FileResponse(path=frame["frame_path"], media_type="image/jpeg")

    # 2. Image: the file itself
    if file_type in IMAGE_EXTENSIONS and Path(file_path).is_file():
        ct, _ = mimetypes.guess_type(src.get("original_name") or file_path)
        return FileResponse(path=file_path, media_type=ct or "image/jpeg")

    # 3. PDF: page-1 render (cached)
    doc_img_dir = upload_dir / "doc_images" / sid
    if file_type == "pdf" and Path(file_path).is_file():
        thumb_path = doc_img_dir / "page_1_thumb.png"
        try:
            if thumb_path.is_file() or await run_in_threadpool(_render_pdf_thumbnail, file_path, thumb_path):
                return FileResponse(path=thumb_path, media_type="image/png")
        except Exception as e:
            print(f"[Knowledge] PDF thumbnail notice for {sid}: {e}")

    # 4. Other documents: first extracted image, page 1 preferred
    if doc_img_dir.exists():
        img_files = sorted(list(doc_img_dir.glob("*.png")) + list(doc_img_dir.glob("*.jpg")) + list(doc_img_dir.glob("*.jpeg")))
        if img_files:
            p1_files = [f for f in img_files if f.name.startswith("page_1_")]
            chosen = p1_files[0] if p1_files else img_files[0]
            mt = "image/png" if chosen.suffix.lower() == ".png" else "image/jpeg"
            return FileResponse(path=chosen, media_type=mt)

    raise HTTPException(status_code=404, detail="Thumbnail not available")
