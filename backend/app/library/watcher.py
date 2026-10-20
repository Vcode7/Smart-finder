"""
app/library/watcher.py
~~~~~~~~~~~~~~~~~~~~~~
Live file-system watching for folder libraries (watchdog).

Events are collected on watchdog's thread and applied by one applier thread per
library:
  * created / modified → after 2 s of quiet and a stable size (files still being
                         copied are not picked up early) the file is registered or
                         re-queued
  * moved / renamed    → paths are updated in place; nothing is re-indexed
  * deleted            → the file's (or folder's) index data is removed
  * folder moved in    → its contents are scanned (Windows reports only the folder)

Network drives get a polling observer, because change notifications are unreliable
there. Missed events (buffer overflows, sleep) are caught by the reconcile scans the
library service runs at startup and periodically. User files are never modified.
"""
from __future__ import annotations

import fnmatch
import os
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Set, Tuple

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from app.library.manager import Library
from app.library.paths import (
    DEFAULT_IGNORED_DIRS, DEFAULT_IGNORED_FILES, INDEX_DIRNAME, is_asset_dir, is_network_path,
)
from app.library.sources import (
    PRIORITY_CHANGED, add_or_update_source, file_kind, is_excluded, move_sources, remove_source,
    remove_sources_under,
)

QUIET_SECONDS = 2.0       # no events for this long before a file is examined
APPLY_INTERVAL = 1.0
POLL_INTERVAL = 30.0      # polling observer (network drives)


def _names_in(folder: Path):
    """Entry names of a folder, listed only if the caller actually iterates."""
    try:
        with os.scandir(folder) as it:
            for entry in it:
                yield entry.name
    except OSError:
        return


def _ignored_rel(rel: str, root: Optional[Path] = None) -> bool:
    parts = PurePosixPath(rel).parts
    if not parts:
        return True
    for i, part in enumerate(parts[:-1]):
        if part in DEFAULT_IGNORED_DIRS or part.startswith("."):
            return True
        if is_asset_dir(part, _names_in(root.joinpath(*parts[:i])) if root is not None else None):
            return True
    name = parts[-1]
    return name.startswith(".") or name == INDEX_DIRNAME or any(fnmatch.fnmatch(name, p) for p in DEFAULT_IGNORED_FILES)


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "LibraryWatcher"):
        self.watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in ("opened", "closed", "closed_no_write"):
            return
        try:
            self.watcher.record(event)
        except Exception as e:  # never let a bad event kill the observer thread
            print(f"[Watcher] Event notice: {e}")


