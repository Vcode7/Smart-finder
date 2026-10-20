import sqlite3
import os
import contextlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Generator, Tuple
from app.core.config import settings

def dict_factory(cursor: sqlite3.Cursor, row: Tuple[Any, ...]) -> Dict[str, Any]:
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}

def get_db_path() -> Path:
    p = settings.resolved_db_path
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def create_connection() -> sqlite3.Connection:
    path = get_db_path()
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

@contextlib.contextmanager
def get_db_context() -> Generator[sqlite3.Connection, None, None]:
    conn = create_connection()
    try:
        yield conn
    finally:
        conn.close()

def db_get(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchone()

def db_all(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchall()

def db_run(sql: str, params: tuple = ()) -> int:
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount

def run_migrations() -> None:
    from app.database.migrations import MIGRATIONS
    with get_db_context() as conn:
        cursor = conn.cursor()
        for stmt in MIGRATIONS:
            try:
                cursor.execute(stmt)
            except Exception as e:
                msg = str(e).lower()
                if "fts5" not in msg and "duplicate column" not in msg:
                    print(f"[DB] Notice on migration: {msg}")
        conn.commit()
        _migrate_chat_context_types(conn)


def _migrate_chat_context_types(conn: sqlite3.Connection) -> None:
    """Rebuild chat_context when its CHECK constraint predates the 'audio' context type."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'chat_context'"
    ).fetchone()
    if not row or "'audio'" in (row.get("sql") or ""):
        return
    print("[DB] Migrating chat_context to accept the 'audio' context type...")
    conn.executescript("""
        BEGIN;
        CREATE TABLE chat_context_new (
            id              TEXT PRIMARY KEY,
            chat_id         TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            context_type    TEXT NOT NULL CHECK(context_type IN ('document','video','image','audio','web')),
            context_ref_id  TEXT NOT NULL,
            relevance_score REAL DEFAULT 0.0,
            snippet         TEXT,
            metadata_json   TEXT DEFAULT '{}',
            added_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO chat_context_new
            (id, chat_id, context_type, context_ref_id, relevance_score, snippet, metadata_json, added_at)
            SELECT id, chat_id, context_type, context_ref_id, relevance_score, snippet, metadata_json, added_at
            FROM chat_context;
        DROP TABLE chat_context;
        ALTER TABLE chat_context_new RENAME TO chat_context;
        CREATE INDEX IF NOT EXISTS idx_context_chat ON chat_context(chat_id);
        COMMIT;
    """)


def get_app_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve an application setting value from SQLite."""
    try:
        row = db_get("SELECT value FROM app_settings WHERE key = ?", (key,))
        return row["value"] if row else default
    except Exception:
        return default


def set_app_setting(key: str, value: str) -> None:
    """Save an application setting value to SQLite (upsert)."""
    db_run(
        """INSERT INTO app_settings (key, value, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')""",
        (key, value)
    )

