import os
import re
import csv
import json
import uuid
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image

from app.core.config import settings
from app.database.session import db_get, db_run, db_all, get_db_context
from app.search.model_pipeline import (
    get_text_embedding,
    get_text_embeddings_batch,
    get_image_embedding,
    detect_and_embed_faces,
    transcribe_audio,
    run_ocr,
    TEXT_DIM,
    IMAGE_DIM,
    FACE_DIM
)
from app.search.faiss_index import get_faiss_manager
from app.processing.logger import IngestionTracker
from app.search.perceptual_hash import compute_image_hashes, store_image_hash

def float_array_to_blob(arr: List[float]) -> bytes:
    import numpy as np
    return np.array(arr, dtype=np.float32).tobytes()

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    chunks = []
    start = 0
    clean = text.strip() if text else ""
    if not clean:
        return []
    while start < len(clean):
        end = min(start + chunk_size, len(clean))
        if end < len(clean):
            last_punc = max(clean.rfind(". ", start, end), clean.rfind("\n", start, end))
            if last_punc > start + chunk_size // 2:
                end = last_punc + 1
        chunks.append(clean[start:end].strip())
        start = end - overlap if end < len(clean) else end
    return [c for c in chunks if len(c) > 10]

from app.search.constants import STOPWORDS, build_enriched_text, preview_text as _preview_text

def is_noise_header(text: str) -> bool:
    clean = text.strip()
    if len(clean) < 3 or len(clean) > 110:
        return True
    # Timestamps & dates (e.g., "9/2/26, 6:36 PM", "2024-08-02")
    if re.search(r"^\d{1,4}[/\-\.]\d{1,2}[/\-\.]\d{1,4}", clean):
        return True
    if re.search(r"^\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?$", clean, re.IGNORECASE):
        return True
    # URLs or domain fragments
    if re.search(r"^(?:https?:\/\/|\(?www\.|[a-zA-Z0-9.-]+\.[a-z]{2,}\/?)", clean, re.IGNORECASE):
        return True
    # Page numbers
    if re.match(r"^(?:page\s*)?\d+(?:\s*(?:of|\/)\s*\d+)?$", clean, re.IGNORECASE):
        return True
    # Fragment starting with lower case or conjunction / punctuation
    if clean[0].islower() or clean.startswith(("[", "(", "-", ",", ";", ":")):
        return True
    if re.match(r"^(?:and|or|but|because|with|that|which|not|to|for|in|on|at|by|from|into)\b", clean, re.IGNORECASE):
        return True
    return False

