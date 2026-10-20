"""
app/library/scanner.py
~~~~~~~~~~~~~~~~~~~~~~
Reconcile a library's index with the files on disk.

  new file               → registered and queued
  size/mtime changed     → re-queued
  file gone              → matched by fingerprint to a new path (rename/move: paths
                           are updated, nothing is re-indexed) or forgotten
  excluded / unsupported → skipped
  web-viewer asset folder → skipped (icon folders, duplicate page thumbnails)

The walk is iterative (no recursion limits) and seen paths go to a temp table in
batches, so libraries with hundreds of thousands of files are fine. Fingerprints are
only computed for rename candidates (same size as a missing file); a normal scan
reads no file contents.
"""
from __future__ import annotations

import fnmatch
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.library.fingerprint import file_fingerprint
from app.library.manager import Library, get_library_manager
from app.library.paths import DEFAULT_IGNORED_DIRS, DEFAULT_IGNORED_FILES, is_asset_dir, is_hidden, long_path
from app.library.sources import (
    PRIORITY_CHANGED, PRIORITY_SCAN, exclusion_patterns, file_kind, is_excluded, remove_source,
)

_BATCH = 1000


@dataclass
class ScanReport:
    library_id: str
    scanned: int = 0
    new: int = 0
    changed: int = 0
    renamed: int = 0
    removed: int = 0
    unchanged: int = 0
    unsupported: int = 0
    ignored: int = 0
    errors: List[str] = field(default_factory=list)
    unreadable_dirs: List[Path] = field(default_factory=list)
    aborted: Optional[str] = None
    seconds: float = 0.0

    def as_dict(self) -> Dict[str, object]:
        out = {k: v for k, v in self.__dict__.items() if k != "unreadable_dirs"}
        out["errors"] = self.errors[:50]
        return out


def _ignored_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in DEFAULT_IGNORED_FILES)


def iter_files(root: Path, report: Optional[ScanReport] = None):
    """Yield (path, size, mtime) for every non-ignored file below root."""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(long_path(current)) as it:
                entries = list(it)
        except OSError as e:
            if report is not None:
                report.errors.append(f"{current}: {e.strerror or e}")
                report.unreadable_dirs.append(current)
            continue
        names = [e.name for e in entries]
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in DEFAULT_IGNORED_DIRS or is_hidden(entry) or is_asset_dir(entry.name, names):
                        if report is not None:
                            report.ignored += 1
                        continue
                    stack.append(current / entry.name)
                elif entry.is_file(follow_symlinks=False):
                    if _ignored_file(entry.name) or is_hidden(entry):
                        if report is not None:
                            report.ignored += 1
                        continue
                    st = entry.stat(follow_symlinks=False)
                    yield current / entry.name, st.st_size, st.st_mtime
            except OSError as e:
                if report is not None:
                    report.errors.append(f"{entry.path}: {e.strerror or e}")


