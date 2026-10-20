"""
app/library/manager.py
~~~~~~~~~~~~~~~~~~~~~~
Registry of folder libraries.

A library is a folder whose files are indexed in place. Its index lives inside the
folder (<folder>/.smartfind/: index.db, vectors/, cache/, library.json) so it moves
with the folder; read-only folders keep the index under LIBRARY_FALLBACK_DIR.

Built-in libraries:
  * Uploads — receives browser uploads (default backend/data/uploads-library)
  * Linked  — individual local files added from anywhere, indexed in place by absolute path

User files are never modified or deleted by this module.
"""
from __future__ import annotations

import json
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.files import is_within
from app.database.session import db_all, db_get, db_run, get_db_context
from app.library.db import LibraryDB
from app.library.paths import INDEX_DIRNAME, from_rel, hide_directory, to_rel
from app.library.schema import SCHEMA_VERSION
from app.library.vector_store import VectorStore

UPLOADS_LIBRARY_ID = "uploads"
LINKED_LIBRARY_ID = "linked"


class LibraryError(ValueError):
    """User-facing problem with a library operation (bad path, overlap, ...)."""


@dataclass
class Library:
    id: str
    name: str
    kind: str                       # folder | uploads | linked
    root: Optional[Path]            # None for the linked library
    index_dir: Path
    watch: bool = True
    paused: bool = False
    db: Optional[LibraryDB] = None
    vectors: Optional[VectorStore] = None
    error: Optional[str] = None
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def is_linked(self) -> bool:
        return self.kind == "linked"

    @property
    def online(self) -> bool:
        if self.db is None:
            return False
        return self.is_linked or (self.root is not None and self.root.is_dir())

    @property
    def cache_dir(self) -> Path:
        return self.index_dir / "cache"

    def abs_path(self, rel_path: str) -> Path:
        if self.is_linked:
            return Path(rel_path)
        assert self.root is not None
        return from_rel(self.root, rel_path)

    def rel_path(self, path: Path) -> str:
        if self.is_linked:
            return str(Path(path).resolve())
        assert self.root is not None
        return to_rel(self.root, path)

    def contains(self, path: Path) -> bool:
        return (not self.is_linked) and self.root is not None and is_within(path, self.root)

    def source_cache_dir(self, source_id: str) -> Path:
        return self.cache_dir / source_id[:2] / source_id

    def open(self) -> None:
        with self._lock:
            if self.db is not None:
                return
            self.index_dir.mkdir(parents=True, exist_ok=True)
            self.db = LibraryDB(self.index_dir / "index.db")
            self.vectors = VectorStore(self.db, self.index_dir / "vectors")
            self.error = None

    def close(self) -> None:
        with self._lock:
            if self.vectors is not None:
                try:
                    self.vectors.checkpoint()
                except Exception as e:  # e.g. the drive was unplugged
                    print(f"[Libraries] {self.name}: final checkpoint skipped ({e})")
            if self.db is not None:
                self.db.close()
            self.db = None
            self.vectors = None

    def summary(self) -> Dict[str, object]:
        out: Dict[str, object] = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "path": str(self.root) if self.root else None,
            "indexPath": str(self.index_dir),
            "online": self.online,
            "watch": self.watch,
            "paused": self.paused,
            "error": self.error,
        }
        if self.db is not None:
            counts = {r["status"]: r["n"] for r in self.db.all(
                "SELECT status, COUNT(*) AS n FROM sources GROUP BY status"
            )}
            out["counts"] = counts
            out["total"] = sum(counts.values())
            out["bytes"] = int(self.db.scalar(
                "SELECT COALESCE(SUM(size), 0) FROM sources WHERE status NOT IN ('excluded', 'missing')", (), 0
            ))
            out["vectors"] = self.vectors.stats() if self.vectors else {}
        return out


def _writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write-test-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


class LibraryManager:
    def __init__(self) -> None:
        self._libs: Dict[str, Library] = {}
        self._lock = threading.RLock()

    # ── loading ──────────────────────────────────────────────────────────────
    def load_all(self) -> None:
        self._ensure_builtins()
        for row in db_all("SELECT * FROM libraries ORDER BY created_at"):
            if row["id"] in self._libs:
                continue
            lib = Library(
                id=row["id"],
                name=row["name"],
                kind=row["kind"],
                root=Path(row["root_path"]) if row["root_path"] else None,
                index_dir=Path(row["index_path"]),
                watch=bool(row["watch"]),
                paused=bool(row["paused"]),
            )
            self._open_library(lib)
            with self._lock:
                self._libs[lib.id] = lib

    def _open_library(self, lib: Library) -> None:
        if not lib.is_linked and (lib.root is None or not lib.root.is_dir()):
            lib.error = "Folder is not available (moved, renamed or on a disconnected drive)"
            return
        try:
            lib.open()
            if not lib.is_linked and lib.index_dir.name == INDEX_DIRNAME:
                hide_directory(lib.index_dir)
        except Exception as e:
            lib.error = f"Could not open the library index: {e}"
            print(f"[Libraries] {lib.name}: {lib.error}")

    def _ensure_builtins(self) -> None:
        if not db_get("SELECT id FROM libraries WHERE id = ?", (UPLOADS_LIBRARY_ID,)):
            root = settings.resolved_uploads_library_dir
            legacy = [settings.resolved_upload_dir, settings.resolved_kb_dir]
            if any(is_within(root, d) or is_within(d, root) for d in legacy):
                # The legacy stores hold the app's own uuid-named copies; indexing them as a
                # library would duplicate everything (Windows paths ignore letter case).
                fallback = settings.resolved_upload_dir.parent / "uploads-library"
                print(f"[Libraries] UPLOADS_LIBRARY_DIR overlaps the legacy upload folders; using {fallback}")
                root = fallback
            root.mkdir(parents=True, exist_ok=True)
            self._insert_row(UPLOADS_LIBRARY_ID, "Uploads", "uploads", root, self._index_dir_for(root, UPLOADS_LIBRARY_ID))
        if not db_get("SELECT id FROM libraries WHERE id = ?", (LINKED_LIBRARY_ID,)):
            index_dir = settings.resolved_library_fallback_dir / LINKED_LIBRARY_ID
            self._insert_row(LINKED_LIBRARY_ID, "Linked files", "linked", None, index_dir, watch=False)

    @staticmethod
    def _insert_row(lib_id: str, name: str, kind: str, root: Optional[Path], index_dir: Path, watch: bool = True) -> None:
        db_run(
            "INSERT INTO libraries (id, name, kind, root_path, index_path, watch) VALUES (?, ?, ?, ?, ?, ?)",
            (lib_id, name, kind, str(root) if root else None, str(index_dir), 1 if watch else 0),
        )

    @staticmethod
    def _index_dir_for(root: Path, lib_id: str) -> Path:
        candidate = root / INDEX_DIRNAME
        if _writable(candidate):
            return candidate
        return settings.resolved_library_fallback_dir / lib_id

    # ── queries ──────────────────────────────────────────────────────────────
    def get(self, lib_id: str) -> Optional[Library]:
        with self._lock:
            return self._libs.get(lib_id)

    def require(self, lib_id: str) -> Library:
        lib = self.get(lib_id)
        if lib is None:
            raise LibraryError(f"Unknown library '{lib_id}'")
        if not lib.online:
            raise LibraryError(f"Library '{lib.name}' is offline: {lib.error or 'folder unavailable'}")
        return lib

    def all(self) -> List[Library]:
        with self._lock:
            return list(self._libs.values())

    def online(self) -> List[Library]:
        return [lib for lib in self.all() if lib.online]

    def uploads(self) -> Library:
        return self.require(UPLOADS_LIBRARY_ID)

    def linked(self) -> Library:
        return self.require(LINKED_LIBRARY_ID)

    def library_for_path(self, path: Path) -> Library:
        """The library whose folder contains `path`, else the Linked library."""
        for lib in self.online():
            if lib.contains(path):
                return lib
        return self.linked()

    # ── attach / detach ──────────────────────────────────────────────────────
    def attach(self, path: str, name: Optional[str] = None) -> Library:
        root = Path(path).expanduser()
        try:
            root = root.resolve(strict=True)
        except OSError:
            raise LibraryError(f"Folder not found: {path}")
        if not root.is_dir():
            raise LibraryError(f"Not a folder: {path}")
        if root.parent == root:
            raise LibraryError("Choose a folder, not the root of a drive")
        for lib in self.all():
            if lib.root is None:
                continue
            if is_within(root, lib.root):
                raise LibraryError(f"This folder is already inside the library '{lib.name}'")
            if is_within(lib.root, root):
                raise LibraryError(f"This folder contains the library '{lib.name}'; detach it first")

        # Re-attaching a folder that already carries an index reuses its library id
        lib_id = None
        manifest = root / INDEX_DIRNAME / "library.json"
        if manifest.exists():
            try:
                lib_id = json.loads(manifest.read_text(encoding="utf-8")).get("id")
            except Exception:
                lib_id = None
        if lib_id:
            existing = self.get(lib_id)
            if existing is not None:
                if existing.root is not None and not existing.root.is_dir():
                    # The same library came back at a new path (new drive letter, moved folder)
                    return self.relocate(existing, root)
                raise LibraryError(
                    f"This folder's index belongs to the library '{existing.name}' at {existing.root} "
                    f"(the folder was probably copied). Delete the {INDEX_DIRNAME} folder inside the copy "
                    f"to index it as a separate library."
                )
        if not lib_id or db_get("SELECT id FROM libraries WHERE id = ?", (lib_id,)):
            lib_id = str(uuid.uuid4())

        index_dir = self._index_dir_for(root, lib_id)
        display = (name or "").strip() or root.name
        self._insert_row(lib_id, display, "folder", root, index_dir)
        lib = Library(id=lib_id, name=display, kind="folder", root=root, index_dir=index_dir)
        self._open_library(lib)
        if lib.error:
            db_run("DELETE FROM libraries WHERE id = ?", (lib_id,))
            raise LibraryError(lib.error)
        try:
            (index_dir / "library.json").write_text(json.dumps({
                "id": lib_id, "name": display, "schema": SCHEMA_VERSION,
            }, indent=2), encoding="utf-8")
        except OSError:
            pass
        with self._lock:
            self._libs[lib_id] = lib
        self.rebuild_locator(lib)
        return lib

    def relocate(self, lib: Library, new_root: Path) -> Library:
        """Point an offline library at its folder's new location and open it there."""
        lib.close()
        index_dir = new_root / INDEX_DIRNAME if (new_root / INDEX_DIRNAME / "index.db").exists() \
            else self._index_dir_for(new_root, lib.id)
        db_run("UPDATE libraries SET root_path = ?, index_path = ? WHERE id = ?", (str(new_root), str(index_dir), lib.id))
        lib.root, lib.index_dir, lib.error = new_root, index_dir, None
        self._open_library(lib)
        if lib.error:
            raise LibraryError(lib.error)
        self.rebuild_locator(lib)
        return lib

    def refresh(self, lib: Library) -> Optional[bool]:
        """Track a folder disappearing / reappearing. True = came online, False = went offline."""
        if lib.is_linked:
            return None
        present = lib.root is not None and lib.root.is_dir()
        if present and lib.db is None:
            self._open_library(lib)
            if lib.db is not None:
                self.rebuild_locator(lib)
                return True
            return None
        if not present and lib.db is not None:
            lib.close()
            lib.error = "Folder is not available (moved, renamed or on a disconnected drive)"
            return False
        return None

    def detach(self, lib_id: str, delete_index: bool = False) -> None:
        if lib_id in (UPLOADS_LIBRARY_ID, LINKED_LIBRARY_ID):
            raise LibraryError("Built-in libraries cannot be detached")
        lib = self.get(lib_id)
        if lib is None:
            raise LibraryError(f"Unknown library '{lib_id}'")
        lib.close()
        with self._lock:
            self._libs.pop(lib_id, None)
        with get_db_context() as conn:
            conn.execute("DELETE FROM source_locator WHERE library_id = ?", (lib_id,))
            conn.execute("DELETE FROM libraries WHERE id = ?", (lib_id,))
            conn.commit()
        if delete_index and lib.index_dir.exists():
            # Only the index folder is ever deleted — never the user's files
            if lib.index_dir.name == INDEX_DIRNAME or is_within(lib.index_dir, settings.resolved_library_fallback_dir):
                shutil.rmtree(lib.index_dir, ignore_errors=True)

    def set_flags(self, lib_id: str, paused: Optional[bool] = None, watch: Optional[bool] = None) -> Library:
        lib = self.get(lib_id)
        if lib is None:
            raise LibraryError(f"Unknown library '{lib_id}'")
        if paused is not None:
            lib.paused = paused
            db_run("UPDATE libraries SET paused = ? WHERE id = ?", (1 if paused else 0, lib_id))
        if watch is not None:
            lib.watch = watch
            db_run("UPDATE libraries SET watch = ? WHERE id = ?", (1 if watch else 0, lib_id))
        return lib

    def rename(self, lib_id: str, name: str) -> Library:
        lib = self.get(lib_id)
        if lib is None:
            raise LibraryError(f"Unknown library '{lib_id}'")
        name = (name or "").strip()
        if not name:
            raise LibraryError("The name cannot be empty")
        lib.name = name[:120]
        db_run("UPDATE libraries SET name = ? WHERE id = ?", (lib.name, lib_id))
        manifest = lib.index_dir / "library.json"
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                data["name"] = lib.name
                manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass
        return lib

    def mark_scanned(self, lib_id: str) -> None:
        db_run("UPDATE libraries SET last_scan_at = datetime('now') WHERE id = ?", (lib_id,))

    # ── source locator ───────────────────────────────────────────────────────
    def register_sources(self, lib: Library, source_ids: List[str]) -> None:
        if not source_ids:
            return
        with get_db_context() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO source_locator (source_id, library_id) VALUES (?, ?)",
                [(sid, lib.id) for sid in source_ids],
            )
            conn.commit()

    def unregister_sources(self, source_ids: List[str]) -> None:
        if not source_ids:
            return
        with get_db_context() as conn:
            conn.executemany("DELETE FROM source_locator WHERE source_id = ?", [(s,) for s in source_ids])
            conn.commit()

    def rebuild_locator(self, lib: Library) -> None:
        if lib.db is None:
            return
        ids = [r["id"] for r in lib.db.all("SELECT id FROM sources")]
        with get_db_context() as conn:
            conn.execute("DELETE FROM source_locator WHERE library_id = ?", (lib.id,))
            conn.executemany(
                "INSERT OR REPLACE INTO source_locator (source_id, library_id) VALUES (?, ?)",
                [(sid, lib.id) for sid in ids],
            )
            conn.commit()

    def find_source(self, source_id: str) -> Optional[Tuple[Library, Dict[str, object]]]:
        sid = str(source_id).removeprefix("src-")
        found = self._find_source(sid)
        if found is None:
            alias = db_get("SELECT source_id FROM source_aliases WHERE alias_id = ?", (sid,))
            if alias and alias["source_id"] != sid:
                found = self._find_source(alias["source_id"])
        return found

    def _find_source(self, sid: str) -> Optional[Tuple[Library, Dict[str, object]]]:
        row = db_get("SELECT library_id FROM source_locator WHERE source_id = ?", (sid,))
        candidates: List[Library] = []
        if row:
            lib = self.get(row["library_id"])
            if lib is not None:
                candidates.append(lib)
        candidates.extend(l for l in self.online() if l not in candidates)
        for lib in candidates:
            if lib.db is None:
                continue
            src = lib.db.one("SELECT * FROM sources WHERE id = ?", (sid,))
            if src:
                if not row or row["library_id"] != lib.id:
                    self.register_sources(lib, [sid])
                return lib, src
        return None

    def checkpoint_all(self) -> None:
        for lib in self.online():
            if lib.vectors is not None:
                lib.vectors.checkpoint()

    def close_all(self) -> None:
        for lib in self.all():
            lib.close()


_manager: Optional[LibraryManager] = None
_manager_lock = threading.Lock()


def get_library_manager() -> LibraryManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = LibraryManager()
    return _manager


def reset_library_manager() -> None:
    """Test helper: drop the singleton (closing open libraries)."""
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.close_all()
        _manager = None
