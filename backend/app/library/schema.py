"""
app/library/schema.py
~~~~~~~~~~~~~~~~~~~~~
Schema of a library's index database (<folder>/.smartfind/index.db).

Versioned with PRAGMA user_version; MIGRATIONS[i] upgrades version i -> i + 1.
All searchable text lives in `chunks` (body text, OCR, captions, transcript windows,
frame OCR) with an FTS5 index kept in sync by triggers, so orphan rows cannot exist.
Audio is transcribed in a separate pass after a file's text and images are indexed
(sources.transcript), so Whisper never competes with the other models for VRAM.
`vectors` is the source of truth for every embedding (float16); FAISS indexes are
rebuildable caches keyed by vectors.id.
"""
from typing import List

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    id           TEXT PRIMARY KEY,
    rel_path     TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    ext          TEXT NOT NULL,
    kind         TEXT NOT NULL,
    size         INTEGER NOT NULL DEFAULT 0,
    mtime        REAL NOT NULL DEFAULT 0,
    fingerprint  TEXT,
    origin       TEXT NOT NULL DEFAULT 'folder',
    status       TEXT NOT NULL DEFAULT 'queued',
    priority     INTEGER NOT NULL DEFAULT 0,
    attempts     INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    page_count   INTEGER,
    duration     REAL,
    width        INTEGER,
    height       INTEGER,
    taken_at     TEXT,
    gps_lat      REAL,
    gps_lon      REAL,
    added_at     TEXT NOT NULL DEFAULT (datetime('now')),
    indexed_at   TEXT,
    uploaded_by  TEXT,
    transcript   TEXT,                       -- NULL (no audio) | pending | running | done | failed
    meta_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sources_queue ON sources(status, priority DESC, size);
CREATE INDEX IF NOT EXISTS idx_sources_transcript ON sources(transcript, priority DESC, size);
CREATE INDEX IF NOT EXISTS idx_sources_fp ON sources(fingerprint);
CREATE INDEX IF NOT EXISTS idx_sources_kind ON sources(kind);
CREATE INDEX IF NOT EXISTS idx_sources_size ON sources(size);

CREATE VIRTUAL TABLE IF NOT EXISTS sources_fts USING fts5(
    name, rel_path, content='sources', content_rowid='rowid', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS sources_ai AFTER INSERT ON sources BEGIN
    INSERT INTO sources_fts(rowid, name, rel_path) VALUES (new.rowid, new.name, new.rel_path);
END;
CREATE TRIGGER IF NOT EXISTS sources_ad AFTER DELETE ON sources BEGIN
    INSERT INTO sources_fts(sources_fts, rowid, name, rel_path) VALUES ('delete', old.rowid, old.name, old.rel_path);
END;
CREATE TRIGGER IF NOT EXISTS sources_au AFTER UPDATE OF name, rel_path ON sources BEGIN
    INSERT INTO sources_fts(sources_fts, rowid, name, rel_path) VALUES ('delete', old.rowid, old.name, old.rel_path);
    INSERT INTO sources_fts(rowid, name, rel_path) VALUES (new.rowid, new.name, new.rel_path);
END;

CREATE TABLE IF NOT EXISTS sections (
    id          TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    title       TEXT,
    page        INTEGER,
    ord         INTEGER NOT NULL DEFAULT 0,
    char_count  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sections_source ON sections(source_id);

CREATE TABLE IF NOT EXISTS chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    section_id      TEXT,
    kind            TEXT NOT NULL,
    text            TEXT NOT NULL,
    heading         TEXT,
    page            INTEGER,
    ts_start        REAL,
    ts_end          REAL,
    visual_item_id  INTEGER,
    ord             INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id, ord);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, heading, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, heading) VALUES (new.id, new.text, new.heading);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, heading) VALUES ('delete', old.id, old.text, old.heading);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE OF text, heading ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, heading) VALUES ('delete', old.id, old.text, old.heading);
    INSERT INTO chunks_fts(rowid, text, heading) VALUES (new.id, new.text, new.heading);
END;

CREATE TABLE IF NOT EXISTS transcript_segments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    ts_start    REAL NOT NULL,
    ts_end      REAL NOT NULL,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_source ON transcript_segments(source_id, ts_start);

CREATE TABLE IF NOT EXISTS visual_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    page        INTEGER,
    ts          REAL,
    cache_path  TEXT,
    width       INTEGER,
    height      INTEGER,
    caption     TEXT,
    ocr_text    TEXT,
    phash       INTEGER,
    dhash       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_visual_source ON visual_items(source_id);

