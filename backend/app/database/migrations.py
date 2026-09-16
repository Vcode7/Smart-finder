from typing import List

MIGRATIONS: List[str] = [
    # --- Users ---
    """CREATE TABLE IF NOT EXISTS users (
        id            TEXT PRIMARY KEY,
        email         TEXT UNIQUE NOT NULL,
        username      TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role          TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'admin')),
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    # --- Knowledge Sources ---
    """CREATE TABLE IF NOT EXISTS knowledge_sources (
        id                TEXT PRIMARY KEY,
        filename          TEXT NOT NULL,
        original_name     TEXT NOT NULL,
        file_type         TEXT NOT NULL,
        file_path         TEXT NOT NULL,
        file_size         INTEGER NOT NULL,
        upload_date       TEXT NOT NULL DEFAULT (datetime('now')),
        uploaded_by       TEXT NOT NULL REFERENCES users(id),
        processing_status TEXT NOT NULL DEFAULT 'uploaded'
                          CHECK(processing_status IN ('uploaded','processing','indexing','completed','failed')),
        error_message     TEXT,
        metadata_json     TEXT DEFAULT '{}',
        tags_json         TEXT DEFAULT '[]',
        chunk_count       INTEGER DEFAULT 0,
        transcript_count  INTEGER DEFAULT 0,
        face_count        INTEGER DEFAULT 0,
        frame_count       INTEGER DEFAULT 0,
        duration_seconds  REAL,
        page_count        INTEGER
    )""",

    # --- Documents ---
    """CREATE TABLE IF NOT EXISTS documents (
        id            TEXT PRIMARY KEY,
        source_id     TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
        title         TEXT,
        full_text     TEXT NOT NULL,
        page_count    INTEGER DEFAULT 1,
        section_count INTEGER DEFAULT 0
    )""",

    """CREATE TABLE IF NOT EXISTS document_sections (
        id            TEXT PRIMARY KEY,
        doc_id        TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        source_id     TEXT NOT NULL,
        section_title TEXT,
        section_text  TEXT NOT NULL,
        page_num      INTEGER DEFAULT 1,
        order_idx     INTEGER NOT NULL DEFAULT 0
    )""",

    """CREATE TABLE IF NOT EXISTS document_chunks (
        id           TEXT PRIMARY KEY,
        section_id   TEXT REFERENCES document_sections(id) ON DELETE CASCADE,
        doc_id       TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        source_id    TEXT NOT NULL,
        chunk_text   TEXT NOT NULL,
        chunk_order  INTEGER NOT NULL DEFAULT 0,
        page_num     INTEGER DEFAULT 1,
        embedding_id TEXT,
        embedding    BLOB
    )""",

    # FTS5 virtual table for keyword search on chunks
    """CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        chunk_text,
        chunk_id UNINDEXED,
        source_id UNINDEXED,
        doc_id UNINDEXED
    )""",

    # --- Videos ---
    """CREATE TABLE IF NOT EXISTS videos (
        id             TEXT PRIMARY KEY,
        source_id      TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
        duration       REAL,
        resolution     TEXT,
        format         TEXT,
        thumbnail_path TEXT
    )""",

    """CREATE TABLE IF NOT EXISTS video_transcripts (
        id           TEXT PRIMARY KEY,
        video_id     TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
        source_id    TEXT NOT NULL,
        start_time   REAL NOT NULL,
        end_time     REAL NOT NULL,
        text         TEXT NOT NULL,
        embedding_id TEXT,
        embedding    BLOB
    )""",

    # FTS5 for transcript keyword search
    """CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
        text,
        transcript_id UNINDEXED,
        video_id UNINDEXED,
        source_id UNINDEXED,
        start_time UNINDEXED,
        end_time UNINDEXED
    )""",

    """CREATE TABLE IF NOT EXISTS video_frames (
        id                 TEXT PRIMARY KEY,
        video_id           TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
        source_id          TEXT NOT NULL,
        timestamp          REAL NOT NULL,
        frame_number       INTEGER DEFAULT 0,
        scene_id           INTEGER DEFAULT 0,
        frame_path         TEXT NOT NULL,
        ocr_text           TEXT,
        visual_description TEXT,
        embedding          BLOB,
        created_at         TEXT DEFAULT (datetime('now'))
    )""",

    # --- Images ---
    """CREATE TABLE IF NOT EXISTS images (
        id           TEXT PRIMARY KEY,
        source_id    TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
        width        INTEGER,
        height       INTEGER,
        ocr_text     TEXT,
        description  TEXT,
        embedding_id TEXT,
        embedding    BLOB
    )""",

    # --- Face Embeddings ---
    """CREATE TABLE IF NOT EXISTS face_embeddings (
        id          TEXT PRIMARY KEY,
        source_id   TEXT NOT NULL,
        video_id    TEXT,
        image_id    TEXT,
        frame_id    TEXT,
        timestamp   REAL,
        embedding   BLOB NOT NULL,
        confidence  REAL NOT NULL DEFAULT 0.0,
        bbox_json   TEXT
    )""",

    # --- Chats ---
    """CREATE TABLE IF NOT EXISTS chats (
        id          TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title       TEXT NOT NULL DEFAULT 'New Chat',
        search_mode TEXT NOT NULL DEFAULT 'internet'
                    CHECK(search_mode IN ('local','internet','both')),
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS chat_messages (
        id             TEXT PRIMARY KEY,
        chat_id        TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
        role           TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
        content        TEXT NOT NULL,
        citations_json TEXT DEFAULT '[]',
        created_at     TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS chat_context (
        id              TEXT PRIMARY KEY,
        chat_id         TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
        context_type    TEXT NOT NULL CHECK(context_type IN ('document','video','image','web')),
        context_ref_id  TEXT NOT NULL,
        relevance_score REAL DEFAULT 0.0,
        snippet         TEXT,
        metadata_json   TEXT DEFAULT '{}',
        added_at        TEXT NOT NULL DEFAULT (datetime('now'))
    )""",

    # --- Perceptual Hashes (pHash + dHash) ---
    """CREATE TABLE IF NOT EXISTS image_perceptual_hashes (
        id          TEXT PRIMARY KEY,
        source_id   TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
        entity_id   TEXT NOT NULL,
        image_path  TEXT NOT NULL,
        phash       TEXT NOT NULL,
        dhash       TEXT NOT NULL,
        image_type  TEXT NOT NULL,
        page_num    INTEGER,
        timestamp   REAL,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",

    # --- Indexes ---
    "CREATE INDEX IF NOT EXISTS idx_ks_user ON knowledge_sources(uploaded_by)",
    "CREATE INDEX IF NOT EXISTS idx_ks_status ON knowledge_sources(processing_status)",
    "CREATE INDEX IF NOT EXISTS idx_dc_source ON document_chunks(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_dc_doc ON document_chunks(doc_id)",
    "CREATE INDEX IF NOT EXISTS idx_vt_video ON video_transcripts(video_id)",
    "CREATE INDEX IF NOT EXISTS idx_vf_video ON video_frames(video_id)",
    "CREATE INDEX IF NOT EXISTS idx_vf_source ON video_frames(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_fe_source ON face_embeddings(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_iph_source ON image_perceptual_hashes(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_iph_phash ON image_perceptual_hashes(phash)",
    "CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_chat ON chat_messages(chat_id)",
    "CREATE INDEX IF NOT EXISTS idx_context_chat ON chat_context(chat_id)",
    # --- Repair tracking columns (added for audit remediation) ---
    # needs_reembed = 1: embedding was skipped (model unavailable at ingest time)
    # fts_synced    = 0: FTS5 insert failed — needs repair sweep
    "ALTER TABLE document_chunks ADD COLUMN needs_reembed INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE document_chunks ADD COLUMN fts_synced INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE video_transcripts ADD COLUMN needs_reembed INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE video_transcripts ADD COLUMN fts_synced INTEGER NOT NULL DEFAULT 1",

    # Perceptual hash prefix bucket for pre-filtering (audit issue #12)
    "ALTER TABLE image_perceptual_hashes ADD COLUMN phash_prefix INTEGER",
    "CREATE INDEX IF NOT EXISTS idx_iph_phash_prefix ON image_perceptual_hashes(phash_prefix)",

    # App Settings (key-value store for user-configured options like Ollama model)
    """CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT DEFAULT (datetime('now'))
    )""",
]

