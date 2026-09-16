import os
import sys
import uuid
from pathlib import Path

# Fix OpenMP conflict on Windows
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# Ensure backend directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import fitz
import faiss
import numpy as np
from app.database.session import db_all, db_run
from app.core.config import settings
from app.search.model_pipeline import (
    get_image_embedding,
    _get_jina_clip_model,
)
from app.search.perceptual_hash import (
    compute_image_hashes,
    store_image_hash,
)
from app.search.faiss_index import get_faiss_manager

def reindex_all_media():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 70)
    print("STARTING COMPLETE MEDIA RE-INDEXING (REAL JINA CLIP v2 + pHASH/dHASH)")
    print("=" * 70)

    # 1. Ensure Jina CLIP model is loaded
    print("[1/5] Initializing real Jina CLIP v2 model...")
    clip_model = _get_jina_clip_model()
    if clip_model is None:
        raise RuntimeError("CRITICAL: Failed to load real Jina CLIP v2 model. Halting re-indexing.")
    print("[1/5] Real Jina CLIP v2 model verified ready on CUDA/CPU.")

    # 2. Reset FAISS image index and SQLite perceptual hash table
    print("[2/5] Resetting FAISS image index and image_perceptual_hashes table...")
    faiss_mgr = get_faiss_manager()
    faiss_mgr.image_index = faiss.IndexFlatIP(1024)
    faiss_mgr.image_meta = []

    db_run("DELETE FROM image_perceptual_hashes")
    print("[2/5] Purged old dummy image vectors and hash records.")

    # 3. Fetch all completed sources
    sources = db_all(
        "SELECT id, original_name, file_type, file_path, processing_status FROM knowledge_sources WHERE processing_status = 'completed'"
    )
    print(f"[3/5] Found {len(sources)} completed knowledge sources to re-index.")

    upload_dir = settings.resolved_upload_dir
    doc_images_dir = upload_dir / "doc_images"
    doc_images_dir.mkdir(parents=True, exist_ok=True)

    total_images_indexed = 0
    total_hashes_stored = 0

    for idx, src in enumerate(sources, 1):
        source_id = src["id"]
        orig_name = src["original_name"]
        file_type = (src["file_type"] or "").lower()
        file_path = Path(src["file_path"])

        print(f"\n--- [{idx}/{len(sources)}] Processing {orig_name} ({file_type}) ---")

        if not file_path.exists():
            print(f"  [WARN] File not found at {file_path}, skipping.")
            continue

        # A. PDF Documents: Extract raw and rendered viewport crops
        if file_type == "pdf":
            try:
                doc = fitz.open(str(file_path))
                src_doc_img_dir = doc_images_dir / source_id
                src_doc_img_dir.mkdir(parents=True, exist_ok=True)

                pdf_images_to_index = []

                for p_idx in range(len(doc)):
                    page = doc[p_idx]
                    p_num = p_idx + 1
                    img_list = page.get_images(full=True)

                    for img_idx, img_info in enumerate(img_list):
                        xref = img_info[0]
                        base_image = doc.extract_image(xref)
                        if not base_image:
                            continue

                        img_bytes = base_image.get("image")
                        img_ext = base_image.get("ext", "png").lower()
                        width = base_image.get("width", 0)
                        height = base_image.get("height", 0)

                        if width < 32 or height < 32 or not img_bytes:
                            continue

                        # 1. Raw embedded image
                        raw_filename = f"page_{p_num}_img_{img_idx}_{xref}_raw.{img_ext}"
                        raw_disk_path = src_doc_img_dir / raw_filename
                        with open(raw_disk_path, "wb") as f:
                            f.write(img_bytes)

                        pdf_images_to_index.append({
                            "id": str(uuid.uuid4()),
                            "path": str(raw_disk_path),
                            "page": p_num,
                            "type": "document_image_raw"
                        })

                        # 2. Rendered crop representation on page
                        try:
                            rects = page.get_image_rects(xref)
                            for r_idx, rect in enumerate(rects):
                                pix = page.get_pixmap(clip=rect, dpi=150)
                                if pix.width >= 32 and pix.height >= 32:
                                    rendered_filename = f"page_{p_num}_img_{img_idx}_{xref}_rendered_{r_idx}.png"
                                    rendered_disk_path = src_doc_img_dir / rendered_filename
                                    pix.save(str(rendered_disk_path))

                                    pdf_images_to_index.append({
                                        "id": str(uuid.uuid4()),
                                        "path": str(rendered_disk_path),
                                        "page": p_num,
                                        "type": "document_image_rendered"
                                    })
                        except Exception as e_rect:
                            print(f"    [WARN] get_image_rects error: {e_rect}")

                doc.close()

                print(f"  Extracted {len(pdf_images_to_index)} images (raw + rendered crops). Indexing...")
                for item in pdf_images_to_index:
                    img_path = item["path"]
                    img_id = item["id"]
                    p_num = item["page"]
                    img_type = item["type"]

                    # Real CLIP vector
                    clip_emb = get_image_embedding(img_path)
                    faiss_mgr.add_image_vector(
                        source_id=source_id,
                        entity_id=img_id,
                        vector=clip_emb,
                        metadata={
                            "type": img_type,
                            "filename": orig_name,
                            "page_num": p_num,
                            "image_path": img_path
                        }
                    )
                    total_images_indexed += 1

                    # Hashes
                    phash, dhash = compute_image_hashes(img_path)
                    if phash and dhash:
                        store_image_hash(
                            source_id=source_id,
                            entity_id=img_id,
                            image_path=img_path,
                            phash=phash,
                            dhash=dhash,
                            image_type=img_type,
                            page_num=p_num
                        )
                        total_hashes_stored += 1

            except Exception as e:
                print(f"  [ERROR] Failed to process PDF {orig_name}: {e}")

        # B. Standalone Images
        elif file_type in ("jpg", "jpeg", "png", "webp"):
            try:
                img_id = str(uuid.uuid4())
                clip_emb = get_image_embedding(str(file_path))
                faiss_mgr.add_image_vector(
                    source_id=source_id,
                    entity_id=img_id,
                    vector=clip_emb,
                    metadata={
                        "type": "standalone_image",
                        "filename": orig_name,
                        "image_path": str(file_path)
                    }
                )
                total_images_indexed += 1

                phash, dhash = compute_image_hashes(str(file_path))
                if phash and dhash:
                    store_image_hash(
                        source_id=source_id,
                        entity_id=img_id,
                        image_path=str(file_path),
                        phash=phash,
                        dhash=dhash,
                        image_type="standalone_image"
                    )
                    total_hashes_stored += 1
            except Exception as e:
                print(f"  [ERROR] Failed to process image {orig_name}: {e}")

        # C. Videos: Re-index existing extracted frames
        elif file_type in ("mp4", "mkv", "mov", "webm", "avi"):
            frames_dir = upload_dir / "frames" / source_id
            if frames_dir.exists():
                frame_files = list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png"))
                print(f"  Found {len(frame_files)} extracted video frames. Indexing...")
                for frame_path in frame_files:
                    try:
                        frame_id = str(uuid.uuid4())
                        clip_emb = get_image_embedding(str(frame_path))
                        faiss_mgr.add_image_vector(
                            source_id=source_id,
                            entity_id=frame_id,
                            vector=clip_emb,
                            metadata={
                                "type": "video_frame",
                                "filename": orig_name,
                                "frame_path": str(frame_path)
                            }
                        )
                        total_images_indexed += 1

                        phash, dhash = compute_image_hashes(str(frame_path))
                        if phash and dhash:
                            store_image_hash(
                                source_id=source_id,
                                entity_id=frame_id,
                                image_path=str(frame_path),
                                phash=phash,
                                dhash=dhash,
                                image_type="video_frame"
                            )
                            total_hashes_stored += 1
                    except Exception as e:
                        print(f"    [WARN] Frame indexing error for {frame_path.name}: {e}")

    # 4. Save FAISS indexes to disk
    print("\n[4/5] Saving FAISS image index to disk...")
    faiss_mgr.save_to_disk()
    print(f"[4/5] Successfully saved {faiss_mgr.image_index.ntotal} vectors to image.index!")

    # 5. Verification & Summary
    print("\n[5/5] VERIFICATION:")
    print(f"  Total FAISS Image Index Vectors: {faiss_mgr.image_index.ntotal}")
    print(f"  Total FAISS Metadata Entries:   {len(faiss_mgr.image_meta)}")
    print(f"  Total Perceptual Hashes:        {total_hashes_stored}")

    # Inspect first few vectors in FAISS image index
    if faiss_mgr.image_index.ntotal > 0:
        sample_vec = faiss_mgr.image_index.reconstruct(0)
        norm = np.linalg.norm(sample_vec)
        dim = len(sample_vec)
        print(f"  Sample Vector #0 - Dim: {dim}, L2-Norm: {norm:.4f}, Non-zero count: {np.count_nonzero(sample_vec)}")
        if abs(norm - 1.0) < 1e-3 and dim == 1024:
            print("  >>> SUCCESS: Image index contains REAL 1024-dim normalized Jina CLIP embeddings! <<<")
        else:
            print("  >>> WARNING: Embedding check did not match expected normalized 1024-dim vector! <<<")

    print("\n" + "=" * 70)
    print("RE-INDEXING COMPLETED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    reindex_all_media()