def scan_library(lib: Library) -> ScanReport:
    """Full reconcile scan of a folder library (blocking; run in a thread)."""
    report = ScanReport(library_id=lib.id)
    if lib.is_linked:
        return scan_linked(lib)
    assert lib.db is not None and lib.root is not None
    t0 = time.time()
    patterns = exclusion_patterns(lib)
    manager = get_library_manager()

    conn = lib.db.conn()
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS scan_seen (rel_path TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM scan_seen")

    new_files: List[Tuple[str, int, float]] = []
    seen_batch: List[Tuple[str]] = []

    def flush_seen():
        if seen_batch:
            conn.executemany("INSERT OR IGNORE INTO scan_seen (rel_path) VALUES (?)", seen_batch)
            seen_batch.clear()

    for path, size, mtime in iter_files(lib.root, report):
        report.scanned += 1
        if file_kind(path.name) == "unsupported":
            report.unsupported += 1
            continue
        try:
            rel = lib.rel_path(path)
        except ValueError:
            continue
        if is_excluded(lib, rel, patterns):
            report.ignored += 1
            continue
        seen_batch.append((rel,))
        if len(seen_batch) >= _BATCH:
            flush_seen()
        row = lib.db.one("SELECT id, size, mtime, status FROM sources WHERE rel_path = ?", (rel,))
        if row is None:
            new_files.append((rel, size, mtime))
        elif int(row["size"]) != int(size) or abs(float(row["mtime"]) - float(mtime)) >= 1.0:
            lib.db.execute(
                """UPDATE sources SET size = ?, mtime = ?, status = 'queued', attempts = 0, error = NULL,
                   fingerprint = NULL, priority = MAX(priority, ?) WHERE id = ?""",
                (size, mtime, PRIORITY_CHANGED, row["id"]),
            )
            report.changed += 1
        else:
            report.unchanged += 1
    flush_seen()

    # Rows whose files were not found
    missing = lib.db.all(
        "SELECT id, rel_path, size, fingerprint FROM sources "
        "WHERE origin != 'internet' AND rel_path NOT IN (SELECT rel_path FROM scan_seen)"
    )

    # Rename / move detection by fingerprint (only for size matches)
    if missing and new_files:
        by_size: Dict[int, List[Dict[str, object]]] = {}
        for m in missing:
            by_size.setdefault(int(m["size"]), []).append(m)
        still_new: List[Tuple[str, int, float]] = []
        matched_ids = set()
        for rel, size, mtime in new_files:
            candidates = [m for m in by_size.get(int(size), []) if m["id"] not in matched_ids]
            if not candidates:
                still_new.append((rel, size, mtime))
                continue
            try:
                fp = file_fingerprint(lib.abs_path(rel))
            except OSError:
                still_new.append((rel, size, mtime))
                continue
            match = next((m for m in candidates if m.get("fingerprint") == fp), None)
            if match is None:
                still_new.append((rel, size, mtime))
                continue
            lib.db.execute(
                "UPDATE sources SET rel_path = ?, name = ?, mtime = ? WHERE id = ?",
                (rel, Path(rel).name, mtime, match["id"]),
            )
            matched_ids.add(match["id"])
            report.renamed += 1
        missing = [m for m in missing if m["id"] not in matched_ids]
        new_files = still_new

    # Never treat files as deleted when we simply could not look: the drive went away
    # mid-scan, or a folder was unreadable (permissions, network hiccup).
    if not lib.root.is_dir():
        report.aborted = "Folder became unavailable during the scan; nothing was removed"
        missing = []
    elif report.unreadable_dirs:
        blocked = []
        for d in report.unreadable_dirs:
            try:
                blocked.append(lib.rel_path(d))
            except ValueError:
                continue
        if "" in blocked or "." in blocked:
            missing = []
        else:
            missing = [m for m in missing
                       if not any(m["rel_path"] == b or m["rel_path"].startswith(b + "/") for b in blocked)]

    for m in missing:
        remove_source(lib, m["id"])
        report.removed += 1

    from app.library.sources import add_or_update_source
    for rel, size, mtime in new_files:
        if add_or_update_source(lib, rel, size, mtime, origin="folder", priority=PRIORITY_SCAN):
            report.new += 1

    conn.execute("DELETE FROM scan_seen")
    manager.mark_scanned(lib.id)
    report.seconds = round(time.time() - t0, 2)
    return report


def scan_linked(lib: Library) -> ScanReport:
    """Linked files are individual absolute paths: re-check each one."""
    report = ScanReport(library_id=lib.id)
    assert lib.db is not None
    t0 = time.time()
    for row in lib.db.all("SELECT id, rel_path, size, mtime FROM sources WHERE origin != 'internet'"):
        report.scanned += 1
        p = Path(row["rel_path"])
        try:
            st = p.stat()
        except OSError:
            remove_source(lib, row["id"])
            report.removed += 1
            continue
        if int(st.st_size) != int(row["size"]) or abs(st.st_mtime - float(row["mtime"])) >= 1.0:
            lib.db.execute(
                "UPDATE sources SET size = ?, mtime = ?, status = 'queued', attempts = 0, fingerprint = NULL WHERE id = ?",
                (st.st_size, st.st_mtime, row["id"]),
            )
            report.changed += 1
        else:
            report.unchanged += 1
    report.seconds = round(time.time() - t0, 2)
    return report
