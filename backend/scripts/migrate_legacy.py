"""
Move the old knowledge base into the Uploads library (re-indexed with the new models).

    venv\\Scripts\\python.exe scripts\\migrate_legacy.py            dry run: show what would happen
    venv\\Scripts\\python.exe scripts\\migrate_legacy.py --apply    copy files in, queue them for indexing
    venv\\Scripts\\python.exe scripts\\migrate_legacy.py --apply --index   ...and index them now
    venv\\Scripts\\python.exe scripts\\migrate_legacy.py --rollback MANIFEST
    venv\\Scripts\\python.exe scripts\\migrate_legacy.py --finalize MANIFEST --yes

--apply is non-destructive:
  * each file the app stored (data/uploads/<id>.<ext>) is COPIED into the Uploads library
    under its original name, keeping its source id, so chats and links keep working
  * byte-identical duplicates become aliases of the first copy (their ids still resolve)
  * internet imports become Markdown files in Uploads/Internet/ with their saved text
  * the old rows are only marked as migrated (hidden from the old index); nothing is deleted
  * a manifest is written to data/ so --rollback can undo all of it

--finalize deletes what the migration made redundant: the old index rows, the old vector
indexes and the app's old copies in data/uploads. Run it only after checking the results.
The backup in data/backup-* is never touched.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.files import is_within, sanitize_filename, unique_path  # noqa: E402
from app.database.session import db_all, db_get, get_db_context, run_migrations  # noqa: E402

LEGACY_TABLES = [
    "document_chunks", "chunks_fts", "document_sections", "documents", "video_transcripts", "transcripts_fts",
    "video_frames", "videos", "face_embeddings", "images", "image_perceptual_hashes",
]


def _is_internet(row: Dict[str, Any]) -> bool:
    try:
        meta = json.loads(row.get("metadata_json") or "{}")
    except Exception:
        meta = {}
    return meta.get("source_type") == "internet" or str(row.get("file_path") or "").startswith(("http://", "https://"))


def _legacy_text(source_id: str) -> str:
    doc = db_get("SELECT full_text FROM documents WHERE source_id = ? AND full_text IS NOT NULL", (source_id,))
    if doc and (doc.get("full_text") or "").strip():
        return doc["full_text"]
    return "\n\n".join(r["chunk_text"] for r in db_all(
        "SELECT chunk_text FROM document_chunks WHERE source_id = ? ORDER BY chunk_order", (source_id,)))


def _register(lib, source_id: str, target: Path, origin: str, row: Dict[str, Any], meta: Dict[str, Any]) -> None:
    """Insert a library source with a given (old) id, queued for indexing."""
    from app.library.manager import get_library_manager
    from app.library.sources import PRIORITY_SCAN, file_kind
    st = target.stat()
    rel = lib.rel_path(target)
    ext = target.suffix.lstrip(".").lower()
    lib.db.execute(
        """INSERT INTO sources (id, rel_path, name, ext, kind, size, mtime, origin, status, priority,
                                added_at, uploaded_by, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, COALESCE(?, datetime('now')), ?, ?)""",
        (source_id, rel, target.name, ext, file_kind(target.name), st.st_size, st.st_mtime, origin, PRIORITY_SCAN,
         row.get("upload_date"), row.get("uploaded_by"), json.dumps(meta)),
    )
    get_library_manager().register_sources(lib, [source_id])


def plan_and_apply(apply: bool) -> Dict[str, Any]:
    from app.library.fingerprint import file_fingerprint
    from app.library.manager import get_library_manager
    manager = get_library_manager()
    manager.load_all()
    lib = manager.uploads()
    rows = db_all("SELECT * FROM knowledge_sources WHERE id NOT IN (SELECT source_id FROM legacy_migrated) "
                  "ORDER BY upload_date, id")
    manifest: Dict[str, Any] = {"created": datetime.now().isoformat(timespec="seconds"), "library": lib.id,
                                "copied": [], "markdown": [], "aliases": [], "skipped": [], "marked": []}
    seen_fp: Dict[str, str] = {}
    counts = manifest["counts"] = {"copy": 0, "internet": 0, "duplicate": 0}
    internet_dir = lib.root / "Internet"
    for row in rows:
        sid, name = row["id"], row["original_name"] or row["filename"] or row["id"]
        if lib.db.scalar("SELECT 1 FROM sources WHERE id = ?", (sid,)):
            manifest["skipped"].append({"id": sid, "name": name, "reason": "already in a library"})
            continue
        if _is_internet(row):
            text = _legacy_text(sid)
            try:
                meta = json.loads(row.get("metadata_json") or "{}")
            except Exception:
                meta = {}
            stem = sanitize_filename(name, default="internet-source")[:120].rstrip(". ")
            target = unique_path(internet_dir, f"{stem}.md")
            print(f"  internet  {name[:70]}  ->  Internet/{target.name}")
            counts["internet"] += 1
            if apply:
                internet_dir.mkdir(parents=True, exist_ok=True)
                url = meta.get("url") or meta.get("original_url") or row.get("file_path")
                front = {"title": name, "url": url, "category": meta.get("category"), "domain": meta.get("domain"),
                         "author": meta.get("author"), "published": meta.get("publishedDate")}
                lines = ["---"] + [f"{k}: {json.dumps(str(v), ensure_ascii=False)}" for k, v in front.items() if v] + \
                        ["---", "", f"# {name}", "", (text or name).strip(), ""]
                target.write_text("\n".join(lines), encoding="utf-8")
                keep = {k: meta.get(k) for k in ("url", "original_url", "category", "domain", "platform", "author",
                                                 "publishedDate") if meta.get(k)}
                keep["source_type"] = "internet"
                if meta.get("thumbnail"):
                    keep["remoteThumbnail"] = meta["thumbnail"]
                _register(lib, sid, target, "internet", row, keep)
                manifest["markdown"].append({"id": sid, "path": str(target)})
                manifest["marked"].append(sid)
            continue
        src_path = Path(row.get("file_path") or "")
        if not src_path.is_file():
            print(f"  MISSING   {name[:70]}  ({src_path})")
            manifest["skipped"].append({"id": sid, "name": name, "reason": "file missing"})
            continue
        fp = file_fingerprint(src_path)
        if fp in seen_fp:
            print(f"  duplicate {name[:70]}  ->  same content as {seen_fp[fp][:8]}")
            counts["duplicate"] += 1
            if apply:
                with get_db_context() as conn:
                    conn.execute("INSERT OR REPLACE INTO source_aliases (alias_id, source_id) VALUES (?, ?)",
                                 (sid, seen_fp[fp]))
                    conn.commit()
                manifest["aliases"].append({"id": sid, "target": seen_fp[fp]})
                manifest["marked"].append(sid)
            continue
        seen_fp[fp] = sid
        target = unique_path(lib.root, sanitize_filename(name))
        print(f"  copy      {name[:70]}  ({src_path.stat().st_size / 1e6:.1f} MB)")
        counts["copy"] += 1
        if apply:
            part = target.with_name(target.name + ".smartfind-part")
            shutil.copy2(src_path, part)
            part.rename(target)
            _register(lib, sid, target, "upload", row, {})
            manifest["copied"].append({"id": sid, "path": str(target), "from": str(src_path)})
            manifest["marked"].append(sid)
    if apply and manifest["marked"]:
        with get_db_context() as conn:
            conn.executemany("INSERT OR IGNORE INTO legacy_migrated (source_id) VALUES (?)",
                             [(s,) for s in manifest["marked"]])
            conn.commit()
    return manifest


def rollback(manifest_path: Path) -> None:
    from app.library.manager import get_library_manager
    from app.library.sources import remove_source
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    manager = get_library_manager()
    manager.load_all()
    lib = manager.get(m["library"])
    for item in m["copied"] + m["markdown"]:
        if lib and lib.db and lib.db.scalar("SELECT 1 FROM sources WHERE id = ?", (item["id"],)):
            remove_source(lib, item["id"])
        p = Path(item["path"])
        if lib and lib.root and is_within(p, lib.root):
            p.unlink(missing_ok=True)
    with get_db_context() as conn:
        conn.executemany("DELETE FROM source_aliases WHERE alias_id = ?", [(a["id"],) for a in m["aliases"]])
        conn.executemany("DELETE FROM legacy_migrated WHERE source_id = ?", [(s,) for s in m["marked"]])
        conn.commit()
    print(f"Rolled back {len(m['copied'])} copies, {len(m['markdown'])} imports, {len(m['aliases'])} aliases.")


def finalize(manifest_path: Path) -> None:
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    marked = m["marked"]
    upload_dir = settings.resolved_upload_dir
    removed_files = 0
    for item in m["copied"]:
        old = Path(item["from"])
        if is_within(old, upload_dir) and old.is_file():
            old.unlink()
            removed_files += 1
    with get_db_context() as conn:
        for table in LEGACY_TABLES:
            try:
                conn.executemany(f"DELETE FROM {table} WHERE source_id = ?", [(s,) for s in marked])
            except Exception:
                pass
        conn.executemany("DELETE FROM knowledge_sources WHERE id = ?", [(s,) for s in marked])
        conn.executemany("DELETE FROM legacy_migrated WHERE source_id = ?", [(s,) for s in marked])
        conn.commit()
    remaining = db_get("SELECT COUNT(*) AS n FROM knowledge_sources")["n"]
    if remaining == 0:
        faiss_dir = Path(settings.resolved_db_path).parent / "faiss"
        if faiss_dir.is_dir():
            shutil.rmtree(faiss_dir, ignore_errors=True)
    print(f"Finalized: removed {removed_files} old copies and {len(marked)} old index entries"
          f"{'; old vector indexes removed' if remaining == 0 else f'; {remaining} unmigrated entries kept'}.")


def index_now() -> None:
    from app.ingest.pipeline import claim_next, finish, mark_failed, prepare, run_all_passes
    from app.library.manager import get_library_manager
    from app.people.cluster import recluster
    manager = get_library_manager()
    t0 = time.time()
    n = 0
    while (job := claim_next(manager)) is not None:
        lib, src = job
        try:
            prep = prepare(lib, src)
            try:
                finish(prep)
            finally:
                prep.extraction.cleanup()
            n += 1
            print(f"  indexed {src['rel_path']}")
        except Exception as e:
            mark_failed(lib, src, f"{type(e).__name__}: {e}")
            print(f"  FAILED  {src['rel_path']}: {e}")
    print(f"Indexed {n} files in {time.time() - t0:.0f}s; running transcription, captions and sounds...")
    print("  passes:", run_all_passes(manager))
    print("  people:", recluster(manager))
    manager.checkpoint_all()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--rollback", type=Path)
    ap.add_argument("--finalize", type=Path)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    run_migrations()
    if args.rollback:
        rollback(args.rollback)
        return
    if args.finalize:
        if not args.yes:
            sys.exit("--finalize deletes the old copies and index entries; add --yes to confirm.")
        finalize(args.finalize)
        return
    print("Legacy knowledge base → Uploads library" + ("" if args.apply else "  (dry run: nothing changes)"))
    manifest = plan_and_apply(args.apply)
    c = manifest["counts"]
    print(f"\n{'' if args.apply else 'Would make: '}{c['copy']} copies, {c['internet']} internet imports, "
          f"{c['duplicate']} duplicates as aliases, {len(manifest['skipped'])} skipped.")
    if args.apply:
        path = Path(settings.resolved_db_path).parent / f"migration-{datetime.now():%Y%m%d-%H%M%S}.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Manifest: {path}\nUndo with: scripts\\migrate_legacy.py --rollback \"{path}\"")
        if args.index:
            index_now()
        else:
            print("The backend indexes the copied files when it next runs.")
    from app.library.manager import get_library_manager
    get_library_manager().close_all()


if __name__ == "__main__":
    main()
