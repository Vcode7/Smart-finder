import os
import re
import json
import uuid
import base64
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from PIL import Image

from app.core.config import settings
from app.database.session import db_all, db_get
from app.search.embeddings import (
    get_image_embedding,
    blob_to_float_array,
    cosine_similarity,
    float_array_to_blob,
)

def get_image_dimensions(file_path: str) -> Tuple[int, int]:
    try:
        with Image.open(file_path) as img:
            return img.width, img.height
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        parts = result.stdout.strip().split("x")
        w, h = int(parts[0]), int(parts[1])
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 1280, 720

def crop_face_from_image(image_path: str, bbox: Dict[str, float], output_path: str) -> bool:
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        img_w, img_h = get_image_dimensions(image_path)

        x_min = bbox.get("xMin", 0.0)
        y_min = bbox.get("yMin", 0.0)
        x_max = bbox.get("xMax", 1.0)
        y_max = bbox.get("yMax", 1.0)

        # 15% padding
        pad_x = (x_max - x_min) * 0.15
        pad_y = (y_max - y_min) * 0.15

        x1 = max(0.0, x_min - pad_x)
        y1 = max(0.0, y_min - pad_y)
        x2 = min(1.0, x_max + pad_x)
        y2 = min(1.0, y_max + pad_y)

        crop_x = int(round(x1 * img_w))
        crop_y = int(round(y1 * img_h))
        crop_w = max(32, int(round((x2 - x1) * img_w)))
        crop_h = max(32, int(round((y2 - y1) * img_h)))

        safe_crop_w = min(crop_w, img_w - crop_x)
        safe_crop_h = min(crop_h, img_h - crop_y)

        subprocess.run(
            [
                "ffmpeg", "-y", "-i", image_path,
                "-filter:v", f"crop={safe_crop_w}:{safe_crop_h}:{crop_x}:{crop_y}",
                "-q:v", "2", output_path
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        return Path(output_path).exists()
    except Exception as e:
        print(f"[FaceDetector] FFmpeg crop notice: {e}")
        # Try PIL crop fallback
        try:
            with Image.open(image_path) as img:
                box = (
                    int(round(max(0.0, bbox.get("xMin", 0.0)) * img.width)),
                    int(round(max(0.0, bbox.get("yMin", 0.0)) * img.height)),
                    int(round(min(1.0, bbox.get("xMax", 1.0)) * img.width)),
                    int(round(min(1.0, bbox.get("yMax", 1.0)) * img.height))
                )
                cropped = img.crop(box)
                cropped.save(output_path, "JPEG")
                return True
        except Exception:
            return False

async def detect_faces_in_image(
    image_input: Union[str, bytes],
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    opts = options or {}
    source_id = opts.get("sourceId", "query")
    crop_dir = opts.get("cropDir") or str(settings.resolved_upload_dir / "faces" / source_id)
    Path(crop_dir).mkdir(parents=True, exist_ok=True)

    temp_image_path: Optional[str] = None
    if isinstance(image_input, bytes):
        temp_dir = settings.resolved_upload_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_image_path = str(temp_dir / f"detect_{uuid.uuid4()}.jpg")
        with open(temp_image_path, "wb") as f:
            f.write(image_input)
        image_path = temp_image_path
    else:
        image_path = str(image_input)

    detected_faces = []
    ocr_text = ""
    visual_description = ""
    identified_names = []

    # Try Groq vision model if API key is present
    if settings.GROQ_API_KEY and Path(image_path).exists():
        try:
            import io
            import asyncio
            with Image.open(image_path) as src_im:
                rgb_im = src_im.convert("RGB")
                max_dim = 800
                if max(rgb_im.width, rgb_im.height) > max_dim:
                    scale = max_dim / max(rgb_im.width, rgb_im.height)
                    nw = int(rgb_im.width * scale)
                    nh = int(rgb_im.height * scale)
                    resized_im = rgb_im.resize((nw, nh), Image.Resampling.BILINEAR)
                else:
                    resized_im = rgb_im
                
                buf = io.BytesIO()
                resized_im.save(buf, format="JPEG", quality=80)
                b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")
            data_url = f"data:image/jpeg;base64,{b64_img}"

            prompt = (
                "Analyze this image for facial recognition, entity identification, and OCR text.\n"
                "Do NOT include any <think> tags or conversational explanations.\n"
                "Return ONLY a raw valid JSON object with this exact structure:\n"
                "{\n"
                '  "faces": [{"box": [ymin, xmin, ymax, xmax], "confidence": 0.95, "label": "person"}],\n'
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

            completion = await asyncio.wait_for(
                client.chat.completions.create(**call_kwargs),
                timeout=12.0
            )
            raw = completion.choices[0].message.content or "{}"
            if "<think>" in raw:
                raw = re.sub(r"<think>[\s\S]*?(?:</think>|$)", "", raw).strip()
            parsed = robust_json_loads(raw, default={})

            ocr_text = parsed.get("ocr_text", "")
            visual_description = parsed.get("visual_description", "")
            if isinstance(parsed.get("identified_names"), list):
                identified_names.extend([n for n in parsed["identified_names"] if isinstance(n, str) and n.strip()])

            # Real face detection & 512-dim ArcFace embeddings using InsightFace
            try:
                from app.search.model_pipeline import detect_and_embed_faces
                insight_faces = await asyncio.to_thread(detect_and_embed_faces, image_path)
                for i, iface in enumerate(insight_faces):
                    box = iface.get("box", [0, 0, 1, 1])
                    bbox = {
                        "yMin": box[0], "xMin": box[1], "yMax": box[2], "xMax": box[3]
                    }
                    face_id = str(uuid.uuid4())
                    crop_file = str(Path(crop_dir) / f"face_{face_id}_{i}.jpg")
                    cropped = crop_face_from_image(image_path, bbox, crop_file)
                    detected_faces.append({
                        "id": face_id,
                        "bbox": bbox,
                        "confidence": float(iface.get("confidence", 0.9)),
                        "label": "person",
                        "cropPath": crop_file if cropped else None,
                        "embedding": iface.get("embedding", []),
                    })
            except Exception as e_face:
                print(f"[FaceDetector] InsightFace extraction notice: {e_face}")
        except Exception as e:
            print(f"[FaceDetector] Groq vision analysis notice: {e}")

    # Clean up temp file
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
    rows = db_all("SELECT * FROM face_embeddings")
    matches = []

    for row in rows:
        emb_blob = row.get("embedding")
        if not emb_blob:
            continue
        stored_vec = blob_to_float_array(emb_blob)
        similarity = cosine_similarity(query_embedding, stored_vec)

        if similarity >= min_similarity:
            src = db_get("SELECT original_name FROM knowledge_sources WHERE id = ?", (row["source_id"],))
            frame_path = None
            frame_number = None

            if row.get("frame_id"):
                frame_row = db_get(
                    "SELECT frame_path, frame_number FROM video_frames WHERE id = ?",
                    (row["frame_id"],)
                )
                if frame_row:
                    frame_path = frame_row.get("frame_path")
                    frame_number = frame_row.get("frame_number")

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
                "frameNumber": frame_number,
                "confidence": row.get("confidence", 0.9),
                "similarity": round(similarity, 4),
                "sourceName": src.get("original_name") if src else None,
                "framePath": frame_path,
                "bbox": bbox,
            })

    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches[:limit]
