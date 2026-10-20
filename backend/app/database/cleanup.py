"""
app/database/cleanup.py
~~~~~~~~~~~~~~~~~~~~~~~
Startup cleanup utilities for removing known garbage/test artifacts
that can accumulate in the database, FAISS indexes and upload folders.

Currently handles:
  - Temporary validation probe files uploaded by validate_backend.py
    (temp_probe_*.txt, test_setup_smoke.txt, temp_setup_probe.txt).
  - Leaked temporary files from search queries (face crops of query images,
    query uploads in uploads/temp).
"""
import re
import shutil
import time
from typing import List

from app.core.config import settings
from app.database.session import db_all

# Patterns that identify probe/test documents — matched against original_name
_PROBE_PATTERNS: List[re.Pattern] = [
    re.compile(r"^temp_probe_\d+\.txt$", re.IGNORECASE),
    re.compile(r"^temp_setup_probe\.txt$", re.IGNORECASE),
    re.compile(r"^test_setup_smoke\.txt$", re.IGNORECASE),
]

_TEMP_MAX_AGE_SECONDS = 24 * 3600


def _is_probe(name: str) -> bool:
    return any(p.match(name) for p in _PROBE_PATTERNS)


def purge_probe_documents() -> int:
    """
    Remove validation probe documents through the shared delete routine (rows, FTS,
    vectors, upload copy and knowledge_base copy). Idempotent; runs at startup.
    Returns the number of sources purged.
    """
    try:
        rows = db_all("SELECT id, original_name FROM knowledge_sources")
    except Exception as e:
        print(f"[Cleanup] Could not query knowledge_sources: {e}")
        return 0

    probe_ids = [r["id"] for r in rows if _is_probe(r.get("original_name", ""))]
    if not probe_ids:
        return 0

    from app.processing.purge import delete_source
    for sid in probe_ids:
        try:
            delete_source(sid)
        except Exception as e:
            print(f"[Cleanup] Could not delete probe source {sid}: {e}")
    print(f"[Cleanup] Removed {len(probe_ids)} validation probe document(s).")
    return len(probe_ids)


def purge_orphan_fts_rows() -> int:
    """Delete FTS rows whose chunk/source no longer exists (left by older delete paths)."""
    from app.database.session import get_db_context
    removed = 0
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM chunks_fts WHERE chunk_id NOT IN (SELECT id FROM document_chunks)"
            )
            removed += cur.rowcount or 0
            cur.execute(
                "DELETE FROM transcripts_fts WHERE source_id NOT IN (SELECT id FROM knowledge_sources)"
            )
            removed += cur.rowcount or 0
            conn.commit()
        except Exception as e:
            print(f"[Cleanup] Orphan FTS cleanup notice: {e}")
    if removed:
        print(f"[Cleanup] Removed {removed} orphaned FTS row(s).")
    return removed


def purge_stale_temp_files() -> int:
    """Delete query-time scratch files: face crops of query images and old temp uploads."""
    upload_dir = settings.resolved_upload_dir
    removed = 0
    query_faces = upload_dir / "faces" / "query"
    if query_faces.is_dir():
        removed += sum(1 for _ in query_faces.iterdir())
        shutil.rmtree(query_faces, ignore_errors=True)

    temp_dir = upload_dir / "temp"
    if temp_dir.is_dir():
        cutoff = time.time() - _TEMP_MAX_AGE_SECONDS
        for f in temp_dir.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
    if removed:
        print(f"[Cleanup] Removed {removed} stale temporary file(s).")
    return removed
