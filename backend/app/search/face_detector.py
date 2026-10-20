import os
import re
import io
import json
import uuid
import base64
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from PIL import Image

from app.core.config import settings
from app.database.session import db_all


def crop_face_from_image(image_path: str, bbox: Dict[str, float], output_path: str) -> bool:
    """Save a padded crop of a face (bbox in normalized coordinates)."""
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with Image.open(image_path) as img:
            w, h = img.width, img.height
            x_min, y_min = bbox.get("xMin", 0.0), bbox.get("yMin", 0.0)
            x_max, y_max = bbox.get("xMax", 1.0), bbox.get("yMax", 1.0)
            pad_x = (x_max - x_min) * 0.15
            pad_y = (y_max - y_min) * 0.15
            box = (
                int(round(max(0.0, x_min - pad_x) * w)),
                int(round(max(0.0, y_min - pad_y) * h)),
                int(round(min(1.0, x_max + pad_x) * w)),
                int(round(min(1.0, y_max + pad_y) * h)),
            )
            if box[2] - box[0] < 2 or box[3] - box[1] < 2:
                return False
            img.crop(box).convert("RGB").save(output_path, "JPEG", quality=90)
        return True
    except Exception as e:
        print(f"[FaceDetector] Crop notice: {e}")
        return False


async def _vision_analysis(image_path: str) -> Dict[str, Any]:
    """Optional Groq vision call for scene description, OCR and named entities."""
    with Image.open(image_path) as src_im:
        rgb_im = src_im.convert("RGB")
        max_dim = 800
        if max(rgb_im.width, rgb_im.height) > max_dim:
            scale = max_dim / max(rgb_im.width, rgb_im.height)
            rgb_im = rgb_im.resize((int(rgb_im.width * scale), int(rgb_im.height * scale)), Image.Resampling.BILINEAR)
        buf = io.BytesIO()
        rgb_im.save(buf, format="JPEG", quality=80)
    data_url = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"

    prompt = (
        "Analyze this image for facial recognition, entity identification, and OCR text.\n"
        "Do NOT include any <think> tags or conversational explanations.\n"
        "Return ONLY a raw valid JSON object with this exact structure:\n"
        "{\n"
        '  "ocr_text": "All readable text in the image",\n'
        '  "visual_description": "Detailed visual description of person/scene",\n'
        '  "identified_names": ["Name 1", "Name 2"]\n'
        "}"
    )

    from app.ai.groq_client import get_async_groq_client, robust_json_loads
    client = get_async_groq_client()
    call_kwargs = {
        "model": settings.GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": 1000,
        "temperature": 0.1,
    }
    if "qwen" in settings.GROQ_MODEL.lower():
        call_kwargs["extra_body"] = {"reasoning_format": "hidden"}

    completion = await asyncio.wait_for(client.chat.completions.create(**call_kwargs), timeout=10.0)
    raw = completion.choices[0].message.content or "{}"
    if "<think>" in raw:
        raw = re.sub(r"<think>[\s\S]*?(?:</think>|$)", "", raw).strip()
    return robust_json_loads(raw, default={})


async def detect_faces_in_image(
    image_input: Union[str, bytes],
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Faces (InsightFace, local) plus OCR / description for an image.

    options:
      sourceId   — "query" for search inputs (default)
      useVision  — call the Groq vision model for OCR/description/names (default True)
      saveCrops  — write face crops to disk (default: only for non-query images)
    """
    opts = options or {}
    source_id = opts.get("sourceId", "query")
    use_vision = bool(opts.get("useVision", True))
    save_crops = bool(opts.get("saveCrops", source_id != "query"))
    crop_dir = Path(opts.get("cropDir") or (settings.resolved_upload_dir / "faces" / source_id))

    temp_image_path: Optional[str] = None
    if isinstance(image_input, bytes):
        temp_dir = settings.resolved_upload_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_image_path = str(temp_dir / f"detect_{uuid.uuid4()}.img")
        with open(temp_image_path, "wb") as f:
            f.write(image_input)
        image_path = temp_image_path
    else:
        image_path = str(image_input)

    detected_faces = []
    ocr_text = ""
    visual_description = ""
    identified_names: List[str] = []

    try:
        if not Path(image_path).exists():
            return {"hasFace": False, "faces": [], "primaryFace": None, "ocrText": "",
                    "visualDescription": "", "identifiedNames": []}

        # 1. Local InsightFace detection + 512-dim ArcFace embeddings
        try:
            from app.search.model_pipeline import detect_and_embed_faces
            insight_faces = await asyncio.to_thread(detect_and_embed_faces, image_path)
            for i, iface in enumerate(insight_faces):
                box = iface.get("box", [0, 0, 1, 1])
                bbox = {"yMin": box[0], "xMin": box[1], "yMax": box[2], "xMax": box[3]}
                face_id = str(uuid.uuid4())
                crop_path = None
                if save_crops:
                    crop_file = str(crop_dir / f"face_{face_id}_{i}.jpg")
                    if await asyncio.to_thread(crop_face_from_image, image_path, bbox, crop_file):
                        crop_path = crop_file
                detected_faces.append({
                    "id": face_id,
                    "bbox": bbox,
                    "confidence": float(iface.get("confidence", 0.9)),
                    "label": "person",
                    "cropPath": crop_path,
                    "embedding": iface.get("embedding", []),
                })
        except Exception as e_face:
            print(f"[FaceDetector] InsightFace extraction notice: {e_face}")

        # 2. OCR / description: Groq vision when requested and configured, else local Tesseract OCR
        vision_done = False
        if use_vision and settings.get_groq_api_keys():
            try:
                parsed = await _vision_analysis(image_path)
                ocr_text = parsed.get("ocr_text", "") or ""
                visual_description = parsed.get("visual_description", "") or ""
                if isinstance(parsed.get("identified_names"), list):
                    identified_names.extend([n for n in parsed["identified_names"] if isinstance(n, str) and n.strip()])
                vision_done = True
            except Exception as e:
                print(f"[FaceDetector] Groq vision analysis notice: {e}")
        if not vision_done:
            from app.search.model_pipeline import run_ocr
            ocr_text = await asyncio.to_thread(run_ocr, image_path)
    finally:
        if temp_image_path and Path(temp_image_path).exists():
            try:
                os.unlink(temp_image_path)
            except Exception:
                pass

    return {
        "hasFace": len(detected_faces) > 0,
        "faces": detected_faces,
        "primaryFace": detected_faces[0] if detected_faces else None,
        "ocrText": ocr_text,
        "visualDescription": visual_description,
        "identifiedNames": identified_names,
    }


def search_face_embeddings(
    query_embedding: List[float],
    min_similarity: float = 0.50,
    limit: int = 15
) -> List[Dict[str, Any]]:
    """Nearest stored faces via the FAISS face index, joined to their source/frame rows."""
    from app.search.faiss_index import get_faiss_manager

    hits = get_faiss_manager().search_face(query_embedding, top_k=max(limit * 3, 30), min_score=min_similarity)
    if not hits:
        return []

    face_ids = [h["entity_id"] for h in hits]
    placeholders = ",".join("?" * len(face_ids))
    rows = db_all(
        f"""SELECT fe.id, fe.source_id, fe.video_id, fe.image_id, fe.frame_id, fe.timestamp,
                   fe.confidence, fe.bbox_json, ks.original_name, vf.frame_path, vf.frame_number
            FROM face_embeddings fe
            LEFT JOIN knowledge_sources ks ON ks.id = fe.source_id
            LEFT JOIN video_frames vf ON vf.id = fe.frame_id
            WHERE fe.id IN ({placeholders})""",
        tuple(face_ids)
    )
    by_id = {r["id"]: r for r in rows}

    matches = []
    for h in hits:
        row = by_id.get(h["entity_id"])
        if not row:
            continue
        bbox = None
        if row.get("bbox_json"):
            try:
                bbox = json.loads(row["bbox_json"])
            except Exception:
                pass
        matches.append({
            "id": row["id"],
            "sourceId": row["source_id"],
            "videoId": row.get("video_id"),
            "imageId": row.get("image_id"),
            "frameId": row.get("frame_id"),
            "timestamp": row.get("timestamp"),
            "frameNumber": row.get("frame_number"),
            "confidence": row.get("confidence", 0.9),
            "similarity": round(float(h["score"]), 4),
            "sourceName": row.get("original_name"),
            "framePath": row.get("frame_path"),
            "bbox": bbox,
        })

    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches[:limit]
