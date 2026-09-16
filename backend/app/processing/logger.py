import time
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from app.database.session import db_run, db_get

class IngestionTracker:
    """
    Step-by-step logging and metadata tracking for media ingestion.
    Provides formatted console output with consistent prefixes:
    [Ingestion], [OCR], [Embedding], [FAISS], [Face], [Whisper], [Storage]
    and persists structured metrics into knowledge_sources.metadata_json.
    """

    def __init__(self, source_id: str, original_name: str, file_type: str, file_size: int):
        self.source_id = source_id
        self.original_name = original_name
        self.file_type = file_type.lower()
        self.file_size = file_size
        self.start_time = time.time()

        self.methods_used: Dict[str, str] = {}
        self.models_used: Dict[str, str] = {}
        self.counts: Dict[str, int] = {
            "text_chars": 0,
            "text_chunks": 0,
            "text_chunks_embedded": 0,
            "pages_processed": 0,
            "images_extracted": 0,
            "image_embeddings_stored": 0,
            "frames_sampled": 0,
            "ocr_chars": 0,
            "ocr_chunks": 0,
            "faces_detected": 0,
            "face_embeddings_stored": 0,
            "transcripts_generated": 0,
        }
        self.storage_info: Dict[str, List[str]] = {
            "sqlite_tables": [],
            "faiss_indexes": [],
            "file_directories": [],
        }
        self.logs: List[Dict[str, str]] = []

    def _add_log(self, prefix: str, message: str) -> None:
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "prefix": prefix,
            "message": message,
        }
        self.logs.append(entry)
        print(f"{prefix} {message}", flush=True)

    def log_ingestion(self, message: str) -> None:
        self._add_log("[Ingestion]", message)

    def log_ocr(self, message: str) -> None:
        self._add_log("[OCR]", message)

    def log_embedding(self, message: str) -> None:
        self._add_log("[Embedding]", message)

    def log_faiss(self, message: str) -> None:
        self._add_log("[FAISS]", message)

    def log_face(self, message: str) -> None:
        self._add_log("[Face]", message)

    def log_whisper(self, message: str) -> None:
        self._add_log("[Whisper]", message)

    def log_storage(self, message: str) -> None:
        self._add_log("[Storage]", message)

    def add_sqlite_table(self, table_name: str) -> None:
        if table_name not in self.storage_info["sqlite_tables"]:
            self.storage_info["sqlite_tables"].append(table_name)

    def add_faiss_index(self, index_name: str) -> None:
        if index_name not in self.storage_info["faiss_indexes"]:
            self.storage_info["faiss_indexes"].append(index_name)

    def add_file_dir(self, dir_name: str) -> None:
        if dir_name not in self.storage_info["file_directories"]:
            self.storage_info["file_directories"].append(dir_name)

    def to_dict(self, status: str = "completed", error: Optional[str] = None) -> Dict[str, Any]:
        elapsed = round(time.time() - self.start_time, 2)
        return {
            "source_id": self.source_id,
            "filename": self.original_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "processing_status": status,
            "error_message": error,
            "processing_time_seconds": elapsed,
            "methods_used": self.methods_used,
            "models_used": self.models_used,
            "counts": self.counts,
            "storage_info": self.storage_info,
            "logs": self.logs,
        }

    def save_to_db(self, status: str = "completed", error: Optional[str] = None) -> Dict[str, Any]:
        info = self.to_dict(status=status, error=error)
        try:
            # Merge with existing metadata_json if any
            src = db_get("SELECT metadata_json FROM knowledge_sources WHERE id = ?", (self.source_id,))
            current_meta = {}
            if src and src.get("metadata_json"):
                try:
                    current_meta = json.loads(src["metadata_json"])
                except Exception:
                    current_meta = {}
            current_meta["processing_info"] = info
            json_str = json.dumps(current_meta)
            db_run(
                "UPDATE knowledge_sources SET metadata_json = ? WHERE id = ?",
                (json_str, self.source_id)
            )
        except Exception as e:
            print(f"[Storage] Notice updating metadata_json: {e}", flush=True)
        return info

    def finish(self, status: str = "completed", error: Optional[str] = None) -> Dict[str, Any]:
        elapsed = round(time.time() - self.start_time, 2)
        if status == "completed":
            self.log_storage(
                f"Ingestion completed in {elapsed}s | Chunks: {self.counts['text_chunks']} | "
                f"Embedded: {self.counts['text_chunks_embedded']} | "
                f"Faces: {self.counts['faces_detected']} | "
                f"FAISS: {', '.join(self.storage_info['faiss_indexes']) or 'None'} | "
                f"SQLite Tables: {', '.join(self.storage_info['sqlite_tables']) or 'None'}"
            )
        else:
            self.log_storage(f"Ingestion {status} after {elapsed}s: {error}")

        return self.save_to_db(status=status, error=error)
