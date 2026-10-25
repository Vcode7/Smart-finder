import os
import sys

# torch and FAISS each bundle an OpenMP runtime; without this Windows aborts with OMP Error #15
# (also needed when uvicorn is started without run.py)
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# Windows consoles default to cp1252; printing a Devanagari filename would raise
# UnicodeEncodeError in the middle of ingestion. Force UTF-8 with replacement.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.database.session import run_migrations
from app.database.seed import seed_database
from app.processing.queue import (
    start_background_worker,
    recover_stale_sources,
    enqueue_pending_sources,
    spawn_background,
)
from app.database.cleanup import purge_probe_documents, purge_orphan_fts_rows, purge_stale_temp_files

from app.api.v1.auth import router as auth_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.search import router as search_router
from app.api.v1.insights import router as insights_router
from app.api.v1.ai import router as ai_router
from app.api.v1.chats import router as chats_router
from app.api.v1.settings import router as settings_router
from app.api.v1.libraries import router as libraries_router
from app.api.v1.uploads import router as uploads_router
from app.api.v1.system import router as system_router
from app.api.v1.people import router as people_router
from app.api.v1.users import router as users_router
from app.ingest.pipeline import get_pipeline
from app.library.manager import get_library_manager
from app.library.service import get_library_service


async def _startup_maintenance() -> None:
    """Slow startup work that must not delay the server becoming ready."""
    try:
        await asyncio.to_thread(purge_probe_documents)
        await asyncio.to_thread(purge_orphan_fts_rows)
        await asyncio.to_thread(purge_stale_temp_files)
    except Exception as e:
        print(f"[Backend] Startup cleanup notice: {e}")
    # The old copy-based knowledge_base folder sync is replaced by folder libraries (indexed
    # in place, watched live); running it would re-import files already migrated.
    try:
        from app.processing.repair import repair_index
        await asyncio.to_thread(repair_index)
    except Exception as e:
        print(f"[Backend] Index repair notice: {e}")
    if settings.ENVIRONMENT != "test":
        from app.search.model_pipeline import warmup_query_models
        await asyncio.to_thread(warmup_query_models)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60)
    print(f"[Backend] Starting Smart Find AI Python Backend ({settings.ENVIRONMENT})")
    print(f"[Backend] Listening on {settings.HOST}:{settings.PORT}")
    print(f"[Backend] DB Path: {settings.resolved_db_path}")
    print(f"[Backend] Uploads: {settings.resolved_upload_dir}")
    print(f"[Backend] Knowledge Base: {settings.resolved_kb_dir}")
    insecure = settings.insecure_defaults()
    if insecure:
        print(f"[Backend] WARNING: {', '.join(insecure)} still use built-in default values. "
              f"Set them in backend/.env (and change the admin password from Settings).")
    print("=" * 60)

    # 1. Run DB migrations
    run_migrations()

    # 2. Seed admin & demo knowledge
    seed_database()

    # 3. Sources interrupted by a previous shutdown go back to the queue
    recover_stale_sources()

    # 4. Start background queue worker and re-queue pending sources
    start_background_worker()
    await enqueue_pending_sources()

    # 5. Cleanup, knowledge_base folder sync and index repair, in the background
    spawn_background(_startup_maintenance())

    # 6. Folder libraries: open their indexes, start the indexing worker, then reconcile
    #    every library with the disk and watch for changes (in the background)
    manager = get_library_manager()
    await asyncio.to_thread(manager.load_all)
    for lib in manager.all():
        state = "online" if lib.online else f"offline ({lib.error})"
        print(f"[Backend] Library '{lib.name}': {lib.root or 'individual files'} — {state}")
    pipeline = get_pipeline()
    pipeline.start()
    service = get_library_service()
    service.start(initial_scan=True)

    yield

    service.stop()
    await pipeline.stop()
    await asyncio.to_thread(manager.close_all)
    print("[Backend] Shutdown complete.")

app = FastAPI(
    title="Smart Find AI API",
    description="Dedicated Python backend for multimodal knowledge search and AI research synthesis",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
origins = settings.get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers under /api prefix
app.include_router(auth_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(insights_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(chats_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(libraries_router, prefix="/api")
app.include_router(uploads_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(people_router, prefix="/api")
app.include_router(users_router, prefix="/api")

@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "groq_configured": bool(settings.get_groq_api_keys()),
        "groq_keys_count": len(settings.get_groq_api_keys()),
    }

@app.get("/")
async def root():
    return {
        "app": "Smart Find AI Python Backend",
        "docs": "/docs",
        "health": "/health",
        "status": "operational"
    }
