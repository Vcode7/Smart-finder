import os
import io
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import numpy as np
from PIL import Image
import torch

from app.core.config import settings

# ─── Dimension Constants ───────────────────────────────────────────────────────
TEXT_DIM = 1024      # Qwen3-Embedding-0.6B
IMAGE_DIM = 1024     # Jina CLIP v2
FACE_DIM = 512       # InsightFace ArcFace

# Configure Tesseract OCR path
try:
    import pytesseract
    tesseract_candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for cand in tesseract_candidates:
        if os.path.isfile(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            break
except Exception as e:
    print(f"[ModelPipeline] Pytesseract setup warning: {e}")

# ─── Deterministic Normalized Fallbacks ────────────────────────────────────────
def normalize_vector(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec, axis=-1, keepdims=True)
    norm = np.where(norm == 0, 1.0, norm)
    return (vec / norm).astype(np.float32)

def generate_fallback_embedding(data: Union[str, bytes], dim: int) -> List[float]:
    """Generates a stable, reproducible pseudo-embedding if model is unavailable."""
    if isinstance(data, bytes):
        s = data[:1024].hex()
    else:
        s = str(data)
    vec = np.zeros(dim, dtype=np.float32)
    for i, ch in enumerate(s):
        code = ord(ch)
        idx = (code * 31 + i * 17) % dim
        vec[idx] = (vec[idx] + (code % 23) / 23.0) % 1.0
    return normalize_vector(vec).tolist()

# ─── 1. Text Embeddings: Qwen3-Embedding-0.6B ──────────────────────────────────
_qwen_model = None
_qwen_lock = threading.Lock()

def _get_qwen_model():
    global _qwen_model
    if _qwen_model is not None:
        return _qwen_model if _qwen_model is not False else None

    acquired = _qwen_lock.acquire(timeout=4.0)
    if not acquired:
        return None
    try:
        if _qwen_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                device = "cuda" if torch.cuda.is_available() else "cpu"
                print(f"[ModelPipeline] Loading Qwen3-Embedding-0.6B on {device}...")
                _qwen_model = SentenceTransformer(
                    "Qwen/Qwen3-Embedding-0.6B",
                    device=device,
                    trust_remote_code=True
                )
                print("[ModelPipeline] Qwen3-Embedding-0.6B loaded successfully.")
            except Exception as e:
                print(f"[ModelPipeline] Notice: Qwen3 model loading deferred or fallback active: {e}")
                _qwen_model = False
    finally:
        _qwen_lock.release()
    return _qwen_model if _qwen_model is not False else None

def get_text_embedding(text: str) -> List[float]:
    clean = text.strip()[:600] if text else ""
    if not clean:
        return generate_fallback_embedding("empty", TEXT_DIM)

    model = _get_qwen_model()
    if model is not None:
        try:
            emb = model.encode(clean, normalize_embeddings=True)
            if hasattr(emb, "tolist"):
                emb = emb.tolist()
            if len(emb) == TEXT_DIM:
                return emb
        except Exception as e:
            print(f"[ModelPipeline] Qwen encode notice: {e}")

    return generate_fallback_embedding(clean, TEXT_DIM)

def get_text_embeddings_batch(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    clean_texts = [t.strip()[:600] if t else "" for t in texts]
    model = _get_qwen_model()
    if model is not None:
        try:
            embs = model.encode(clean_texts, batch_size=16, normalize_embeddings=True)
            if hasattr(embs, "tolist"):
                embs = embs.tolist()
            if len(embs) == len(texts) and len(embs[0]) == TEXT_DIM:
                return embs
        except Exception as e:
            print(f"[ModelPipeline] Qwen batch encode notice: {e}")

    return [generate_fallback_embedding(t or "empty", TEXT_DIM) for t in clean_texts]

# ─── 2. Image + Video Frame Embeddings: Jina CLIP v2 ───────────────────────────
_jina_clip_model = None
_jina_clip_lock = threading.Lock()

def _ensure_jina_cache():
    """Ensures dynamic modules (e.g. mha.py, stochastic_depth.py) are present in HF cache on Windows."""
    try:
        from pathlib import Path
        import shutil
        from huggingface_hub import hf_hub_download
        base_mod = Path.home() / ".cache" / "huggingface" / "modules" / "transformers_modules" / "jinaai" / "xlm-roberta-flash-implementation"
        if base_mod.exists():
            for target_dir in base_mod.glob("*"):
                if target_dir.is_dir():
                    for fname in ["mha.py", "stochastic_depth.py"]:
                        dest = target_dir / fname
                        if not dest.exists():
                            print(f"[ModelPipeline] Fetching required Jina dependency {fname}...")
                            fpath = hf_hub_download(repo_id="jinaai/xlm-roberta-flash-implementation", filename=fname)
                            shutil.copy(fpath, dest)
                            print(f"[ModelPipeline] Successfully restored {fname} to {dest}")
    except Exception as e:
        print(f"[ModelPipeline] Jina cache check notice: {e}")

def _get_jina_clip_model():
    """Returns the Jina CLIP v2 model, or None if unavailable. Never raises."""
    global _jina_clip_model
    if _jina_clip_model is not None:
        return None if _jina_clip_model is False else _jina_clip_model

    with _jina_clip_lock:
        if _jina_clip_model is not None:
            return None if _jina_clip_model is False else _jina_clip_model

        _ensure_jina_cache()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[ModelPipeline] Loading Jina CLIP v2 synchronously on {device}...")
        try:
            from transformers import AutoModel
            model = AutoModel.from_pretrained(
                "jinaai/jina-clip-v2",
                trust_remote_code=True
            ).to(device)
            model.eval()
            _jina_clip_model = model
            print(f"[ModelPipeline] Jina CLIP v2 loaded successfully on {device} (1024-dim visual embeddings active).")
            return _jina_clip_model
        except Exception as e:
            print(f"[ModelPipeline] AutoModel loading error: {e}, attempting SentenceTransformer fallback...")
            try:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer(
                    "jinaai/jina-clip-v2",
                    device=device,
                    trust_remote_code=True
                )
                _jina_clip_model = model
                print(f"[ModelPipeline] Jina CLIP v2 loaded via SentenceTransformer on {device}.")
                return _jina_clip_model
            except Exception as e2:
                print(f"[ModelPipeline] Warning: Jina CLIP v2 could not be loaded (image/visual search disabled): {e2}")
                _jina_clip_model = False
                return None

def _load_pil_image(image_input: Union[str, bytes, Image.Image]) -> Optional[Image.Image]:
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
        print(f"[ModelPipeline] Image load notice: {e}")
    return None

def get_image_embedding(image_input: Union[str, bytes, Image.Image]) -> Optional[List[float]]:
    """Encodes an image into a 1024-dim Jina CLIP v2 vector, or None if unavailable."""
    img = _load_pil_image(image_input)
    if img is None:
        return None

    model = _get_jina_clip_model()
    if model is None:
        return None

    try:
        if hasattr(model, "encode_image"):
            emb = model.encode_image([img])
        else:
            emb = model.encode([img], normalize_embeddings=True)
        if hasattr(emb, "detach"):
            emb = emb.detach().cpu().numpy()
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
            emb = emb[0]
        emb_arr = np.array(emb, dtype=np.float32)
        if len(emb_arr) == IMAGE_DIM:
            norm_vec = normalize_vector(emb_arr)
            return norm_vec.tolist()
        return None
    except Exception as e:
        print(f"[ModelPipeline] Jina CLIP image encode notice: {e}")
        return None

def get_multimodal_text_embedding(text: str) -> Optional[List[float]]:
    """
    Encodes text into the 1024-dim Jina CLIP v2 space.
    Used when a text query searches against the image / video-frame index.
    Returns None if Jina CLIP v2 is unavailable — callers must handle None.
    """
    clean = text.strip() if text else ""
    if not clean:
        clean = "empty query"

    model = _get_jina_clip_model()
    if model is None:
        print("[ModelPipeline] Jina CLIP v2 unavailable — skipping multimodal text embedding.")
        return None

    try:
        if hasattr(model, "encode_text"):
            emb = model.encode_text([clean])
        else:
            emb = model.encode([clean], normalize_embeddings=True)
        if hasattr(emb, "detach"):
            emb = emb.detach().cpu().numpy()
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
            emb = emb[0]
        emb_arr = np.array(emb, dtype=np.float32)
        if len(emb_arr) == IMAGE_DIM:
            norm_vec = normalize_vector(emb_arr)
            return norm_vec.tolist()
        print(f"[ModelPipeline] Unexpected multimodal text dimension {len(emb_arr)}, expected {IMAGE_DIM}")
        return None
    except Exception as e:
        print(f"[ModelPipeline] Jina CLIP text encode error: {e}")
        return None


# ─── 3. Face Detection & Embeddings: InsightFace ───────────────────────────────
_insightface_app = None
_insightface_lock = threading.Lock()

def _get_insightface_app():
    global _insightface_app
    if _insightface_app is None:
        with _insightface_lock:
            if _insightface_app is None:
                try:
                    from insightface.app import FaceAnalysis
                    providers = ["CPUExecutionProvider"]
                    print("[ModelPipeline] Initializing InsightFace FaceAnalysis...")
                    app = FaceAnalysis(name="buffalo_s", providers=providers)
                    app.prepare(ctx_id=-1, det_size=(640, 640))
                    _insightface_app = app
                    print("[ModelPipeline] InsightFace initialized successfully.")
                except Exception as e:
                    print(f"[ModelPipeline] Notice: InsightFace initialization deferred: {e}")
                    _insightface_app = False
    return _insightface_app if _insightface_app is not False else None

def detect_and_embed_faces(
    image_input: Union[str, bytes, Image.Image],
    min_confidence: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Runs InsightFace face detection and extraction on an image.
    Returns list of dicts:
      [
        {
          "box": [ymin, xmin, ymax, xmax],  # normalized [0, 1]
          "confidence": float,
          "embedding": List[float] (512-dim)
        }, ...
      ]
    """
    img = _load_pil_image(image_input)
    if img is None:
        return []

    app = _get_insightface_app()
    if app is not None:
        try:
            # InsightFace expects BGR numpy array
            np_img = np.array(img)[:, :, ::-1].copy()
            faces = app.get(np_img)
            results = []
            h, w = img.height, img.width

            for f in faces:
                conf = float(f.det_score) if hasattr(f, "det_score") else 0.9
                if conf < min_confidence:
                    continue

                bbox = f.bbox.astype(np.float32)  # [x1, y1, x2, y2]
                ymin = max(0.0, min(1.0, float(bbox[1]) / h))
                xmin = max(0.0, min(1.0, float(bbox[0]) / w))
                ymax = max(0.0, min(1.0, float(bbox[3]) / h))
                xmax = max(0.0, min(1.0, float(bbox[2]) / w))

                raw_emb = f.embedding
                if hasattr(raw_emb, "tolist"):
                    raw_emb = raw_emb.tolist()
                # Ensure 512-dim and normalized
                norm_emb = normalize_vector(np.array(raw_emb, dtype=np.float32)).tolist()

                results.append({
                    "box": [ymin, xmin, ymax, xmax],
                    "confidence": conf,
                    "embedding": norm_emb,
                })
            return results
        except Exception as e:
            print(f"[ModelPipeline] InsightFace inference notice: {e}")

    return []

# ─── 4. Video & Audio Transcription: faster-whisper Medium ───────────────────
_whisper_model = None
_whisper_lock = threading.Lock()
_whisper_device = None

def _get_whisper_model():
    global _whisper_model, _whisper_device
    if _whisper_model is not None:
        return _whisper_model if _whisper_model is not False else None

    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model if _whisper_model is not False else None
        try:
            from faster_whisper import WhisperModel
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute_type = "float16" if torch.cuda.is_available() else "int8"
            print(f"[ModelPipeline] Loading cached faster-whisper Medium on {device} ({compute_type})...")
            model = WhisperModel("medium", device=device, compute_type=compute_type)
            _whisper_model = model
            _whisper_device = device
            print(f"[ModelPipeline] faster-whisper Medium loaded and cached on {device}.")
            return _whisper_model
        except Exception as e:
            print(f"[ModelPipeline] faster-whisper medium error on cuda/gpu: {e}, falling back to CPU...")
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel("medium", device="cpu", compute_type="int8")
                _whisper_model = model
                _whisper_device = "cpu"
                print("[ModelPipeline] faster-whisper Medium loaded on CPU.")
                return _whisper_model
            except Exception as e2:
                print(f"[ModelPipeline] Faster-whisper medium failed: {e2}")
                _whisper_model = False
                return None

_get_whisper_medium_model = _get_whisper_model

def transcribe_audio(audio_or_video_path: str) -> List[Dict[str, Any]]:
    """
    Transcribes video or audio file using cached faster-whisper Medium.
    Returns list of segments: [{"start": float, "end": float, "text": str}]
    """
    p = Path(audio_or_video_path)
    if not p.exists():
        return []

    import time
    t0 = time.time()
    model = _get_whisper_model()
    if model is not None:
        try:
            device_str = _whisper_device or ("cuda" if torch.cuda.is_available() else "cpu")
            segments_gen, info = model.transcribe(str(p), beam_size=5, vad_filter=True)
            results = []
            for seg in segments_gen:
                text = seg.text.strip()
                if text:
                    results.append({
                        "start": round(seg.start, 2),
                        "end": round(seg.end, 2),
                        "text": text,
                    })
            elapsed = time.time() - t0
            audio_dur = getattr(info, "duration", 0.0)
            print(f"[ModelPipeline] faster-whisper Medium transcribed '{p.name}' on {device_str}: audio_dur={audio_dur:.2f}s, elapsed={elapsed:.2f}s, segments={len(results)}")
            return results
        except Exception as e:
            print(f"[ModelPipeline] faster-whisper Medium transcription notice: {e}")

    # Fallback using standard openai-whisper if faster-whisper fails
    try:
        import whisper
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[ModelPipeline] Falling back to openai-whisper medium on {device}...")
        w_model = whisper.load_model("medium", device=device)
        res = w_model.transcribe(str(p))
        results = []
        for s in res.get("segments", []):
            txt = s.get("text", "").strip()
            if txt:
                results.append({
                    "start": round(s.get("start", 0.0), 2),
                    "end": round(s.get("end", 0.0), 2),
                    "text": txt,
                })
        elapsed = time.time() - t0
        print(f"[ModelPipeline] openai-whisper transcribed '{p.name}' in {elapsed:.2f}s, segments={len(results)}")
        return results
    except Exception as e:
        print(f"[ModelPipeline] Standard whisper fallback error: {e}")

    return []


# ─── 5. OCR Extraction: Tesseract ─────────────────────────────────────────────
def run_ocr(image_input: Union[str, bytes, Image.Image]) -> str:
    """Runs Tesseract OCR on an image and returns cleaned text."""
    try:
        import pytesseract
        img = _load_pil_image(image_input)
        if img is None:
            return ""
        text = pytesseract.image_to_string(img)
        return text.strip()
    except Exception as e:
        print(f"[ModelPipeline] OCR notice: {e}")
        return ""