CREATE TABLE IF NOT EXISTS faces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    visual_item_id  INTEGER,
    ts              REAL,
    page            INTEGER,
    bbox            TEXT,
    det_score       REAL,
    quality         REAL,
    person_id       TEXT,
    person_locked   INTEGER NOT NULL DEFAULT 0,
    crop_path       TEXT,
    track_id        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_faces_source ON faces(source_id);
CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);

CREATE TABLE IF NOT EXISTS audio_segments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    ts_start    REAL NOT NULL,
    ts_end      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audio_source ON audio_segments(source_id);

CREATE TABLE IF NOT EXISTS vectors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    space       TEXT NOT NULL,
    entity_id   INTEGER NOT NULL,
    source_id   TEXT NOT NULL,
    emb         BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vectors_space_entity ON vectors(space, entity_id);
CREATE INDEX IF NOT EXISTS idx_vectors_source ON vectors(source_id);

CREATE TABLE IF NOT EXISTS vector_state (
    space              TEXT PRIMARY KEY,
    checkpoint_max_id  INTEGER NOT NULL DEFAULT 0,
    index_kind         TEXT,
    dim                INTEGER,
    model              TEXT
);

CREATE TABLE IF NOT EXISTS vector_tombstones (
    space   TEXT NOT NULL,
    vec_id  INTEGER NOT NULL,
    PRIMARY KEY (space, vec_id)
);

CREATE TABLE IF NOT EXISTS upload_sessions (
    id             TEXT PRIMARY KEY,
    rel_path       TEXT NOT NULL,
    part_path      TEXT NOT NULL,
    size           INTEGER NOT NULL,
    received       INTEGER NOT NULL DEFAULT 0,
    last_modified  REAL,
    created_by     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS exclusions (
    pattern     TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS source_logs (
    source_id  TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    info_json  TEXT NOT NULL
);
"""

# v2: enrichment passes that run after a file's text and images are indexed
#   captions — Florence-2 descriptions (and on-screen text for video frames)
#   sounds   — CLAP embeddings of the soundtrack in 10 s windows ("dog barking")
SCHEMA_V2 = """
ALTER TABLE sources ADD COLUMN captions TEXT;     -- NULL | pending | running | done | failed
ALTER TABLE sources ADD COLUMN sounds TEXT;       -- NULL | pending | running | done | failed
CREATE INDEX IF NOT EXISTS idx_sources_captions ON sources(captions, priority DESC, size);
CREATE INDEX IF NOT EXISTS idx_sources_sounds ON sources(sounds, priority DESC, size);
UPDATE sources SET captions = 'pending'
 WHERE status = 'indexed'
   AND EXISTS (SELECT 1 FROM visual_items v WHERE v.source_id = sources.id AND v.kind != 'page');
UPDATE sources SET sounds = 'pending' WHERE status = 'indexed' AND transcript IS NOT NULL;
"""

# v3: image vectors re-made after the image model changes (the "images" pass)
SCHEMA_V3 = """
ALTER TABLE sources ADD COLUMN image_vectors TEXT;   -- NULL | pending | running | done | failed
CREATE INDEX IF NOT EXISTS idx_sources_image_vectors ON sources(image_vectors, priority DESC, size);
"""

# v4: each source's folder (parent of rel_path, '' at the top level), derived from the
# path so renames and moves need no upkeep; search matches folder names in queries
SCHEMA_V4 = r"""
ALTER TABLE sources ADD COLUMN folder TEXT GENERATED ALWAYS AS (
    rtrim(rtrim(replace(rel_path, '\', '/'), replace(replace(rel_path, '\', '/'), '/', '')), '/')
) VIRTUAL;
CREATE INDEX IF NOT EXISTS idx_sources_folder ON sources(folder);
"""

# v5: what a file is about, cached per source (topics from the indexed text, or from the
# LLM when the file was summarised). `fingerprint` ties the row to the file's content, so a
# changed file is re-derived; an 'llm' row is never replaced by an 'index' one.
SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS source_insights (
    source_id    TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    fingerprint  TEXT,
    topics_json  TEXT NOT NULL DEFAULT '[]',
    events_json  TEXT NOT NULL DEFAULT '[]',
    summary      TEXT,
    origin       TEXT NOT NULL DEFAULT 'index',     -- index | llm
    model        TEXT,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# MIGRATIONS[i] upgrades a database at user_version i to i + 1.
MIGRATIONS: List[str] = [SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5]

SCHEMA_VERSION = len(MIGRATIONS)
