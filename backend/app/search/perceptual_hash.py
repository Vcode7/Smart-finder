"""
app/search/perceptual_hash.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Perceptual image hashing for near-duplicate and visually-similar image retrieval.

Uses pHash and dHash (64-bit each). Hamming distance <= 8 is considered a match.

Hamming distance is computed as popcount(a XOR b) over the 64-bit integers.
There is deliberately no numeric "prefix bucket" pre-filter: hashes that differ
in a single high bit are near-duplicates but land in numerically distant
buckets, so bucketing silently dropped most real matches.
"""
import io
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from PIL import Image, ImageOps
import imagehash

from app.database.session import db_run, db_all


def _load_image(image_input: Union[str, bytes, Path, Image.Image]) -> Optional[Image.Image]:
    try:
        if isinstance(image_input, Image.Image):
            return image_input.convert("RGB")
        if isinstance(image_input, bytes):
            with Image.open(io.BytesIO(image_input)) as im:
                return ImageOps.exif_transpose(im).convert("RGB")
        if isinstance(image_input, (str, Path)):
            p = Path(image_input)
            if p.exists():
                with Image.open(str(p)) as im:
                    return ImageOps.exif_transpose(im).convert("RGB")
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


def _phash_prefix(phash_hex: str) -> Optional[int]:
    """Top 16 bits of a 64-bit phash (kept in the schema; not used for filtering)."""
    if not phash_hex or len(phash_hex) < 4:
        return None
    try:
        return int(phash_hex[:4], 16)
    except Exception:
        return None


def _hex_to_int(h: str) -> Optional[int]:
    try:
        return int(h, 16) if h else None
    except (TypeError, ValueError):
        return None


def hamming_distance(h1_str: str, h2_str: str) -> int:
    """Calculates Hamming distance between two hex-encoded 64-bit hashes."""
    a, b = _hex_to_int(h1_str), _hex_to_int(h2_str)
    if a is None or b is None:
        return 64
    return (a ^ b).bit_count()


def _similarity_from_distances(p_dist: int, d_dist: int) -> float:
    min_dist = min(p_dist, d_dist)
    # Near-duplicate / screenshot / resize matching scale (0-64 bits)
    if p_dist == 0 and d_dist == 0:
        return 1.00
    if p_dist <= 2 and d_dist <= 2:
        return 0.99
    if p_dist <= 3 and d_dist <= 3:
        return 0.98
    if p_dist <= 5 and d_dist <= 5:
        return 0.95
    if min_dist <= 4:
        return 0.94
    if min_dist <= 6:
        return 0.90
    if min_dist <= 8:
        return 0.80
    if min_dist <= 10:
        return 0.65
    return 0.0


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
    return (_similarity_from_distances(p_dist, d_dist), p_dist, d_dist)


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
    prefix = _phash_prefix(phash)
    db_run(
        """INSERT INTO image_perceptual_hashes
           (id, source_id, entity_id, image_path, phash, dhash, image_type, page_num, timestamp, phash_prefix)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (hash_id, source_id, entity_id, str(image_path), phash, dhash, image_type, page_num, timestamp, prefix)
    )
    return hash_id


def search_image_hashes(
    query_phash: str,
    query_dhash: str,
    max_hamming_distance: int = 8
) -> List[Dict[str, Any]]:
    """
    Compares query perceptual hashes against every stored image hash.
    Returns matching records sorted by visual similarity descending.
    """
    q_ph = _hex_to_int(query_phash)
    q_dh = _hex_to_int(query_dhash)
    if q_ph is None and q_dh is None:
        return []

    rows = db_all(
        """SELECT id, source_id, entity_id, image_path, phash, dhash, image_type, page_num, timestamp
           FROM image_perceptual_hashes"""
    )

    matches: List[Dict[str, Any]] = []
    for row in rows:
        t_ph = _hex_to_int(row.get("phash", ""))
        t_dh = _hex_to_int(row.get("dhash", ""))
        p_dist = (q_ph ^ t_ph).bit_count() if (q_ph is not None and t_ph is not None) else 64
        d_dist = (q_dh ^ t_dh).bit_count() if (q_dh is not None and t_dh is not None) else 64
        if p_dist > max_hamming_distance and d_dist > max_hamming_distance:
            continue
        sim = _similarity_from_distances(p_dist, d_dist)
        if sim < 0.60:
            continue
        item = dict(row)
        item["similarity"] = sim
        item["p_dist"] = p_dist
        item["d_dist"] = d_dist
        item["is_exact_match"] = (p_dist <= 3 and d_dist <= 3)
        matches.append(item)

    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches
