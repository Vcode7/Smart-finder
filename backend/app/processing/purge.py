"""
app/processing/purge.py
~~~~~~~~~~~~~~~~~~~~~~~
The single routine for removing what was derived from a source.

Delete, reprocess, reindex, startup cleanup and the ingestion worker all call
this, so they can no longer disagree about which tables to clear (the cause of
the orphaned FTS rows and stale vectors found in the live database).
"""
import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.files import is_within
from app.database.session import db_get, get_db_context

# Every table holding rows derived from a source. FTS tables have no foreign keys,
# so they must be cleared explicitly.
_DERIVED_DELETES = (
    "DELETE FROM chunks_fts WHERE source_id = ?",
    "DELETE FROM transcripts_fts WHERE source_id = ?",
    "DELETE FROM document_chunks WHERE source_id = ?",
    "DELETE FROM document_sections WHERE source_id = ?",
    "DELETE FROM documents WHERE source_id = ?",
    "DELETE FROM video_transcripts WHERE source_id = ?",
    "DELETE FROM video_frames WHERE source_id = ?",
    "DELETE FROM videos WHERE source_id = ?",
    "DELETE FROM face_embeddings WHERE source_id = ?",
    "DELETE FROM images WHERE source_id = ?",
    "DELETE FROM image_perceptual_hashes WHERE source_id = ?",
)

# Per-source artifact directories under UPLOAD_DIR
_DERIVED_DIRS = ("frames", "faces", "doc_images")


def is_internet_source(src: Dict[str, Any]) -> bool:
    """Internet imports have no local file: their file_path holds the URL."""
    fp = str(src.get("file_path") or "").strip().lower()
    if fp.startswith(("http://", "https://")):
        return True
    try:
        meta = json.loads(src.get("metadata_json") or "{}")
    except Exception:
        meta = {}
    return meta.get("source_type") == "internet"


def purge_derived_data(source_id: str, remove_vectors: bool = True) -> None:
    """Remove every derived row, vector and artifact of a source; keep the source row."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        for stmt in _DERIVED_DELETES:
            try:
                cursor.execute(stmt, (source_id,))
            except Exception as e:
                print(f"[Purge] Notice clearing derived rows for {source_id}: {e}")
        conn.commit()

    if remove_vectors:
        try:
            from app.search.faiss_index import get_faiss_manager
            get_faiss_manager().remove_source_vectors(source_id)
        except Exception as e:
            print(f"[Purge] FAISS vector removal notice for {source_id}: {e}")

    upload_dir = settings.resolved_upload_dir
    for sub in _DERIVED_DIRS:
        d = upload_dir / sub / source_id
        if d.exists() and is_within(d, upload_dir):
            shutil.rmtree(d, ignore_errors=True)


def delete_source(source_id: str) -> Optional[Dict[str, Any]]:
    """
    Delete a source completely. Only app-managed files are removed: the processed
    copy inside UPLOAD_DIR and the source's copy in KB_DIR (left behind, the startup
    folder sync would re-import it). Returns the deleted row, or None if unknown.
    """
    src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (source_id,))
    if not src:
        return None

    purge_derived_data(source_id)
    with get_db_context() as conn:
        conn.execute("DELETE FROM knowledge_sources WHERE id = ?", (source_id,))
        conn.commit()

    if not is_internet_source(src):
        candidates = []
        if src.get("file_path"):
            candidates.append((Path(src["file_path"]), settings.resolved_upload_dir))
        if src.get("original_name"):
            candidates.append((settings.resolved_kb_dir / src["original_name"], settings.resolved_kb_dir))
        for path, root in candidates:
            try:
                if path.is_file() and is_within(path, root):
                    path.unlink()
            except Exception as e:
                print(f"[Purge] Could not delete file {path}: {e}")
    return src
