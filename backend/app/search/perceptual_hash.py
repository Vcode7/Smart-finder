import io
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from PIL import Image
import imagehash

from app.database.session import db_run, db_all

def _load_image(image_input: Union[str, bytes, Path, Image.Image]) -> Optional[Image.Image]:
    try:
        if isinstance(image_input, Image.Image):
            return image_input.convert("RGB")
        elif isinstance(image_input, bytes):
            return Image.open(io.BytesIO(image_input)).convert("RGB")
        elif isinstance(image_input, (str, Path)):
            p = Path(image_input)
            if p.exists():
                return Image.open(str(p)).convert("RGB")
    except Exception as e:
        print(f"[PerceptualHash] Image load error: {e}")
    return None

def compute_image_hashes(image_input: Union[str, bytes, Path, Image.Image]) -> Tuple[str, str]:
    """
    Computes 64-bit pHash and dHash for an image.
    Returns (phash_hex, dhash_hex).
    """
    img = _load_image(image_input)
    if img is None:
        return ("", "")
    try:
        ph = str(imagehash.phash(img))
        dh = str(imagehash.dhash(img))
        return (ph, dh)
    except Exception as e:
        print(f"[PerceptualHash] Hash computation error: {e}")
        return ("", "")

def hamming_distance(h1_str: str, h2_str: str) -> int:
    """Calculates Hamming distance between two hex-encoded 64-bit hashes."""
    if not h1_str or not h2_str:
        return 64
    try:
        h1 = imagehash.hex_to_hash(h1_str)
        h2 = imagehash.hex_to_hash(h2_str)
        return int(h1 - h2)
    except Exception:
        return 64

def calculate_hash_similarity(
    query_phash: str,
    query_dhash: str,
    target_phash: str,
    target_dhash: str
) -> Tuple[float, int, int]:
    """
    Computes visual similarity based on combined pHash and dHash Hamming distances.
    Returns (similarity_score 0.0-1.0, p_dist, d_dist).
    """
    p_dist = hamming_distance(query_phash, target_phash)
    d_dist = hamming_distance(query_dhash, target_dhash)
    min_dist = min(p_dist, d_dist)

    # Near-duplicate / screenshot / resize matching scale (0-64 bits)
    if p_dist == 0 and d_dist == 0:
        sim = 1.00
    elif p_dist <= 2 and d_dist <= 2:
        sim = 0.99
    elif p_dist <= 3 and d_dist <= 3:
        sim = 0.98
    elif p_dist <= 5 and d_dist <= 5:
        sim = 0.95
    elif min_dist <= 4:
        sim = 0.94
    elif min_dist <= 6:
        sim = 0.90
    elif min_dist <= 8:
        sim = 0.80
    elif min_dist <= 10:
        sim = 0.65
    else:
        sim = 0.0

    return (round(sim, 3), p_dist, d_dist)

def store_image_hash(
    source_id: str,
    entity_id: str,
    image_path: str,
    phash: str,
    dhash: str,
    image_type: str,
    page_num: Optional[int] = None,
    timestamp: Optional[float] = None
) -> str:
    """Persists an image's perceptual hashes to SQLite."""
    hash_id = str(uuid.uuid4())
    db_run(
        """INSERT INTO image_perceptual_hashes 
           (id, source_id, entity_id, image_path, phash, dhash, image_type, page_num, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (hash_id, source_id, entity_id, str(image_path), phash, dhash, image_type, page_num, timestamp)
    )
    return hash_id

def search_image_hashes(
    query_phash: str,
    query_dhash: str,
    max_hamming_distance: int = 8
) -> List[Dict[str, Any]]:
    """
    Compares query perceptual hashes against all stored image hashes.
    Returns matching records sorted by visual similarity descending.
    """
    if not query_phash and not query_dhash:
        return []

    rows = db_all("SELECT * FROM image_perceptual_hashes")
    matches: List[Dict[str, Any]] = []

    for row in rows:
        t_ph = row.get("phash", "")
        t_dh = row.get("dhash", "")
        sim, p_dist, d_dist = calculate_hash_similarity(query_phash, query_dhash, t_ph, t_dh)

        if (p_dist <= max_hamming_distance or d_dist <= max_hamming_distance) and sim >= 0.60:
            item = dict(row)
            item["similarity"] = sim
            item["p_dist"] = p_dist
            item["d_dist"] = d_dist
            item["is_exact_match"] = (p_dist <= 3 and d_dist <= 3)
            matches.append(item)

    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches
