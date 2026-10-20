"""
Folder library tests: registry, in-place indexing bookkeeping and reconcile scans.
"""
import os
import time
from pathlib import Path

import pytest


def _write(path: Path, content: str = "hello") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_builtin_libraries_exist(manager, tmp_path):
    ids = {lib.id for lib in manager.all()}
    assert {"uploads", "linked"} <= ids
    up = manager.uploads()
    assert up.root.resolve() == (tmp_path / "uploads-library").resolve()
    assert (up.index_dir / "index.db").exists()


def test_uploads_library_never_overlaps_legacy_upload_folder(tmp_db, tmp_path, monkeypatch):
    # Windows paths ignore letter case: "data/Uploads" IS the legacy "data/uploads"
    from app.core import config as cfg
    from app.library.manager import get_library_manager, reset_library_manager
    monkeypatch.setattr(cfg.settings, "UPLOADS_LIBRARY_DIR", str(tmp_path / "UPLOADS"), raising=False)
    reset_library_manager()
    try:
        m = get_library_manager()
        m.load_all()
        root = m.uploads().root.resolve()
        assert root != (tmp_path / "uploads").resolve()
        assert root.name == "uploads-library"
    finally:
        reset_library_manager()


def test_attach_creates_index_inside_folder_and_reuses_it(manager, tmp_path):
    folder = tmp_path / "My Docs"
    _write(folder / "notes.txt")
    lib = manager.attach(str(folder))
    assert lib.index_dir == folder.resolve() / ".smartfind"
    assert (lib.index_dir / "library.json").exists()

    from app.library.scanner import scan_library
    scan_library(lib)
    source_id = lib.db.scalar("SELECT id FROM sources")

    manager.detach(lib.id)                       # keep the index
    again = manager.attach(str(folder))
    assert again.id == lib.id                    # library.json identity reused
    assert again.db.scalar("SELECT id FROM sources") == source_id
    assert manager.find_source(source_id)[0].id == lib.id


def test_attach_rejects_overlaps_and_missing_folders(manager, tmp_path):
    from app.library.manager import LibraryError
    parent = tmp_path / "parent"
    (parent / "child").mkdir(parents=True)
    manager.attach(str(parent))
    with pytest.raises(LibraryError):
        manager.attach(str(parent / "child"))
    with pytest.raises(LibraryError):
        manager.attach(str(tmp_path / "does-not-exist"))
    other = tmp_path / "other"
    (other / "inner").mkdir(parents=True)
    manager.attach(str(other / "inner"))
    with pytest.raises(LibraryError):
        manager.attach(str(other))


def test_reconcile_scan(manager, tmp_path):
    from app.library.scanner import scan_library
    from app.library.sources import exclude_path
    from app.library.fingerprint import file_fingerprint

    root = tmp_path / "lib"
    _write(root / "a.txt", "alpha")
    _write(root / "sub" / "b.pdf", "pdf-ish bytes " * 100)
    _write(root / "photo.jpg", "jpeg bytes")
    _write(root / "परीक्षा.txt", "हिंदी पाठ")
    _write(root / "skip.exe", "binary")
    _write(root / ".hidden.txt", "secret")
    _write(root / "node_modules" / "x.txt", "dependency")
    lib = manager.attach(str(root))

    r = scan_library(lib)
    assert r.new == 4 and r.unsupported == 1
    rels = {row["rel_path"] for row in lib.db.all("SELECT rel_path FROM sources")}
    assert rels == {"a.txt", "sub/b.pdf", "photo.jpg", "परीक्षा.txt"}
    assert all(row["status"] == "queued" for row in lib.db.all("SELECT status FROM sources"))

    # Unchanged rescan does nothing
    assert scan_library(lib).unchanged == 4

    # Changed content re-queues
    lib.db.execute("UPDATE sources SET status = 'indexed'")
    time.sleep(0.01)
    _write(root / "a.txt", "alpha, now longer")
    os.utime(root / "a.txt", (time.time() + 5, time.time() + 5))
    r = scan_library(lib)
    assert r.changed == 1
    assert lib.db.scalar("SELECT status FROM sources WHERE rel_path = 'a.txt'") == "queued"

    # Rename is detected by fingerprint: same source id, no re-index
    b_id = lib.db.scalar("SELECT id FROM sources WHERE rel_path = 'sub/b.pdf'")
    lib.db.execute("UPDATE sources SET fingerprint = ? WHERE id = ?", (file_fingerprint(root / "sub" / "b.pdf"), b_id))
    (root / "sub" / "b.pdf").rename(root / "sub" / "renamed.pdf")
    r = scan_library(lib)
    assert r.renamed == 1 and r.removed == 0 and r.new == 0
    assert lib.db.scalar("SELECT rel_path FROM sources WHERE id = ?", (b_id,)) == "sub/renamed.pdf"
    assert lib.db.scalar("SELECT status FROM sources WHERE id = ?", (b_id,)) == "indexed"

    # Deleted file is forgotten (and the user's other files untouched)
    (root / "photo.jpg").unlink()
    r = scan_library(lib)
    assert r.removed == 1
    assert lib.db.scalar("SELECT COUNT(*) FROM sources WHERE rel_path = 'photo.jpg'") == 0

    # Excluding removes it from the index and keeps it out on rescans — file stays on disk
    exclude_path(lib, "a.txt")
    assert (root / "a.txt").exists()
    scan_library(lib)
    assert lib.db.scalar("SELECT COUNT(*) FROM sources WHERE rel_path = 'a.txt'") == 0


def test_detach_with_index_deletion_keeps_user_files(manager, tmp_path):
    folder = tmp_path / "keepme"
    f = _write(folder / "doc.txt")
    lib = manager.attach(str(folder))
    manager.detach(lib.id, delete_index=True)
    assert f.exists()
    assert not (folder / ".smartfind").exists()


def test_asset_dir_names():
    from app.library.paths import is_asset_dir
    for name in ("icon", "icons", "Icons", "phoneIcon", "mb_icon", "app-icons", "sprites", "emoji"):
        assert is_asset_dir(name), name
    for name in ("silicon", "Lexicon", "Photos", "style", "files", "large", "thumb"):
        assert not is_asset_dir(name), name
    assert is_asset_dir("thumb", ["large", "thumb"])
    assert is_asset_dir("thumbnails", ["original"])
    assert not is_asset_dir("thumb", ["thumb", "notes"])


def test_web_viewer_assets_are_not_indexed_and_old_rows_go(manager, tmp_path):
    """Flipbook exports: button icons and duplicate page thumbnails are skipped."""
    from app.library.scanner import scan_library
    from app.library.sources import add_or_update_source
    from app.library.watcher import _ignored_rel

    root = tmp_path / "lib"
    book = root / "booklet.zip_extracted"
    _write(book / "style" / "icon" / "back.png", "png")
    _write(book / "style" / "phoneIcon" / "print.png", "png")
    _write(book / "style" / "mb_icon" / "cloud.png", "png")
    _write(book / "files" / "thumb" / "1.webp", "small page")
    _write(book / "files" / "large" / "1.webp", "full page")
    _write(root / "photos" / "thumb" / "a.jpg", "no full-size sibling, kept")
    lib = manager.attach(str(root))
    # Indexed by an older version, before the rule existed
    stale = add_or_update_source(lib, "booklet.zip_extracted/style/icon/back.png", 3, time.time(), origin="folder")
    assert stale

    r = scan_library(lib)
    rels = {row["rel_path"] for row in lib.db.all("SELECT rel_path FROM sources")}
    assert rels == {"booklet.zip_extracted/files/large/1.webp", "photos/thumb/a.jpg"}
    assert r.removed == 1

    # The live watcher applies the same rule
    assert _ignored_rel("booklet.zip_extracted/style/phoneIcon/print.png", lib.root)
    assert _ignored_rel("booklet.zip_extracted/files/thumb/1.webp", lib.root)
    assert not _ignored_rel("booklet.zip_extracted/files/large/1.webp", lib.root)
    assert not _ignored_rel("photos/thumb/a.jpg", lib.root)


def test_an_index_from_before_folders_gains_the_folder_column(tmp_path):
    import sqlite3
    from app.library.db import LibraryDB
    from app.library.schema import MIGRATIONS, SCHEMA_VERSION
    path = tmp_path / "old" / "index.db"
    path.parent.mkdir()
    c = sqlite3.connect(str(path))
    for i, step in enumerate(MIGRATIONS[:3]):     # a schema-3 index, as made before v4
        c.executescript(f"BEGIN;\n{step}\nPRAGMA user_version = {i + 1};\nCOMMIT;")
    for rel in ("top.txt", "Events/Diwali 2023/Day 1/a.jpg", r"C:\Pictures\Goa\b.jpg"):
        c.execute("INSERT INTO sources (id, rel_path, name, ext, kind) VALUES (?, ?, 'x', 'txt', 'document')", (rel, rel))
    c.commit()
    c.close()
    db = LibraryDB(path)
    try:
        assert db.scalar("PRAGMA user_version") == SCHEMA_VERSION
        folders = {r["id"]: r["folder"] for r in db.all("SELECT id, folder FROM sources")}
        assert folders == {"top.txt": "", "Events/Diwali 2023/Day 1/a.jpg": "Events/Diwali 2023/Day 1",
                           r"C:\Pictures\Goa\b.jpg": "C:/Pictures/Goa"}
        plan = " ".join(r["detail"] for r in db.all(
            "EXPLAIN QUERY PLAN SELECT id FROM sources WHERE folder >= 'Events/' AND folder < 'Events0'"))
        assert "idx_sources_folder" in plan
    finally:
        db.close()