def extract_page_heading_and_keywords(page, page_num: int, doc_title: str) -> Tuple[str, List[str], bool]:
    """
    Detects page header/title/section heading from page content using PyMuPDF font size & layout analysis.
    Extracts important page keywords and falls back cleanly to document title and page N.
    """
    from collections import Counter
    text_dict = page.get_text("dict")
    blocks = text_dict.get("blocks", [])

    spans_info = []
    page_height = page.rect.height

    for b in blocks:
        if b.get("type") == 0:  # Text block
            for l in b.get("lines", []):
                line_text = "".join([s.get("text", "") for s in l.get("spans", [])]).strip()
                if not line_text:
                    continue

                max_size = max([s.get("size", 0) for s in l.get("spans", [])], default=0)
                is_bold = any((s.get("flags", 0) & 2 != 0) or "bold" in s.get("font", "").lower() for s in l.get("spans", []))
                y0 = l.get("bbox", (0, 0, 0, 0))[1]

                spans_info.append({
                    "text": line_text,
                    "size": max_size,
                    "is_bold": is_bold,
                    "y0": y0,
                    "in_top_third": y0 < (page_height * 0.35)
                })

    detected_heading = None
    fallback_used = False

    if spans_info:
        sizes = [s["size"] for s in spans_info]
        avg_size = sum(sizes) / len(sizes) if sizes else 10.0

        # Look for prominent headings in top 35% of page
        top_candidates = [s for s in spans_info if s["in_top_third"] and not is_noise_header(s["text"])]

        # 1. Check for prominent font size (>= 1.15x average) or bold
        prominent = [s for s in top_candidates if (s["size"] >= avg_size * 1.15 or s["is_bold"]) and len(s["text"]) >= 4]
        if prominent:
            prominent.sort(key=lambda x: (-x["size"], x["y0"]))
            detected_heading = prominent[0]["text"]
        else:
            # Check for explicit section numbering/title patterns (not normal running sentences)
            section_pattern = re.compile(r"^(\d+(\.\d+)*\s+[A-Za-z]|Chapter\s+\d+|Section\s+\d+)", re.IGNORECASE)
            clean_candidates = [
                s for s in top_candidates 
                if len(s["text"]) <= 60 and not s["text"].endswith(".") and section_pattern.match(s["text"])
            ]
            if clean_candidates:
                detected_heading = clean_candidates[0]["text"]

    clean_doc_title = Path(doc_title).stem
    clean_doc_title = re.sub(r"[_\-]+", " ", clean_doc_title).strip()

    if not detected_heading or len(detected_heading) < 3:
        fallback_used = True
        if clean_doc_title:
            detected_heading = f"{clean_doc_title} - Page {page_num}"
        else:
            detected_heading = f"Page {page_num}"

    # Extract important keywords from page text
    full_page_text = page.get_text()
    tokens = [w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", full_page_text)]
    filtered_tokens = [w for w in tokens if w not in STOPWORDS]
    counts = Counter(filtered_tokens)
    top_keywords = [w for w, _ in counts.most_common(8)]

    return detected_heading, top_keywords, fallback_used

# ─── 1. DOCUMENT PROCESSOR ───────────────────────────────────────────────────
def process_document(source_id: str) -> None:
    src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (source_id,))
    if not src:
        return

    file_path = src["file_path"]
    if not file_path or not Path(file_path).exists():
        raise FileNotFoundError(f"Source document file not found on disk: {file_path}")
    file_type = (src["file_type"] or "").lower()
    full_text = ""
    page_count = 1
    sections: List[Dict[str, Any]] = []
    extracted_images_records: List[Dict[str, Any]] = []
    faiss_mgr = get_faiss_manager()

    tracker = IngestionTracker(source_id, src["original_name"], file_type, src.get("file_size") or 0)
    tracker.log_ingestion(f"Source ID: {source_id} | File: '{src['original_name']}' | Type: {file_type.upper()} | Size: {src.get('file_size', 0):,} bytes")

    doc_img_dir = settings.resolved_upload_dir / "doc_images" / source_id
    doc_img_dir.mkdir(parents=True, exist_ok=True)
    tracker.add_file_dir(str(doc_img_dir))

    if file_type == "pdf":
        tracker.methods_used["text_extraction"] = "PyMuPDF (fitz)"
        tracker.methods_used["image_extraction"] = "PyMuPDF embedded pixmap extraction (>2KB filter)"
        tracker.log_ingestion("Extracting text and embedded images using PyMuPDF (fitz)...")
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            page_count = len(doc)
            pages_text = []

            for page_idx in range(page_count):
                page = doc[page_idx]
                p_num = page_idx + 1
                txt = page.get_text() or ""
                pages_text.append(txt)

                # Content-aware page heading and keyword extraction
                heading, page_kws, fb_used = extract_page_heading_and_keywords(page, p_num, src["original_name"])
                if fb_used:
                    print(f"[Page Indexing Fallback] Source: '{src['original_name']}' Page {p_num}: fallback_heading='{heading}'")
                    tracker.log_ingestion(f"Page {p_num} (fallback heading): '{heading}'")
                else:
                    print(f"[Page Indexing] Source: '{src['original_name']}' Page {p_num}: detected_heading='{heading}', keywords={page_kws[:5]}")
                    tracker.log_ingestion(f"Page {p_num} detected heading: '{heading}' | Keywords: {', '.join(page_kws[:5])}")

                if txt.strip():
                    sections.append({
                        "id": str(uuid.uuid4()),
                        "section_title": heading,
                        "section_text": txt,
                        "page_num": p_num,
                        "keywords": page_kws,
                        "order_idx": page_idx
                    })

                # Extract embedded images and rendered visual representations from this page
                image_list = page.get_images(full=True)
                for img_idx, img_info in enumerate(image_list):
                    xref = img_info[0]
                    base_img = doc.extract_image(xref)
                    img_bytes = base_img.get("image")
                    img_ext = base_img.get("ext", "png")
                    if img_bytes and len(img_bytes) > 2048:  # Filter out tiny icons
                        raw_filename = f"page_{p_num}_img_{img_idx}_{xref}_raw.{img_ext}"
                        raw_disk_path = doc_img_dir / raw_filename
                        with open(raw_disk_path, "wb") as f:
                            f.write(img_bytes)

                        extracted_images_records.append({
                            "id": str(uuid.uuid4()),
                            "path": str(raw_disk_path),
                            "page": p_num,
                            "section_title": heading,
                            "keywords": page_kws,
                            "index": img_idx,
                            "type": "document_image_raw"
                        })

                        # Also extract rendered page crop representation (matches user screenshots exactly)
                        try:
                            rects = page.get_image_rects(xref)
                            if rects:
                                for r_idx, rect in enumerate(rects):
                                    pix = page.get_pixmap(clip=rect, dpi=150)
                                    if pix.width >= 32 and pix.height >= 32:
                                        rendered_filename = f"page_{p_num}_img_{img_idx}_{xref}_rendered_{r_idx}.png"
                                        rendered_disk_path = doc_img_dir / rendered_filename
                                        pix.save(str(rendered_disk_path))
                                        extracted_images_records.append({
                                            "id": str(uuid.uuid4()),
                                            "path": str(rendered_disk_path),
                                            "page": p_num,
                                            "section_title": heading,
                                            "keywords": page_kws,
                                            "index": img_idx,
                                            "type": "document_image_rendered"
                                        })
                        except Exception as e_rect:
                            tracker.log_ingestion(f"Notice rendering page crop for page {p_num} image {img_idx}: {e_rect}")

            full_text = "\n\n".join(pages_text)
            doc.close()
            tracker.log_ingestion(f"Extracted text across {page_count} page(s) | Total: {len(full_text):,} characters ({len(full_text.split()):,} words)")
            tracker.log_ingestion(f"Extracted {len(extracted_images_records)} embedded image(s) from PDF pages")
        except Exception as e:
            tracker.methods_used["text_extraction"] = "pypdf (fallback)"
            tracker.log_ingestion(f"PyMuPDF notice: {e}, falling back to pypdf...")
            try:
                import pypdf
                with open(file_path, "rb") as f:
                    reader = pypdf.PdfReader(f)
                    page_count = len(reader.pages)
                    pages_text = []
                    for i, p in enumerate(reader.pages):
                        txt = p.extract_text() or ""
                        pages_text.append(txt)
                        if txt.strip():
                            sections.append({
                                "id": str(uuid.uuid4()),
                                "section_title": f"Page {i + 1}",
                                "section_text": txt,
                                "page_num": i + 1,
                                "order_idx": i
                            })
                    full_text = "\n\n".join(pages_text)
                tracker.log_ingestion(f"Extracted {len(full_text):,} characters via pypdf fallback across {page_count} page(s)")
            except Exception as e2:
                tracker.finish(status="failed", error=str(e2))
                raise RuntimeError(f"Failed to extract PDF text: PyMuPDF error ({e}), pypdf fallback error ({e2})") from e2

    elif file_type in ("docx", "doc"):
        tracker.methods_used["text_extraction"] = "python-docx"
        tracker.log_ingestion("Extracting text from DOCX using python-docx...")
        try:
            import docx
            d = docx.Document(file_path)
            current_heading = "Document Content"
            current_paras = []
            char_count = 0
            section_idx = 0
            estimated_page = 1
            all_paras = []

            for p in d.paragraphs:
                text = p.text.strip()
                if not text:
                    continue
                all_paras.append(text)
                style_name = getattr(getattr(p, "style", None), "name", "").lower()
                is_heading = style_name.startswith("heading") or style_name in ("title", "subtitle")

                if is_heading and current_paras:
                    sec_text = "\n\n".join(current_paras)
                    sections.append({
                        "id": str(uuid.uuid4()),
                        "section_title": current_heading,
                        "section_text": sec_text,
                        "page_num": estimated_page,
                        "order_idx": section_idx
                    })
                    section_idx += 1
                    current_paras = []
                    current_heading = text
                else:
                    current_paras.append(text)

                char_count += len(text)
                estimated_page = max(1, (char_count // 2500) + 1)

            if current_paras:
                sec_text = "\n\n".join(current_paras)
                sections.append({
                    "id": str(uuid.uuid4()),
                    "section_title": current_heading,
                    "section_text": sec_text,
                    "page_num": estimated_page,
                    "order_idx": section_idx
                })

            full_text = "\n\n".join(all_paras)
            tracker.log_ingestion(
                f"Extracted {len(full_text):,} characters ({len(full_text.split()):,} words) "
                f"across {len(sections)} section(s) from {len(all_paras)} paragraphs"
            )
        except Exception as e:
            tracker.finish(status="failed", error=str(e))
            raise RuntimeError(f"Failed to parse DOCX document: {e}") from e

    elif file_type in ("xlsx", "xls"):
        tracker.methods_used["text_extraction"] = "openpyxl (tabular sheets)"
        tracker.log_ingestion("Extracting text from Excel spreadsheet using openpyxl...")
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheet_texts = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                rows = []
                for row in ws.iter_rows(values_only=True):
                    vals = [str(v) for v in row if v is not None]
                    if vals:
                        rows.append(" | ".join(vals))
                sheet_content = "\n".join(rows)
                sheet_texts.append(f"--- Sheet: {sheet} ---\n{sheet_content}")
                sections.append({
                    "id": str(uuid.uuid4()),
                    "section_title": f"Sheet: {sheet}",
                    "section_text": sheet_content,
                    "page_num": 1,
                    "order_idx": len(sections)
                })
            full_text = "\n\n".join(sheet_texts)
            tracker.log_ingestion(f"Extracted {len(full_text):,} characters across {len(wb.sheetnames)} sheets")
        except Exception as e:
            tracker.finish(status="failed", error=str(e))
            raise RuntimeError(f"Failed to parse XLSX document: {e}") from e

    elif file_type == "csv":
        tracker.methods_used["text_extraction"] = "CSV reader (pipe-delimited rows)"
        tracker.log_ingestion("Extracting text from CSV using Python csv.reader...")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                rows = [" | ".join(row) for row in reader if row]
                full_text = "\n".join(rows)
                sections.append({
                    "id": str(uuid.uuid4()),
                    "section_title": "CSV Data",
                    "section_text": full_text,
                    "page_num": 1,
                    "order_idx": 0
                })
            tracker.log_ingestion(f"Extracted {len(full_text):,} characters across {len(rows)} rows")
        except Exception as e:
            tracker.finish(status="failed", error=str(e))
            raise RuntimeError(f"Failed to parse CSV document: {e}") from e
    else:
        # TXT / MD / other text
        tracker.methods_used["text_extraction"] = "Plaintext UTF-8 read"
        tracker.log_ingestion("Reading text from plaintext document...")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                full_text = f.read()
                sections.append({
                    "id": str(uuid.uuid4()),
                    "section_title": "Overview",
                    "section_text": full_text,
                    "page_num": 1,
                    "order_idx": 0
                })
            tracker.log_ingestion(f"Read {len(full_text):,} characters from plaintext file")
        except Exception as e:
            tracker.finish(status="failed", error=str(e))
            raise RuntimeError(f"Failed to read plaintext document: {e}") from e

    if not full_text.strip():
        full_text = f"Document: {src['original_name']}"

    tracker.counts["pages_processed"] = page_count
    tracker.counts["text_chars"] = len(full_text)
    tracker.counts["images_extracted"] = len(extracted_images_records)

    db_run("UPDATE knowledge_sources SET processing_status = 'indexing', page_count = ? WHERE id = ?", (page_count, source_id))

    doc_id = str(uuid.uuid4())
    db_run(
        "INSERT INTO documents (id, source_id, title, full_text, page_count, section_count) VALUES (?, ?, ?, ?, ?, ?)",
        (doc_id, source_id, src["original_name"], full_text, page_count, len(sections))
    )
    tracker.add_sqlite_table("documents")

    for sec in sections:
        db_run(
            "INSERT INTO document_sections (id, doc_id, source_id, section_title, section_text, page_num, order_idx) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sec["id"], doc_id, source_id, sec["section_title"], sec["section_text"], sec["page_num"], sec["order_idx"])
        )
    tracker.add_sqlite_table("document_sections")

    # 1. Chunk and index text into SQLite & FAISS text index (Qwen3-Embedding-0.6B)
    chunks_to_index = []
    for sec in sections:
        sec_text = sec["section_text"].strip()
        if not sec_text:
            continue
        sec_chunks = chunk_text(sec_text, chunk_size=800, overlap=150)
        for sc in sec_chunks:
            chunks_to_index.append({
                "section_id": sec["id"],
                "section_title": sec["section_title"],
                "page_num": sec["page_num"],
                "keywords": sec.get("keywords", []),
                "text": sc
            })

    if not chunks_to_index and full_text.strip():
        for sc in chunk_text(full_text, chunk_size=800, overlap=150):
            chunks_to_index.append({
                "section_id": sections[0]["id"] if sections else None,
                "section_title": src["original_name"],
                "page_num": 1,
                "keywords": [],
                "text": sc
            })

    chunk_count = len(chunks_to_index)
    tracker.methods_used["chunking"] = "Section/Page-Aware Sliding Window (800 chars, 150 overlap)"
    tracker.models_used["text_embedding"] = "Qwen/Qwen3-Embedding-0.6B (1024-dim)"
    tracker.counts["text_chunks"] = chunk_count
    tracker.log_ingestion(f"Chunking: Section/Page-aware window -> Created {chunk_count} text chunks across {len(sections)} section(s)")
    tracker.log_embedding(f"Embedding {chunk_count} text chunks using Qwen/Qwen3-Embedding-0.6B (1024-dim)...")

    with get_db_context() as conn:
        cursor = conn.cursor()
        for idx, item in enumerate(chunks_to_index):
            chunk_id = str(uuid.uuid4())
            ch = item["text"]
            sec_title = item["section_title"]
            enriched_text = build_enriched_text(sec_title, ch)
            emb = get_text_embedding(enriched_text)
            needs_reembed = 0 if emb is not None else 1
            emb_blob = float_array_to_blob(emb) if emb is not None else b""

            cursor.execute(
                "INSERT INTO document_chunks (id, section_id, doc_id, source_id, chunk_text, chunk_order, page_num, embedding, needs_reembed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chunk_id, item["section_id"], doc_id, source_id, enriched_text, idx, item["page_num"], emb_blob, needs_reembed)
            )
            try:
                cursor.execute(
                    "INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id) VALUES (?, ?, ?, ?)",
                    (enriched_text, chunk_id, source_id, doc_id)
                )
            except Exception as fts_err:
                import logging
                logging.getLogger(__name__).warning(
                    f"[Processor] FTS5 insert failed for chunk {chunk_id}: {fts_err}"
                )
                # Mark fts_synced = 0 so a repair sweep can re-insert this chunk
                try:
                    cursor.execute(
                        "UPDATE document_chunks SET fts_synced = 0 WHERE id = ?",
                        (chunk_id,)
                    )
                except Exception:
                    pass

            if emb is not None:
                faiss_mgr.add_text_vector(
                    source_id=source_id,
                    chunk_id=chunk_id,
                    vector=emb,
                    metadata={
                        "type": "document_chunk",
                        "filename": src["original_name"],
                        "doc_id": doc_id,
                        "chunk_order": idx,
                        "page_num": item["page_num"],
                        "section_title": sec_title,
                        "keywords": item["keywords"],
                        "preview": _preview_text(enriched_text)
                    }
                )
            else:
                import logging
                logging.getLogger(__name__).warning(
                    f"[Processor] Skipping FAISS for chunk {chunk_id} — embedding unavailable (model not loaded)"
                )
        conn.commit()

    tracker.counts["text_chunks_embedded"] = chunk_count
    tracker.add_sqlite_table("document_chunks")
    tracker.add_sqlite_table("chunks_fts")
    tracker.add_faiss_index("text.index (1024-dim)")
    tracker.log_storage(f"Stored {chunk_count} text chunks in SQLite: document_chunks, chunks_fts (FTS5)")
    tracker.log_faiss(f"Inserted {chunk_count} text vectors into FAISS text index (current total: {faiss_mgr.text_index.ntotal})")

    # 2. Process Extracted Images (OCR, Jina CLIP, InsightFace)
    total_faces = 0
    total_ocr_chars = 0
    total_ocr_chunks = 0
    total_img_embs = 0

    if extracted_images_records:
        tracker.methods_used["ocr"] = "pytesseract (Tesseract OCR)"
        tracker.models_used["image_embedding"] = "jinaai/jina-clip-v2 (1024-dim)"
        tracker.models_used["face_embedding"] = "InsightFace FaceAnalysis (buffalo_s, 512-dim)"
        tracker.methods_used["face_detection"] = "InsightFace buffalo_s"
        tracker.log_ingestion(f"Processing {len(extracted_images_records)} extracted images (OCR + CLIP + InsightFace)...")

    for img_rec in extracted_images_records:
        img_path = img_rec["path"]
        p_num = img_rec["page"]
        img_title = img_rec.get("section_title") or f"Page {p_num}"
        img_kws = img_rec.get("keywords") or []

        # Run OCR on extracted image
        ocr_text = run_ocr(img_path)
        ocr_words = ocr_text.strip().split()
        if len(ocr_text.strip()) >= 20 and len(ocr_words) >= 3:  # raised threshold (was >5)
            total_ocr_chars += len(ocr_text.strip())
            total_ocr_chunks += 1
            ocr_chunk_id = str(uuid.uuid4())
            # Fix: monotonic chunk_order using enumerate (was constant for all OCR chunks, audit #13)
            ocr_order = chunk_count + len(extracted_images_records) + total_ocr_chunks
            ocr_content = build_enriched_text(f"{img_title} - OCR Page {p_num}", ocr_text)
            ocr_emb = get_text_embedding(ocr_content)
            ocr_needs_reembed = 0 if ocr_emb is not None else 1
            db_run(
                "INSERT INTO document_chunks (id, doc_id, source_id, chunk_text, chunk_order, page_num, embedding, needs_reembed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ocr_chunk_id, doc_id, source_id, ocr_content, ocr_order, p_num,
                 float_array_to_blob(ocr_emb) if ocr_emb is not None else b"", ocr_needs_reembed)
            )
            try:
                db_run(
                    "INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id) VALUES (?, ?, ?, ?)",
                    (ocr_content, ocr_chunk_id, source_id, doc_id)
                )
            except Exception as fts_err:
                import logging
                logging.getLogger(__name__).warning(f"[Processor] FTS5 insert failed for OCR chunk {ocr_chunk_id}: {fts_err}")

            if ocr_emb is not None:
                faiss_mgr.add_text_vector(
                    source_id=source_id,
                    chunk_id=ocr_chunk_id,
                    vector=ocr_emb,
                    metadata={
                        "type": "document_ocr",
                        "filename": src["original_name"],
                        "page_num": p_num,
                        "section_title": img_title,
                        "keywords": img_kws,
                        "preview": _preview_text(ocr_content)
                    }
                )
            tracker.log_ocr(f"OCR Page {p_num} ({img_title}): extracted {len(ocr_text.strip())} chars")

        # Generate real Jina CLIP embedding for extracted image
        clip_emb = get_image_embedding(img_path)
        img_id = img_rec["id"]
        img_type = img_rec.get("type", "document_image")
        if clip_emb is not None:
            faiss_mgr.add_image_vector(
                source_id=source_id,
                entity_id=img_id,
                vector=clip_emb,
                metadata={
                    "type": img_type,
                    "filename": src["original_name"],
                    "page_num": p_num,
                    "section_title": img_title,
                    "keywords": img_kws,
                    "image_path": img_path
                }
            )
            total_img_embs += 1
            tracker.add_faiss_index("image.index (1024-dim)")
        else:
            import logging
            logging.getLogger(__name__).warning(
                f"[Processor] Skipping FAISS image vector for {img_path} — Jina CLIP unavailable"
            )

        # Generate & store perceptual hashes (pHash + dHash)
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
            tracker.add_sqlite_table("image_perceptual_hashes")

        # Run Face Detection (InsightFace)
        detected_faces = detect_and_embed_faces(img_path)
        for face in detected_faces:
            total_faces += 1
            f_id = str(uuid.uuid4())
            f_blob = float_array_to_blob(face["embedding"])
            bbox_json = json.dumps(face.get("box", []))
            db_run(
                "INSERT INTO face_embeddings (id, source_id, image_id, timestamp, embedding, confidence, bbox_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f_id, source_id, img_id, float(p_num), f_blob, face.get("confidence", 0.9), bbox_json)
            )
            faiss_mgr.add_face_vector(
                source_id=source_id,
                face_id=f_id,
                vector=face["embedding"],
                metadata={
                    "type": "document_face",
                    "filename": src["original_name"],
                    "page_num": p_num,
                    "image_path": img_path,
                    "box": face.get("box")
                }
            )
        if detected_faces:
            tracker.add_sqlite_table("face_embeddings")
            tracker.add_faiss_index("face.index (512-dim)")
            tracker.log_face(f"Page {p_num}: detected {len(detected_faces)} face(s) via InsightFace -> stored in SQLite face_embeddings & FAISS face index")

    tracker.counts["ocr_chars"] = total_ocr_chars
    tracker.counts["ocr_chunks"] = total_ocr_chunks
    tracker.counts["image_embeddings_stored"] = total_img_embs
    tracker.counts["faces_detected"] = total_faces
    tracker.counts["face_embeddings_stored"] = total_faces

    # Persist FAISS index changes
    faiss_mgr.save_to_disk()
    tracker.log_faiss("Persisted FAISS index changes to disk.")

    db_run(
        "UPDATE knowledge_sources SET chunk_count = ?, face_count = ? WHERE id = ?",
        (chunk_count + len(extracted_images_records), total_faces, source_id)
    )

    tracker.finish(status="completed")

# ─── 2. IMAGE PROCESSOR ──────────────────────────────────────────────────────
def process_image(source_id: str) -> None:
    src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (source_id,))
    if not src:
        return

    file_path = src["file_path"]
    if not file_path or not Path(file_path).exists():
        raise FileNotFoundError(f"Source image file not found on disk: {file_path}")
    file_type = (src["file_type"] or "").lower()

    tracker = IngestionTracker(source_id, src["original_name"], file_type, src.get("file_size") or 0)
    tracker.log_ingestion(f"Source ID: {source_id} | File: '{src['original_name']}' | Type: {file_type.upper()} | Size: {src.get('file_size', 0):,} bytes")

    faiss_mgr = get_faiss_manager()
    w, h = 800, 600
    try:
        with Image.open(file_path) as img:
            w, h = img.width, img.height
        tracker.methods_used["image_loading"] = "PIL.Image (RGB normalization)"
        tracker.log_ingestion(f"Loaded image {w}x{h} pixels using PIL")
    except Exception as e:
        tracker.finish(status="failed", error=str(e))
        raise RuntimeError(f"Failed to read image file: {e}") from e

    # 1. Run OCR (Tesseract)
    tracker.methods_used["ocr"] = "pytesseract (Tesseract OCR)"
    ocr_text = run_ocr(file_path)
    tracker.counts["ocr_chars"] = len(ocr_text) if ocr_text else 0
    tracker.log_ocr(f"Running Tesseract OCR on image -> Extracted {len(ocr_text):,} characters")

    # 2. Run InsightFace face detection
    tracker.methods_used["face_detection"] = "InsightFace FaceAnalysis (buffalo_s)"
    tracker.models_used["face_embedding"] = "InsightFace buffalo_s (512-dim)"
    detected_faces = detect_and_embed_faces(file_path)
    tracker.counts["faces_detected"] = len(detected_faces)
    tracker.counts["face_embeddings_stored"] = len(detected_faces)
    tracker.log_face(f"Face detection (buffalo_s): detected {len(detected_faces)} face(s)")

    # 3. Generate Jina CLIP v2 image embedding
    tracker.models_used["image_embedding"] = "jinaai/jina-clip-v2 (1024-dim)"
    tracker.log_embedding("Generating 1024-dim image embedding using jinaai/jina-clip-v2...")
    img_emb = get_image_embedding(file_path)
    img_blob = float_array_to_blob(img_emb)

    image_id = str(uuid.uuid4())
    db_run(
        "INSERT INTO images (id, source_id, width, height, ocr_text, description, embedding) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (image_id, source_id, w, h, ocr_text, "", img_blob)
    )
    tracker.add_sqlite_table("images")
    tracker.counts["image_embeddings_stored"] = 1

    # Add to FAISS Image Index
    if img_emb is not None:
        faiss_mgr.add_image_vector(
            source_id=source_id,
            entity_id=image_id,
            vector=img_emb,
            metadata={
                "type": "image",
                "filename": src["original_name"],
                "image_path": file_path
            }
        )
        tracker.add_faiss_index("image.index (1024-dim)")
        tracker.log_faiss(f"Inserted image vector into FAISS image index (current total: {faiss_mgr.image_index.ntotal})")
    else:
        import logging
        logging.getLogger(__name__).warning(
            f"[Processor] Skipping FAISS image vector for standalone image {file_path} — Jina CLIP unavailable"
        )
    tracker.log_storage("Stored image record in SQLite images table")

    # Generate & store perceptual hashes for standalone image
    phash, dhash = compute_image_hashes(file_path)
    if phash and dhash:
        store_image_hash(
            source_id=source_id,
            entity_id=image_id,
            image_path=file_path,
            phash=phash,
            dhash=dhash,
            image_type="image"
        )
        tracker.add_sqlite_table("image_perceptual_hashes")

    # Store faces in SQLite & FAISS Face Index
    face_count = len(detected_faces)
    with get_db_context() as conn:
        cursor = conn.cursor()
        for face in detected_faces:
            f_id = str(uuid.uuid4())
            f_blob = float_array_to_blob(face["embedding"]) if face.get("embedding") is not None else b""
            bbox_json = json.dumps(face.get("box", []))
            cursor.execute(
                "INSERT INTO face_embeddings (id, source_id, image_id, timestamp, embedding, confidence, bbox_json) VALUES (?, ?, ?, 0.0, ?, ?, ?)",
                (f_id, source_id, image_id, f_blob, face.get("confidence", 0.9), bbox_json)
            )
            if face.get("embedding") is not None:
                faiss_mgr.add_face_vector(
                    source_id=source_id,
                    face_id=f_id,
                    vector=face["embedding"],
                    metadata={
                        "type": "image_face",
                        "filename": src["original_name"],
                        "image_path": file_path,
                        "box": face.get("box")
                    }
                )
        conn.commit()

    if detected_faces:
        tracker.add_sqlite_table("face_embeddings")
        tracker.add_faiss_index("face.index (512-dim)")
        tracker.log_storage(f"Stored {len(detected_faces)} face embedding(s) in SQLite face_embeddings table")
        tracker.log_faiss(f"Inserted {len(detected_faces)} face vector(s) into FAISS face index (current total: {faiss_mgr.face_index.ntotal})")

    # Index OCR text into SQLite FTS5 and FAISS text index (Qwen3)
    if ocr_text and ocr_text.strip():
        tracker.models_used["text_embedding"] = "Qwen/Qwen3-Embedding-0.6B (1024-dim)"
        doc_id = str(uuid.uuid4())
        doc_text = f"Image: {src['original_name']}\nOCR Text: {ocr_text.strip()}"
        db_run(
            "INSERT INTO documents (id, source_id, title, full_text, page_count, section_count) VALUES (?, ?, ?, ?, 1, 1)",
            (doc_id, source_id, src["original_name"], doc_text)
        )
        chunk_id = str(uuid.uuid4())
        c_emb = get_text_embedding(doc_text)
        c_needs_reembed = 0 if c_emb is not None else 1
        db_run(
            "INSERT INTO document_chunks (id, doc_id, source_id, chunk_text, chunk_order, embedding, needs_reembed) VALUES (?, ?, ?, ?, 0, ?, ?)",
            (chunk_id, doc_id, source_id, doc_text, float_array_to_blob(c_emb) if c_emb is not None else b"", c_needs_reembed)
        )
        try:
            db_run(
                "INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id) VALUES (?, ?, ?, ?)",
                (doc_text, chunk_id, source_id, doc_id)
            )
        except Exception as fts_err:
            import logging
            logging.getLogger(__name__).warning(f"[Processor] FTS5 insert failed for image OCR {chunk_id}: {fts_err}")
            try:
                db_run("UPDATE document_chunks SET fts_synced = 0 WHERE id = ?", (chunk_id,))
            except Exception:
                pass

        if c_emb is not None:
            faiss_mgr.add_text_vector(
                source_id=source_id,
                chunk_id=chunk_id,
                vector=c_emb,
                metadata={
                    "type": "image_ocr",
                    "filename": src["original_name"],
                    "preview": ocr_text[:150]
                }
            )
        tracker.counts["ocr_chunks"] = 1
        tracker.counts["text_chunks"] = 1
        tracker.counts["text_chunks_embedded"] = 1
        tracker.add_sqlite_table("documents")
        tracker.add_sqlite_table("document_chunks")
        tracker.add_sqlite_table("chunks_fts")
        tracker.add_faiss_index("text.index (1024-dim)")
        tracker.log_embedding("Embedded OCR text with Qwen3-0.6B (1024-dim)")
        tracker.log_storage("Stored image OCR document in SQLite: documents, document_chunks, chunks_fts")
        tracker.log_faiss(f"Inserted image OCR text vector into FAISS text index (current total: {faiss_mgr.text_index.ntotal})")

    faiss_mgr.save_to_disk()
    tracker.log_faiss("Persisted FAISS index changes to disk.")
    db_run("UPDATE knowledge_sources SET face_count = ?, chunk_count = 1 WHERE id = ?", (face_count, source_id))

    tracker.finish(status="completed")

