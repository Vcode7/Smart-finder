import os
import json
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import faiss

from app.core.config import settings

# Default dimensions
TEXT_DIM = 1024      # Qwen3-Embedding-0.6B
IMAGE_DIM = 1024     # Jina CLIP v2
FACE_DIM = 512       # InsightFace ArcFace

class FAISSVectorManager:
    """
    Manages three distinct FAISS vector index spaces:
    1. text_index: 1024-dim (document chunks, OCR text, video transcripts)
    2. image_index: 1024-dim (extracted PDF images, standalone photos, sampled video frames)
    3. face_index: 512-dim (InsightFace face embeddings)
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        if storage_dir is None:
            storage_dir = settings.resolved_db_path.parent / "faiss"
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()

        # Indexes using Inner Product on L2-normalized vectors (Cosine Similarity)
        self.text_index = faiss.IndexFlatIP(TEXT_DIM)
        self.image_index = faiss.IndexFlatIP(IMAGE_DIM)
        self.face_index = faiss.IndexFlatIP(FACE_DIM)

        # Mapping: vector_idx (int) -> dict(source_id, entity_type, entity_id, metadata)
        self.text_meta: List[Dict[str, Any]] = []
        self.image_meta: List[Dict[str, Any]] = []
        self.face_meta: List[Dict[str, Any]] = []

        self.load_from_disk()

    # ─── Helper for Vector Normalization ─────────────────────────────────────────

    @staticmethod
    def _normalize(vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec, axis=-1, keepdims=True)
        norm = np.where(norm == 0, 1.0, norm)
        return (vec / norm).astype(np.float32)

    def _prepare_vector(self, vector: Any, expected_dim: int) -> Optional[np.ndarray]:
        """Validates and normalizes vector into a 2D float32 numpy array with expected_dim."""
        if vector is None:
            return None
        try:
            arr = np.asarray(vector, dtype=np.float32)
            if arr.size == 0 or np.isnan(arr).any():
                return None
            if arr.ndim == 1:
                arr = np.expand_dims(arr, axis=0)
            if arr.ndim != 2 or arr.shape[1] != expected_dim:
                return None
            return self._normalize(arr)
        except Exception:
            return None

    # ─── Adding Vectors ──────────────────────────────────────────────────────────

    def add_text_vector(
        self,
        source_id: str,
        chunk_id: str,
        vector: List[float],
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        vec_np = self._prepare_vector(vector, TEXT_DIM)
        if vec_np is None:
            return -1
        with self._lock:
            idx = self.text_index.ntotal
            self.text_index.add(vec_np)
            self.text_meta.append({
                "source_id": source_id,
                "entity_type": (metadata or {}).get("type", "chunk"),
                "entity_id": chunk_id,
                "metadata": metadata or {},
            })
            return idx

    def add_image_vector(
        self,
        source_id: str,
        entity_id: str,
        vector: List[float],
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        vec_np = self._prepare_vector(vector, IMAGE_DIM)
        if vec_np is None:
            return -1
        with self._lock:
            idx = self.image_index.ntotal
            self.image_index.add(vec_np)
            self.image_meta.append({
                "source_id": source_id,
                "entity_type": (metadata or {}).get("type", "image"),
                "entity_id": entity_id,
                "metadata": metadata or {},
            })
            return idx

    def add_face_vector(
        self,
        source_id: str,
        face_id: str,
        vector: List[float],
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        vec_np = self._prepare_vector(vector, FACE_DIM)
        if vec_np is None:
            return -1
        with self._lock:
            idx = self.face_index.ntotal
            self.face_index.add(vec_np)
            self.face_meta.append({
                "source_id": source_id,
                "entity_type": "face",
                "entity_id": face_id,
                "metadata": metadata or {},
            })
            return idx

    # ─── Searching Vectors ───────────────────────────────────────────────────────

    def search_text(
        self,
        query_vector: Optional[List[float]],
        top_k: int = 25,
        min_score: float = 0.35
    ) -> List[Dict[str, Any]]:
        vec_np = self._prepare_vector(query_vector, TEXT_DIM)
        if vec_np is None:
            return []
        with self._lock:
            if self.text_index.ntotal == 0:
                return []
            try:
                k = min(top_k, self.text_index.ntotal)
                scores, indices = self.text_index.search(vec_np, k)

                results = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx < 0 or idx >= len(self.text_meta):
                        continue
                    score_val = float(score)
                    if score_val >= min_score:
                        item = dict(self.text_meta[idx])
                        item["score"] = score_val
                        results.append(item)
                return results
            except Exception as e:
                print(f"[FAISS] Text search notice: {e}")
                return []

    def search_image(
        self,
        query_vector: Optional[List[float]],
        top_k: int = 25,
        min_score: float = 0.30
    ) -> List[Dict[str, Any]]:
        vec_np = self._prepare_vector(query_vector, IMAGE_DIM)
        if vec_np is None:
            return []
        with self._lock:
            if self.image_index.ntotal == 0:
                return []
            try:
                k = min(top_k, self.image_index.ntotal)
                scores, indices = self.image_index.search(vec_np, k)

                results = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx < 0 or idx >= len(self.image_meta):
                        continue
                    score_val = float(score)
                    if score_val >= min_score:
                        item = dict(self.image_meta[idx])
                        item["score"] = score_val
                        results.append(item)
                return results
            except Exception as e:
                print(f"[FAISS] Image search notice: {e}")
                return []

    def search_face(
        self,
        query_vector: Optional[List[float]],
        top_k: int = 20,
        min_score: float = 0.45
    ) -> List[Dict[str, Any]]:
        vec_np = self._prepare_vector(query_vector, FACE_DIM)
        if vec_np is None:
            return []
        with self._lock:
            if self.face_index.ntotal == 0:
                return []
            try:
                k = min(top_k, self.face_index.ntotal)
                scores, indices = self.face_index.search(vec_np, k)

                results = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx < 0 or idx >= len(self.face_meta):
                        continue
                    score_val = float(score)
                    if score_val >= min_score:
                        item = dict(self.face_meta[idx])
                        item["score"] = score_val
                        results.append(item)
                return results
            except Exception as e:
                print(f"[FAISS] Face search notice: {e}")
                return []

    # ─── Source-Level Removal & Compaction ───────────────────────────────────────

    def remove_source_vectors(self, source_id: str) -> None:
        """
        Removes all vectors belonging to source_id from text, image, and face indexes,
        then reconstructs the FAISS indexes cleanly.
        """
        with self._lock:
            # 1. Text Index
            if self.text_index.ntotal > 0:
                keep_text_idx = [i for i, m in enumerate(self.text_meta) if m["source_id"] != source_id]
                if len(keep_text_idx) < len(self.text_meta):
                    new_text_index = faiss.IndexFlatIP(TEXT_DIM)
                    new_text_meta = []
                    for i in keep_text_idx:
                        vec = self.text_index.reconstruct(i)
                        new_text_index.add(np.array([vec], dtype=np.float32))
                        new_text_meta.append(self.text_meta[i])
                    self.text_index = new_text_index
                    self.text_meta = new_text_meta

            # 2. Image Index
            if self.image_index.ntotal > 0:
                keep_img_idx = [i for i, m in enumerate(self.image_meta) if m["source_id"] != source_id]
                if len(keep_img_idx) < len(self.image_meta):
                    new_image_index = faiss.IndexFlatIP(IMAGE_DIM)
                    new_image_meta = []
                    for i in keep_img_idx:
                        vec = self.image_index.reconstruct(i)
                        new_image_index.add(np.array([vec], dtype=np.float32))
                        new_image_meta.append(self.image_meta[i])
                    self.image_index = new_image_index
                    self.image_meta = new_image_meta

            # 3. Face Index
            if self.face_index.ntotal > 0:
                keep_face_idx = [i for i, m in enumerate(self.face_meta) if m["source_id"] != source_id]
                if len(keep_face_idx) < len(self.face_meta):
                    new_face_index = faiss.IndexFlatIP(FACE_DIM)
                    new_face_meta = []
                    for i in keep_face_idx:
                        vec = self.face_index.reconstruct(i)
                        new_face_index.add(np.array([vec], dtype=np.float32))
                        new_face_meta.append(self.face_meta[i])
                    self.face_index = new_face_index
                    self.face_meta = new_face_meta

            self.save_to_disk()

    def clear_all(self) -> None:
        """
        Clears all in-memory indexes and deletes persisted files on disk.
        """
        with self._lock:
            self.text_index = faiss.IndexFlatIP(TEXT_DIM)
            self.image_index = faiss.IndexFlatIP(IMAGE_DIM)
            self.face_index = faiss.IndexFlatIP(FACE_DIM)
            self.text_meta = []
            self.image_meta = []
            self.face_meta = []
            for f in ["text.index", "image.index", "face.index", "metadata.json"]:
                p = self.storage_dir / f
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
            self.save_to_disk()

    # ─── Persistence to Disk ─────────────────────────────────────────────────────

    def save_to_disk(self) -> None:
        with self._lock:
            try:
                faiss.write_index(self.text_index, str(self.storage_dir / "text.index"))
                faiss.write_index(self.image_index, str(self.storage_dir / "image.index"))
                faiss.write_index(self.face_index, str(self.storage_dir / "face.index"))

                meta_data = {
                    "text": self.text_meta,
                    "image": self.image_meta,
                    "face": self.face_meta,
                }
                with open(self.storage_dir / "metadata.json", "w", encoding="utf-8") as f:
                    json.dump(meta_data, f, ensure_ascii=False)
            except Exception as e:
                print(f"[FAISS] Failed to save indexes to disk: {e}")

    def load_from_disk(self) -> None:
        with self._lock:
            text_p = self.storage_dir / "text.index"
            img_p = self.storage_dir / "image.index"
            face_p = self.storage_dir / "face.index"
            meta_p = self.storage_dir / "metadata.json"

            if text_p.exists() and img_p.exists() and face_p.exists() and meta_p.exists():
                try:
                    self.text_index = faiss.read_index(str(text_p))
                    self.image_index = faiss.read_index(str(img_p))
                    self.face_index = faiss.read_index(str(face_p))

                    with open(meta_p, "r", encoding="utf-8") as f:
                        meta_data = json.load(f)
                    self.text_meta = meta_data.get("text", [])
                    self.image_meta = meta_data.get("image", [])
                    self.face_meta = meta_data.get("face", [])
                    print(f"[FAISS] Loaded indexes from disk: text={self.text_index.ntotal}, image={self.image_index.ntotal}, face={self.face_index.ntotal}")
                except Exception as e:
                    print(f"[FAISS] Could not load saved index, initializing empty: {e}")
                    self.text_index = faiss.IndexFlatIP(TEXT_DIM)
                    self.image_index = faiss.IndexFlatIP(IMAGE_DIM)
                    self.face_index = faiss.IndexFlatIP(FACE_DIM)
                    self.text_meta = []
                    self.image_meta = []
                    self.face_meta = []

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "textVectors": self.text_index.ntotal,
                "imageVectors": self.image_index.ntotal,
                "faceVectors": self.face_index.ntotal,
                "total": self.text_index.ntotal + self.image_index.ntotal + self.face_index.ntotal,
            }

# Global singleton
_manager_instance: Optional[FAISSVectorManager] = None

def get_faiss_manager() -> FAISSVectorManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = FAISSVectorManager()
    return _manager_instance
