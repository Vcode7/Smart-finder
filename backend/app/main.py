import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.database.session import run_migrations
from app.database.seed import seed_database
from app.processing.queue import start_background_worker, recover_stale_sources
from app.processing.folder_sync import sync_knowledge_folder

from app.api.v1.auth import router as auth_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.search import router as search_router
from app.api.v1.ai import router as ai_router
from app.api.v1.chats import router as chats_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60)
    print(f"[Backend] Starting Smart Find AI Python Backend ({settings.ENVIRONMENT})")
    print(f"[Backend] DB Path: {settings.resolved_db_path}")
    print(f"[Backend] Uploads: {settings.resolved_upload_dir}")
    print(f"[Backend] Knowledge Base: {settings.resolved_kb_dir}")
    print("=" * 60)

    # 1. Run DB migrations
    run_migrations()

    # 2. Seed admin & demo knowledge
    seed_database()

    # 3. Recover stale sources from previous ungraceful shutdowns
    recover_stale_sources()

    # 4. Start background queue worker
    start_background_worker()

    # 5. Sync knowledge_base folder
    asyncio.create_task(sync_knowledge_folder())

    yield

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
app.include_router(ai_router, prefix="/api")
app.include_router(chats_router, prefix="/api")

@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "database": str(settings.resolved_db_path),
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
