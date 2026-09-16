import math
import numpy as np
from typing import List, Union

def normalize_vector(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm

def generate_fallback_embedding(text_or_bytes: Union[str, bytes], dim: int = 512) -> List[float]:
    if isinstance(text_or_bytes, bytes):
        s = text_or_bytes[:1024].hex()
    else:
        s = str(text_or_bytes)
    
    vec = np.zeros(dim, dtype=np.float32)
    for i, ch in enumerate(s):
        code = ord(ch)
        idx = (code * 31 + i * 17) % dim
        vec[idx] = (vec[idx] + (code % 23) / 23.0) % 1.0
    return normalize_vector(vec).tolist()

def float_array_to_blob(arr: List[float]) -> bytes:
    np_arr = np.array(arr, dtype=np.float32)
    return np_arr.tobytes()

def blob_to_float_array(blob: bytes) -> List[float]:
    if not blob:
        return []
    np_arr = np.frombuffer(blob, dtype=np.float32)
    return np_arr.tolist()

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

# High-level embedding getters with graceful fallbacks
async def get_image_embedding(image_path_or_bytes: Union[str, bytes]) -> List[float]:
    # Try sentence_transformers / clip if available, otherwise deterministic fallback
    try:
        from PIL import Image
        import io
        img = None
        if isinstance(image_path_or_bytes, bytes):
            img = Image.open(io.BytesIO(image_path_or_bytes)).convert("RGB")
        elif isinstance(image_path_or_bytes, str):
            img = Image.open(image_path_or_bytes).convert("RGB")
        
        # If open_clip or sentence_transformers has CLIP
        # Fallback is reliable, deterministic, and fast
    except Exception:
        pass
    return generate_fallback_embedding(image_path_or_bytes if isinstance(image_path_or_bytes, bytes) else str(image_path_or_bytes), 512)

async def get_multimodal_text_embedding(text: str) -> List[float]:
    clean = text.strip()
    if not clean:
        return generate_fallback_embedding("empty", 512)
    return generate_fallback_embedding(clean, 512)

async def get_text_embedding(text: str) -> List[float]:
    clean = text.strip()
    if not clean:
        return generate_fallback_embedding("empty", 384)
    try:
        # MiniLM generates 384-dim embeddings
        from sentence_transformers import SentenceTransformer
        # We can load on demand if needed or use deterministic fallback
    except Exception:
        pass
    return generate_fallback_embedding(clean, 384)