# ─── 3. VIDEO PROCESSOR ──────────────────────────────────────────────────────
def process_video(source_id: str) -> None:
    src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (source_id,))
    if not src:
        return

    file_path = src["file_path"]
    if not file_path or not Path(file_path).exists():
        raise FileNotFoundError(f"Source video file not found on disk: {file_path}")
    file_type = (src["file_type"] or "").lower()

    tracker = IngestionTracker(source_id, src["original_name"], file_type, src.get("file_size") or 0)
    tracker.log_ingestion(f"Source ID: {source_id} | File: '{src['original_name']}' | Type: {file_type.upper()} | Size: {src.get('file_size', 0):,} bytes")

    faiss_mgr = get_faiss_manager()
    duration = 60.0
    fps = 30.0

    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=r_frame_rate", "-of", "default=noprint_wrappers=1", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        for line in probe.stdout.splitlines():
            if line.startswith("duration="):
                duration = float(line.split("=")[1])
            elif line.startswith("r_frame_rate="):
                rate_str = line.split("=")[1]
                if "/" in rate_str:
                    num, den = rate_str.split("/")
                    if float(den) > 0:
                        fps = float(num) / float(den)
        tracker.methods_used["probing"] = "FFprobe (duration, stream frame rate)"
        tracker.log_ingestion(f"Probed video via FFprobe: duration={duration:.2f}s, fps={fps:.1f}")
    except Exception as e:
        tracker.log_ingestion(f"FFprobe notice: {e}")

    db_run("UPDATE knowledge_sources SET duration_seconds = ? WHERE id = ?", (duration, source_id))

    video_id = str(uuid.uuid4())
    db_run(
        "INSERT INTO videos (id, source_id, duration, format, thumbnail_path) VALUES (?, ?, ?, ?, ?)",
        (video_id, source_id, duration, src["file_type"], "")
    )
    tracker.add_sqlite_table("videos")

    frames_dir = settings.resolved_upload_dir / "frames" / source_id
    frames_dir.mkdir(parents=True, exist_ok=True)
    tracker.add_file_dir(str(frames_dir))

    # 1. Video Transcription using Whisper Medium
    tracker.methods_used["transcription"] = "Whisper Medium / faster-whisper"
    tracker.models_used["transcription"] = "Whisper Medium (float16/int8)"
    tracker.log_whisper("Extracting and transcribing audio stream using Whisper Medium...")
    transcript_items = transcribe_audio(file_path)
    if not transcript_items:
        transcript_items.append({
            "start": 0.0,
            "end": duration,
            "text": f"Video footage: {src['original_name']}"
        })
    tracker.counts["transcripts_generated"] = len(transcript_items)
    tracker.log_whisper(f"Transcription complete -> Generated {len(transcript_items)} transcript segment(s)")

    # Index transcript items into SQLite & FAISS text index (Qwen3)
    tracker.models_used["text_embedding"] = "Qwen/Qwen3-Embedding-0.6B (1024-dim)"
    tracker.log_embedding(f"Embedding {len(transcript_items)} transcript segments using Qwen3-0.6B (1024-dim)...")
    with get_db_context() as conn:
        cursor = conn.cursor()
        for tr in transcript_items:
            tr_id = str(uuid.uuid4())
            emb = get_text_embedding(tr["text"])
            needs_reembed = 0 if emb is not None else 1
            cursor.execute(
                "INSERT INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding, needs_reembed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tr_id, video_id, source_id, tr["start"], tr["end"], tr["text"], float_array_to_blob(emb) if emb is not None else b"", needs_reembed)
            )
            try:
                cursor.execute(
                    "INSERT INTO transcripts_fts (text, transcript_id, video_id, source_id, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
                    (tr["text"], tr_id, video_id, source_id, tr["start"], tr["end"])
                )
            except Exception as fts_err:
                import logging
                logging.getLogger(__name__).warning(f"[Processor] FTS5 insert failed for video transcript {tr_id}: {fts_err}")
                try:
                    cursor.execute("UPDATE video_transcripts SET fts_synced = 0 WHERE id = ?", (tr_id,))
                except Exception:
                    pass

            if emb is not None:
                faiss_mgr.add_text_vector(
                    source_id=source_id,
                    chunk_id=tr_id,
                    vector=emb,
                    metadata={
                        "type": "video_transcript",
                        "filename": src["original_name"],
                        "video_id": video_id,
                        "start": tr["start"],
                        "end": tr["end"],
                        "preview": tr["text"][:150]
                    }
                )
            else:
                import logging
                logging.getLogger(__name__).warning(
                    f"[Processor] Skipping FAISS text vector for video transcript {tr_id} — embedding unavailable"
                )
        conn.commit()

    tracker.counts["text_chunks"] = len(transcript_items)
    tracker.counts["text_chunks_embedded"] = len(transcript_items)
    tracker.add_sqlite_table("video_transcripts")
    tracker.add_sqlite_table("transcripts_fts")
    tracker.add_faiss_index("text.index (1024-dim)")
    tracker.log_storage(f"Stored {len(transcript_items)} transcript segments in SQLite: video_transcripts, transcripts_fts")
    tracker.log_faiss(f"Inserted {len(transcript_items)} transcript vectors into FAISS text index (current index size: {faiss_mgr.text_index.ntotal})")

    # 2. Video Frame Sampling with 30-Frame Stride
    # Correct stride: 30-frame stride in seconds, capped at 120 total frames
    # Removed max(1.0, ...) clamp which broke high-fps content (audit #14)
    stride_seconds = (30.0 / fps) if fps > 0 else 1.0
    stride_seconds = max(0.25, stride_seconds)  # floor at 250ms for sanity
    sample_timestamps = []
    curr_t = 0.0
    while curr_t < duration:
        sample_timestamps.append(round(curr_t, 2))
        curr_t += stride_seconds

    if len(sample_timestamps) > 120:
        step = len(sample_timestamps) // 120 + 1
        sample_timestamps = sample_timestamps[::step]

    tracker.methods_used["frame_sampling"] = f"FFmpeg 30-frame stride ({stride_seconds:.1f}s intervals)"
    tracker.log_ingestion(f"Sampling {len(sample_timestamps)} video frames using FFmpeg (stride: {stride_seconds:.1f}s)...")

    tracker.models_used["image_embedding"] = "jinaai/jina-clip-v2 (1024-dim)"
    tracker.models_used["face_embedding"] = "InsightFace FaceAnalysis (buffalo_s, 512-dim)"
    tracker.methods_used["face_detection"] = "InsightFace buffalo_s"
    tracker.methods_used["ocr"] = "pytesseract (Tesseract OCR)"

    frames_records = []
    total_faces = 0
    total_ocr_frames = 0

    for idx, ts in enumerate(sample_timestamps):
        frame_id = str(uuid.uuid4())
        frame_file = str(frames_dir / f"frame_{idx:04d}_{int(ts)}s.jpg")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(ts), "-i", file_path, "-vframes", "1", "-q:v", "2", frame_file],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
            )
            if Path(frame_file).exists():
                emb = get_image_embedding(frame_file)
                frames_records.append({
                    "id": frame_id,
                    "timestamp": float(ts),
                    "frame_number": idx * 30,
                    "scene_id": idx + 1,
                    "frame_path": frame_file,
                    "embedding": float_array_to_blob(emb) if emb is not None else b""
                })

                if emb is not None:
                    faiss_mgr.add_image_vector(
                        source_id=source_id,
                        entity_id=frame_id,
                        vector=emb,
                        metadata={
                            "type": "video_frame",
                            "filename": src["original_name"],
                            "timestamp": float(ts),
                            "frame_path": frame_file
                        }
                    )
                else:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"[Processor] Skipping FAISS image vector for frame {frame_file} — Jina CLIP unavailable"
                    )

                # Store perceptual hashes for sampled video frame
                phash, dhash = compute_image_hashes(frame_file)
                if phash and dhash:
                    store_image_hash(
                        source_id=source_id,
                        entity_id=frame_id,
                        image_path=frame_file,
                        phash=phash,
                        dhash=dhash,
                        image_type="video_frame",
                        timestamp=float(ts)
                    )

                # Run OCR on frame — only index if content is substantive
                f_ocr = run_ocr(frame_file)
                f_ocr_words = f_ocr.strip().split() if f_ocr else []
                if f_ocr and len(f_ocr.strip()) >= 20 and len(f_ocr_words) >= 3:
                    total_ocr_frames += 1
                    f_ocr_id = str(uuid.uuid4())
                    ocr_line = f"[Video frame at {ts}s]: {f_ocr.strip()}"
                    f_ocr_emb = get_text_embedding(ocr_line)
                    try:
                        db_run(
                            "INSERT INTO transcripts_fts (text, transcript_id, video_id, source_id, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
                            (ocr_line, f_ocr_id, video_id, source_id, float(ts), float(ts + 1.0))
                        )
                    except Exception as fts_err:
                        import logging
                        logging.getLogger(__name__).warning(f"[Processor] FTS5 insert failed for frame OCR {f_ocr_id}: {fts_err}")
                    if f_ocr_emb is not None:
                        faiss_mgr.add_text_vector(
                            source_id=source_id,
                            chunk_id=f_ocr_id,
                            vector=f_ocr_emb,
                            metadata={
                                "type": "video_frame_ocr",
                                "filename": src["original_name"],
                                "timestamp": float(ts),
                                "preview": f_ocr[:150]
                            }
                        )

                # Run InsightFace face detection on frame
                detected_faces = detect_and_embed_faces(frame_file)
                for face in detected_faces:
                    total_faces += 1
                    f_id = str(uuid.uuid4())
                    f_blob = float_array_to_blob(face["embedding"]) if face.get("embedding") is not None else b""
                    bbox_json = json.dumps(face.get("box", []))
                    db_run(
                        "INSERT INTO face_embeddings (id, source_id, video_id, frame_id, timestamp, embedding, confidence, bbox_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (f_id, source_id, video_id, frame_id, float(ts), f_blob, face.get("confidence", 0.9), bbox_json)
                    )
                    if face.get("embedding") is not None:
                        faiss_mgr.add_face_vector(
                            source_id=source_id,
                            face_id=f_id,
                            vector=face["embedding"],
                            metadata={
                                "type": "video_face",
                                "filename": src["original_name"],
                                "timestamp": float(ts),
                                "frame_path": frame_file,
                                "box": face.get("box")
                            }
                        )
        except Exception as e:
            tracker.log_ingestion(f"Frame processing notice at {ts}s: {e}")

    tracker.counts["frames_sampled"] = len(frames_records)
    tracker.counts["image_embeddings_stored"] = len(frames_records)
    tracker.counts["faces_detected"] = total_faces
    tracker.counts["face_embeddings_stored"] = total_faces
    tracker.counts["ocr_chunks"] = total_ocr_frames

    tracker.log_embedding(f"Embedded {len(frames_records)} video frames using jinaai/jina-clip-v2 (1024-dim)")
    tracker.log_faiss(f"Inserted {len(frames_records)} frame vectors into FAISS image index (current index size: {faiss_mgr.image_index.ntotal})")
    tracker.log_face(f"Detected {total_faces} face(s) across {len(frames_records)} sampled frames")

    if frames_records:
        # Pick best-quality thumbnail by pixel variance + brightness (audit #27)
        # Avoids using frames_records[0] which is often a dark/black frame at t=0s.
        best_thumb = None
        best_score = -1.0
        try:
            import numpy as np
            for fr in frames_records[:min(12, len(frames_records))]:
                fp = fr.get("frame_path", "")
                if not fp or not Path(fp).exists():
                    continue
                with Image.open(fp).convert("L") as gray_img:
                    arr = np.array(gray_img, dtype=np.float32)
                variance = float(arr.var())
                brightness = float(arr.mean())
                # Penalize very dark frames (< 30 / 255) and very bright (overexposed > 240)
                if brightness < 15 or brightness > 245:
                    continue
                thumb_score = variance * (1.0 - abs(brightness - 128) / 256.0)
                if thumb_score > best_score:
                    best_score = thumb_score
                    best_thumb = fp
        except Exception:
            pass
        thumb_path = best_thumb or frames_records[0]["frame_path"]
        db_run("UPDATE videos SET thumbnail_path = ? WHERE id = ?", (thumb_path, video_id))

    with get_db_context() as conn:
        cursor = conn.cursor()
        for fr in frames_records:
            cursor.execute(
                "INSERT INTO video_frames (id, video_id, source_id, timestamp, frame_number, scene_id, frame_path, embedding) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (fr["id"], video_id, source_id, fr["timestamp"], fr["frame_number"], fr["scene_id"], fr["frame_path"], fr["embedding"])
            )
        conn.commit()

    tracker.add_sqlite_table("video_frames")
    if total_faces > 0:
        tracker.add_sqlite_table("face_embeddings")
        tracker.add_faiss_index("face.index (512-dim)")
        tracker.log_storage(f"Stored {total_faces} face embeddings in SQLite face_embeddings")
        tracker.log_faiss(f"Inserted {total_faces} face vectors into FAISS face index (current index size: {faiss_mgr.face_index.ntotal})")

    tracker.add_faiss_index("image.index (1024-dim)")
    tracker.log_storage(f"Stored {len(frames_records)} video frames in SQLite video_frames")

    faiss_mgr.save_to_disk()
    tracker.log_faiss("Persisted FAISS index changes to disk.")

    db_run(
        "UPDATE knowledge_sources SET transcript_count = ?, frame_count = ?, face_count = ? WHERE id = ?",
        (len(transcript_items), len(frames_records), total_faces, source_id)
    )

    tracker.finish(status="completed")

# ─── 4. AUDIO PROCESSOR ──────────────────────────────────────────────────────
def process_audio(source_id: str) -> None:
    src = db_get("SELECT * FROM knowledge_sources WHERE id = ?", (source_id,))
    if not src:
        return

    file_path = src["file_path"]
    if not file_path or not Path(file_path).exists():
        raise FileNotFoundError(f"Source audio file not found on disk: {file_path}")
    file_type = (src["file_type"] or "").lower()

    tracker = IngestionTracker(source_id, src["original_name"], file_type, src.get("file_size") or 0)
    tracker.log_ingestion(f"Source ID: {source_id} | File: '{src['original_name']}' | Type: {file_type.upper()} | Size: {src.get('file_size', 0):,} bytes")

    faiss_mgr = get_faiss_manager()
    duration = 60.0
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        duration = float(probe.stdout.strip())
        tracker.methods_used["probing"] = "FFprobe (duration)"
        tracker.log_ingestion(f"FFprobe audio duration: {duration:.2f}s")
    except Exception as e:
        tracker.log_ingestion(f"FFprobe notice: {e}")

    db_run("UPDATE knowledge_sources SET duration_seconds = ? WHERE id = ?", (duration, source_id))
    video_id = str(uuid.uuid4())
    db_run(
        "INSERT INTO videos (id, source_id, duration, format) VALUES (?, ?, ?, ?)",
        (video_id, source_id, duration, src["file_type"])
    )
    tracker.add_sqlite_table("videos")

    tracker.methods_used["transcription"] = "Whisper Medium / faster-whisper"
    tracker.models_used["transcription"] = "Whisper Medium"
    tracker.log_whisper("Transcribing audio stream using Whisper Medium...")
    transcript_items = transcribe_audio(file_path)
    if not transcript_items:
        transcript_items.append({"start": 0.0, "end": duration, "text": f"Audio file: {src['original_name']}"})

    tracker.counts["transcripts_generated"] = len(transcript_items)
    tracker.counts["text_chunks"] = len(transcript_items)
    tracker.counts["text_chunks_embedded"] = len(transcript_items)
    tracker.log_whisper(f"Generated {len(transcript_items)} transcript segments")

    tracker.models_used["text_embedding"] = "Qwen/Qwen3-Embedding-0.6B (1024-dim)"
    tracker.log_embedding(f"Embedding {len(transcript_items)} transcript segments using Qwen3-0.6B (1024-dim)...")

    with get_db_context() as conn:
        cursor = conn.cursor()
        for tr in transcript_items:
            tr_id = str(uuid.uuid4())
            emb = get_text_embedding(tr["text"])
            needs_reembed = 0 if emb is not None else 1
            cursor.execute(
                "INSERT INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding, needs_reembed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tr_id, video_id, source_id, tr["start"], tr["end"], tr["text"], float_array_to_blob(emb) if emb is not None else b"", needs_reembed)
            )
            try:
                cursor.execute(
                    "INSERT INTO transcripts_fts (text, transcript_id, video_id, source_id, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
                    (tr["text"], tr_id, video_id, source_id, tr["start"], tr["end"])
                )
            except Exception as fts_err:
                import logging
                logging.getLogger(__name__).warning(f"[Processor] FTS5 insert failed for audio transcript {tr_id}: {fts_err}")
                try:
                    cursor.execute("UPDATE video_transcripts SET fts_synced = 0 WHERE id = ?", (tr_id,))
                except Exception:
                    pass

            if emb is not None:
                faiss_mgr.add_text_vector(
                    source_id=source_id,
                    chunk_id=tr_id,
                    vector=emb,
                    metadata={
                        "type": "audio_transcript",
                        "filename": src["original_name"],
                        "start": tr["start"],
                        "end": tr["end"],
                        "preview": tr["text"][:150]
                    }
                )
            else:
                import logging
                logging.getLogger(__name__).warning(
                    f"[Processor] Skipping FAISS text vector for audio transcript {tr_id} — embedding unavailable"
                )
        conn.commit()

    tracker.add_sqlite_table("video_transcripts")
    tracker.add_sqlite_table("transcripts_fts")
    tracker.add_faiss_index("text.index (1024-dim)")
    tracker.log_storage(f"Stored {len(transcript_items)} transcripts in SQLite video_transcripts & transcripts_fts")
    tracker.log_faiss(f"Inserted {len(transcript_items)} transcript vectors into FAISS text index (current index size: {faiss_mgr.text_index.ntotal})")

    faiss_mgr.save_to_disk()
    tracker.log_faiss("Persisted FAISS index changes to disk.")
    db_run("UPDATE knowledge_sources SET transcript_count = ? WHERE id = ?", (len(transcript_items), source_id))

    tracker.finish(status="completed")