class LibraryWatcher:
    def __init__(self, lib: Library, on_queued: Callable[[], None]):
        assert lib.root is not None
        self.lib = lib
        self.root = Path(lib.root)
        self.on_queued = on_queued
        self._lock = threading.Lock()
        self._pending: Dict[str, float] = {}                  # rel → time of last event
        self._sizes: Dict[str, Tuple[int, float]] = {}        # rel → (size, mtime) seen at the last check
        self._deleted: Set[str] = set()
        self._moves: List[Tuple[str, str, bool]] = []         # (old_rel, new_rel, is_dir)
        self._scan_dirs: Set[str] = set()
        self._stop = threading.Event()
        self.observer = PollingObserver(timeout=POLL_INTERVAL) if is_network_path(self.root) else Observer()
        self.observer.schedule(_Handler(self), str(self.root), recursive=True)
        self._applier = threading.Thread(target=self._apply_loop, name=f"watch-{lib.name}", daemon=True)

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        self.observer.start()
        self._applier.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.observer.stop()
            self.observer.join(timeout=5)
        except Exception:
            pass

    # ── event intake (watchdog thread) ───────────────────────────────────────
    def _rel(self, path: str) -> Optional[str]:
        try:
            return Path(path).resolve().relative_to(self.root.resolve()).as_posix()
        except (ValueError, OSError):
            return None

    def record(self, event: FileSystemEvent) -> None:
        src = self._rel(event.src_path)
        now = time.time()
        with self._lock:
            if event.event_type == "moved":
                dest = self._rel(getattr(event, "dest_path", "") or "")
                src_ok = src is not None and not _ignored_rel(src, self.root)
                dest_ok = dest is not None and not _ignored_rel(dest, self.root)
                if src_ok and dest_ok:
                    self._moves.append((src, dest, event.is_directory))
                elif src_ok:
                    self._deleted.add(src)        # renamed to an ignored name / moved out
                elif dest_ok:
                    # e.g. an upload's .smartfind-part renamed to its final name
                    if event.is_directory:
                        self._scan_dirs.add(dest)
                    else:
                        self._pending[dest] = now
                return
            if src is None or _ignored_rel(src, self.root):
                return
            if event.event_type == "deleted":
                self._deleted.add(src)
                self._pending.pop(src, None)
            elif event.is_directory:
                if event.event_type == "created":
                    self._scan_dirs.add(src)      # folders moved in arrive as a single event
            else:
                self._deleted.discard(src)
                self._pending[src] = now

    # ── applying (applier thread) ────────────────────────────────────────────
    def _apply_loop(self) -> None:
        while not self._stop.wait(APPLY_INTERVAL):
            if self.lib.db is None:
                continue
            try:
                if self._apply():
                    self.on_queued()
            except Exception as e:
                print(f"[Watcher] {self.lib.name}: {e}")

    def _take(self):
        now = time.time()
        with self._lock:
            moves, self._moves = self._moves, []
            deleted, self._deleted = self._deleted, set()
            scan_dirs, self._scan_dirs = self._scan_dirs, set()
            due = [rel for rel, t in self._pending.items() if now - t >= QUIET_SECONDS]
        return moves, deleted, scan_dirs, due

    def _apply(self) -> bool:
        lib = self.lib
        assert lib.db is not None
        queued = False
        moves, deleted, scan_dirs, due = self._take()

        for old, new, is_dir in moves:
            if not is_dir and (file_kind(new) == "unsupported" or is_excluded(lib, new)):
                deleted.add(old)          # renamed to a type we don't index, or into an excluded path
                continue
            n = move_sources(lib, old, new)
            if n == 0:
                # Not indexed under the old name: treat the destination as new
                if is_dir:
                    scan_dirs.add(new)
                else:
                    with self._lock:
                        self._pending[new] = time.time()
            elif is_dir and is_excluded(lib, new):
                remove_sources_under(lib, new)

        for rel in deleted:
            if lib.abs_path(rel).exists():
                continue  # deleted and re-created (editors save like this): the modify event handles it
            row = lib.db.one("SELECT id FROM sources WHERE rel_path = ?", (rel,))
            if row:
                remove_source(lib, row["id"])
            else:
                remove_sources_under(lib, rel)

        for rel_dir in scan_dirs:
            from app.library.scanner import iter_files
            base = lib.abs_path(rel_dir)
            if not base.is_dir():
                continue
            found = []
            for path, _size, _mtime in iter_files(base):
                try:
                    rel = lib.rel_path(path)
                except ValueError:
                    continue
                if not _ignored_rel(rel, self.root):
                    found.append(rel)
            ready = time.time() - QUIET_SECONDS
            with self._lock:
                for rel in found:
                    self._pending.setdefault(rel, ready)

        for rel in due:
            path = lib.abs_path(rel)
            try:
                st = path.stat()
            except OSError:
                with self._lock:
                    self._pending.pop(rel, None)
                self._sizes.pop(rel, None)
                continue
            if not path.is_file():
                with self._lock:
                    self._pending.pop(rel, None)
                continue
            current = (int(st.st_size), float(st.st_mtime))
            if self._sizes.get(rel) != current:
                self._sizes[rel] = current   # still changing (or first look): check again next round
                continue
            with self._lock:
                self._pending.pop(rel, None)
            self._sizes.pop(rel, None)
            if file_kind(path.name) == "unsupported":
                continue
            sid = add_or_update_source(lib, rel, current[0], current[1], origin="folder", priority=PRIORITY_CHANGED)
            if sid and lib.db.scalar("SELECT status FROM sources WHERE id = ?", (sid,)) == "queued":
                queued = True
        return queued


class WatchManager:
    """One watcher per online folder library that has watching enabled."""

    def __init__(self, on_queued: Callable[[], None]):
        self.on_queued = on_queued
        self._watchers: Dict[str, LibraryWatcher] = {}
        self._lock = threading.Lock()

    def ensure(self, lib: Library) -> None:
        if lib.is_linked or lib.root is None or not lib.watch or not lib.online:
            self.remove(lib.id)
            return
        with self._lock:
            if lib.id in self._watchers:
                return
            try:
                w = LibraryWatcher(lib, self.on_queued)
                w.start()
                self._watchers[lib.id] = w
            except Exception as e:
                print(f"[Watcher] Could not watch {lib.root}: {e}")

    def remove(self, lib_id: str) -> None:
        with self._lock:
            w = self._watchers.pop(lib_id, None)
        if w is not None:
            w.stop()

    def watching(self, lib_id: str) -> bool:
        with self._lock:
            return lib_id in self._watchers

    def stop_all(self) -> None:
        with self._lock:
            watchers, self._watchers = list(self._watchers.values()), {}
        for w in watchers:
            w.stop()
