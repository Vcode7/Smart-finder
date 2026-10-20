"""
app/library/service.py
~~~~~~~~~~~~~~~~~~~~~~
Keeps folder libraries in sync with the disk:
  * a reconcile scan of every library at startup (in the background)
  * live watchers for folder libraries
  * folders that disappear (unplugged USB drive, network share) go offline and come
    back automatically, then get a reconcile scan
  * periodic reconcile scans catch anything the watchers missed
  * abandoned upload sessions are cleaned up
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from app.ingest.pipeline import IngestionPipeline, get_pipeline, recover_library
from app.library.manager import Library, LibraryManager, get_library_manager
from app.library.scanner import scan_library, scan_linked
from app.library.watcher import WatchManager

ONLINE_CHECK_INTERVAL = 30.0
RECONCILE_WATCHED_S = 6 * 3600      # watchers catch changes live; this catches missed events
RECONCILE_UNWATCHED_S = 30 * 60
UPLOAD_CLEANUP_INTERVAL_S = 3600


class LibraryService:
    def __init__(self, manager: Optional[LibraryManager] = None, pipeline: Optional[IngestionPipeline] = None):
        self.manager = manager or get_library_manager()
        self.pipeline = pipeline or get_pipeline()
        self.watchers = WatchManager(self.pipeline.wake)
        self._scans: Dict[str, Dict[str, Any]] = {}
        self._scan_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self, initial_scan: bool = True) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(initial_scan,), name="library-service", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.watchers.stop_all()

    # ── scans ────────────────────────────────────────────────────────────────
    def scan(self, lib_id: str, wait: bool = False) -> bool:
        """Start a reconcile scan unless one is already running. True when started."""
        with self._scan_lock:
            state = self._scans.get(lib_id)
            if state and state.get("state") == "running":
                return False
            self._scans[lib_id] = {"state": "running", "startedAt": time.time()}
        t = threading.Thread(target=self._run_scan, args=(lib_id,), name=f"scan-{lib_id[:8]}", daemon=True)
        t.start()
        if wait:
            t.join()
        return True

    def _run_scan(self, lib_id: str) -> None:
        lib = self.manager.get(lib_id)
        try:
            if lib is None or not lib.online:
                raise RuntimeError("library is offline")
            report = scan_linked(lib) if lib.is_linked else scan_library(lib)
            result: Dict[str, Any] = {"state": "done", "finishedAt": time.time(), "report": report.as_dict()}
            if report.new or report.changed:
                self.pipeline.wake()
        except Exception as e:
            result = {"state": "failed", "finishedAt": time.time(), "error": str(e)}
        with self._scan_lock:
            self._scans[lib_id] = {**self._scans.get(lib_id, {}), **result}

    def scan_state(self, lib_id: str) -> Optional[Dict[str, Any]]:
        with self._scan_lock:
            state = self._scans.get(lib_id)
            return dict(state) if state else None

    # ── library operations (keep watchers and scans in step) ─────────────────
    def attach(self, path: str, name: Optional[str] = None) -> Library:
        lib = self.manager.attach(path, name)
        recover_library(lib)
        self.watchers.ensure(lib)
        self.scan(lib.id)
        return lib

    def detach(self, lib_id: str, delete_index: bool = False) -> None:
        self.watchers.remove(lib_id)
        self.manager.detach(lib_id, delete_index=delete_index)
        with self._scan_lock:
            self._scans.pop(lib_id, None)

    def update(self, lib_id: str, paused: Optional[bool] = None, watch: Optional[bool] = None) -> Library:
        lib = self.manager.set_flags(lib_id, paused=paused, watch=watch)
        if watch is not None:
            self.watchers.ensure(lib)
            if watch:
                self.scan(lib.id)   # catch up on whatever changed while unwatched
        if paused is False:
            self.pipeline.wake()
        return lib

    # ── background loop ──────────────────────────────────────────────────────
    def _loop(self, initial_scan: bool) -> None:
        last_scan: Dict[str, float] = {}
        for lib in self.manager.online():
            self.watchers.ensure(lib)
            if initial_scan:
                self.scan(lib.id)
            last_scan[lib.id] = time.time()
        last_cleanup = 0.0
        while not self._stop.wait(ONLINE_CHECK_INTERVAL):
            try:
                now = time.time()
                for lib in self.manager.all():
                    change = self.manager.refresh(lib)
                    if change is True:
                        print(f"[Libraries] {lib.name} is back online")
                        recover_library(lib)
                        self.watchers.ensure(lib)
                        self.scan(lib.id)
                        last_scan[lib.id] = now
                    elif change is False:
                        print(f"[Libraries] {lib.name} went offline")
                        self.watchers.remove(lib.id)
                    elif lib.online:
                        interval = RECONCILE_WATCHED_S if self.watchers.watching(lib.id) else RECONCILE_UNWATCHED_S
                        if now - last_scan.get(lib.id, 0.0) >= interval:
                            self.scan(lib.id)
                            last_scan[lib.id] = now
                if now - last_cleanup >= UPLOAD_CLEANUP_INTERVAL_S:
                    from app.library.uploads import cleanup_stale_uploads
                    cleanup_stale_uploads(self.manager)
                    last_cleanup = now
            except Exception as e:
                print(f"[Libraries] Service notice: {e}")


_service: Optional[LibraryService] = None


def get_library_service() -> LibraryService:
    global _service
    if _service is None:
        _service = LibraryService()
    return _service


def reset_library_service() -> None:
    global _service
    if _service is not None:
        _service.stop()
    _service = None
