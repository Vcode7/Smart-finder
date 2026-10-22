"""
app/library/db.py
~~~~~~~~~~~~~~~~~
Connection management for a library's index.db.

- One connection per thread (SQLite connections are cheap; WAL lets readers run
  alongside the single writer).
- Writes go through `write()`, which serializes writers inside this process and
  opens BEGIN IMMEDIATE so the write lock is taken up front (no upgrade deadlocks).
- Transactions are kept short by callers: models run *before* a write starts.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from app.library.schema import MIGRATIONS, SCHEMA_VERSION


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
    return {col[0]: value for col, value in zip(cursor.description, row)}


class _ConnHolder:
    """Lives in a thread's local storage; when the thread ends, its connection is closed."""

    def __init__(self, db: "LibraryDB", conn: sqlite3.Connection):
        self.db, self.conn = db, conn

    def __del__(self) -> None:
        try:
            self.db._release(self.conn)
        except Exception:
            pass


class LibraryDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._all_conns: List[sqlite3.Connection] = []
        self._conns_lock = threading.Lock()
        self._closed = False
        self._migrate()

    # ── connections ──────────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0, check_same_thread=False, isolation_level=None)
        conn.row_factory = _dict_factory
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -32768")
        with self._conns_lock:
            self._all_conns.append(conn)
        return conn

    def conn(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError(f"Library database is closed: {self.path}")
        holder = getattr(self._local, "holder", None)
        if holder is None:
            holder = self._local.holder = _ConnHolder(self, self._connect())
        return holder.conn

    def _release(self, c: sqlite3.Connection) -> None:
        """Close the connection of a thread that has ended (indexing runs each file on a new thread)."""
        with self._conns_lock:
            if c in self._all_conns:
                self._all_conns.remove(c)
        try:
            c.close()
        except Exception:
            pass

    def close(self) -> None:
        self._closed = True
        with self._conns_lock:
            for c in self._all_conns:
                try:
                    c.close()
                except Exception:
                    pass
            self._all_conns.clear()

    # ── schema ───────────────────────────────────────────────────────────────
    def _migrate(self) -> None:
        c = self._connect()
        try:
            version = c.execute("PRAGMA user_version").fetchone()["user_version"]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"{self.path} was created by a newer version (schema {version} > {SCHEMA_VERSION})"
                )
            for target in range(version, SCHEMA_VERSION):
                # One transaction per step: a failure leaves the database at the old version
                c.executescript(f"BEGIN;\n{MIGRATIONS[target]}\nPRAGMA user_version = {target + 1};\nCOMMIT;")
        finally:
            with self._conns_lock:
                self._all_conns.remove(c)
            c.close()

    # ── queries ──────────────────────────────────────────────────────────────
    def all(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        return self.conn().execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        return self.conn().execute(sql, tuple(params)).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = self.conn().execute(sql, tuple(params)).fetchone()
        if not row:
            return default
        return next(iter(row.values()))

    @contextlib.contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Serialized write transaction (BEGIN IMMEDIATE ... COMMIT / ROLLBACK)."""
        with self._write_lock:
            c = self.conn()
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.write() as c:
            return c.execute(sql, tuple(params)).rowcount

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
