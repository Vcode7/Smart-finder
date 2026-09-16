"""
app/search/embeddings.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Shared embedding utilities: serialization, deserialization, cosine similarity.

NOTE: This module intentionally does NOT contain get_text_embedding,
get_image_embedding, or get_multimodal_text_embedding. Those live in
model_pipeline.py and return Optional[List[float]].  If you need them,
import from app.search.model_pipeline.
"""
import numpy as np
from typing import List, Union


def normalize_vector(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return (vec / norm).astype(np.float32)


def float_array_to_blob(arr: List[float]) -> bytes:
    return np.array(arr, dtype=np.float32).tobytes()


def blob_to_float_array(blob: bytes) -> List[float]:
    if not blob:
        return []
    return np.frombuffer(blob, dtype=np.float32).tolist()


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
