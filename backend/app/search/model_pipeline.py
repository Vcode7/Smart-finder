"""
app/search/model_pipeline.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
All embedding/model functions return Optional — never a fallback vector.
Callers MUST check for None and skip FAISS insertion / FAISS query when None.

Models loaded:
  1. Qwen3-Embedding-0.6B  → 1024-dim text embeddings
  2. Jina CLIP v2          → 1024-dim image / multimodal text embeddings
  3. InsightFace buffalo_s → 512-dim face embeddings (ArcFace)
  4. faster-whisper medium → audio / video transcription
  5. Tesseract             → OCR
"""
import os
import io
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import numpy as np
from PIL import Image
import torch

from app.core.config import settings
from app.search.constants import TEXT_EMBED_MAX_CHARS

# ── Dimension Constants ────────────────────────────────────────────────────────
TEXT_DIM  = 1024   # Qwen3-Embedding-0.6B
IMAGE_DIM = 1024   # Jina CLIP v2
FACE_DIM  = 512    # InsightFace ArcFace

# Configure Tesseract OCR path
try:
    import pytesseract
    _tesseract_candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for _cand in _tesseract_candidates:
        if os.path.isfile(_cand):
            pytesseract.pytesseract.tesseract_cmd = _cand
            break
except Exception as _e:
    print(f"[ModelPipeline] Pytesseract setup warning: {_e}")

# ── Normalization helper ───────────────────────────────────────────────────────
def normalize_vector(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec, axis=-1, keepdims=True)
    norm = np.where(norm == 0, 1.0, norm)
    return (vec / norm).astype(np.float32)


# ── 1. Text Embeddings: Qwen3-Embedding-0.6B ──────────────────────────────────
_qwen_model = None
_qwen_lock = threading.Lock()

def _get_qwen_model():
    global _qwen_model
    if _qwen_model is not None:
        return _qwen_model if _qwen_model is not False else None

    # Increased timeout to survive cold load (was 4s → 45s, audit issue #26)
    acquired = _qwen_lock.acquire(timeout=45.0)
    if not acquired:
        print("[ModelPipeline] Qwen3 lock timeout — model still loading, returning None")
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
                    trust_remote_code=True,
                )
                print("[ModelPipeline] Qwen3-Embedding-0.6B loaded successfully.")
            except Exception as e:
                print(f"[ModelPipeline] Qwen3 model loading failed — text vector search DISABLED: {e}")
                _qwen_model = False
    finally:
        _qwen_lock.release()
    return _qwen_model if _qwen_model is not False else None


def get_text_embedding(text: str) -> Optional[List[float]]:
    """
    Encodes text into a 1024-dim Qwen3 vector.
    Returns None when the model is unavailable or encoding fails.
    Callers MUST skip FAISS insertion / search when None is returned.
    """
    clean = text.strip()[:TEXT_EMBED_MAX_CHARS] if text else ""
    if not clean:
        return None
    model = _get_qwen_model()
    if model is None:
        return None
    try:
        emb = model.encode(clean, normalize_embeddings=True)
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        if len(emb) == TEXT_DIM:
            return emb
        print(f"[ModelPipeline] Unexpected Qwen3 dimension {len(emb)}, expected {TEXT_DIM}")
    except Exception as e:
        print(f"[ModelPipeline] Qwen3 encode error: {e}")
    return None


def get_text_embeddings_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """
    Batch-encodes texts. Returns a list of Optional embeddings — entries may be None
    when encoding fails for that item. Callers must filter before FAISS insertion.
    """
    if not texts:
        return []
    clean_texts = [t.strip()[:TEXT_EMBED_MAX_CHARS] if t else "" for t in texts]
    model = _get_qwen_model()
    if model is None:
        return [None] * len(texts)
    try:
        embs = model.encode(clean_texts, batch_size=16, normalize_embeddings=True)
        if hasattr(embs, "tolist"):
            embs = embs.tolist()
        if len(embs) == len(texts) and len(embs[0]) == TEXT_DIM:
            return embs
        print(f"[ModelPipeline] Qwen3 batch encode unexpected shape")
    except Exception as e:
        print(f"[ModelPipeline] Qwen3 batch encode error: {e}")
    return [None] * len(texts)


# ── 2. Image + Video Frame Embeddings: Jina CLIP v2 ───────────────────────────
_jina_clip_model = None
_jina_clip_lock = threading.Lock()

def _ensure_jina_cache():
    """Ensures dynamic modules (mha.py, stochastic_depth.py) are present in HF cache on Windows."""
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
        print(f"[ModelPipeline] Loading Jina CLIP v2 on {device}...")
        try:
            from transformers import AutoModel
            model = AutoModel.from_pretrained(
                "jinaai/jina-clip-v2", trust_remote_code=True
            ).to(device)
            model.eval()
            _jina_clip_model = model
            print(f"[ModelPipeline] Jina CLIP v2 loaded successfully on {device}.")
            return _jina_clip_model
        except Exception as e:
            print(f"[ModelPipeline] AutoModel loading error: {e}, trying SentenceTransformer fallback...")
            try:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer("jinaai/jina-clip-v2", device=device, trust_remote_code=True)
                _jina_clip_model = model
                print(f"[ModelPipeline] Jina CLIP v2 loaded via SentenceTransformer.")
                return _jina_clip_model
            except Exception as e2:
                print(f"[ModelPipeline] Jina CLIP v2 failed — image/visual search DISABLED: {e2}")
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
    """
    Encodes an image into a 1024-dim Jina CLIP v2 vector.
    Returns None if the model is unavailable or encoding fails.
    Callers MUST skip FAISS insertion when None is returned.
    """
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
        if isinstance(emb, list) and emb and isinstance(emb[0], list):
            emb = emb[0]
        emb_arr = np.array(emb, dtype=np.float32)
        if len(emb_arr) == IMAGE_DIM:
            return normalize_vector(emb_arr).tolist()
        print(f"[ModelPipeline] Unexpected Jina CLIP image dimension {len(emb_arr)}")
    except Exception as e:
        print(f"[ModelPipeline] Jina CLIP image encode error: {e}")
    return None

def get_multimodal_text_embedding(text: str) -> Optional[List[float]]:
    """
    Encodes text into the 1024-dim Jina CLIP v2 space (for text→image search).
    Returns None if the model is unavailable. Callers must handle None.
    """
    clean = text.strip()[:TEXT_EMBED_MAX_CHARS] if text else ""
    if not clean:
        return None
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
        if isinstance(emb, list) and emb and isinstance(emb[0], list):
            emb = emb[0]
        emb_arr = np.array(emb, dtype=np.float32)
        if len(emb_arr) == IMAGE_DIM:
            return normalize_vector(emb_arr).tolist()
        print(f"[ModelPipeline] Unexpected multimodal text dimension {len(emb_arr)}, expected {IMAGE_DIM}")
    except Exception as e:
        print(f"[ModelPipeline] Jina CLIP text encode error: {e}")
    return None


# ── 3. Face Detection & Embeddings: InsightFace ────────────────────────────────
_insightface_app = None
_insightface_lock = threading.Lock()

def _get_insightface_app():
    global _insightface_app
    if _insightface_app is None:
        with _insightface_lock:
            if _insightface_app is None:
                try:
                    from insightface.app import FaceAnalysis
                    print("[ModelPipeline] Initializing InsightFace FaceAnalysis...")
                    app = FaceAnalysis(name="buffalo_s", providers=["CPUExecutionProvider"])
                    app.prepare(ctx_id=-1, det_size=(640, 640))
                    _insightface_app = app
                    print("[ModelPipeline] InsightFace initialized successfully.")
                except Exception as e:
                    print(f"[ModelPipeline] InsightFace initialization deferred: {e}")
                    _insightface_app = False
    return _insightface_app if _insightface_app is not False else None

def detect_and_embed_faces(
    image_input: Union[str, bytes, Image.Image],
    min_confidence: float = 0.5,
) -> List[Dict[str, Any]]:
    """
    Runs InsightFace face detection and embedding extraction on an image.
    Returns list of dicts: {"box": [ymin, xmin, ymax, xmax], "confidence": float, "embedding": List[float]}.
    Returns [] when the model is unavailable.
    """
    img = _load_pil_image(image_input)
    if img is None:
        return []
    app = _get_insightface_app()
    if app is None:
        return []
    try:
        np_img = np.array(img)[:, :, ::-1].copy()  # BGR for InsightFace
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
            norm_emb = normalize_vector(np.array(raw_emb, dtype=np.float32)).tolist()
            results.append({
                "box": [ymin, xmin, ymax, xmax],
                "confidence": conf,
                "embedding": norm_emb,
            })
        return results
    except Exception as e:
        print(f"[ModelPipeline] InsightFace inference error: {e}")
    return []


# ── 4. Audio & Video Transcription: faster-whisper Medium ─────────────────────
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
            print(f"[ModelPipeline] Loading faster-whisper Medium on {device} ({compute_type})...")
            _whisper_model = WhisperModel("medium", device=device, compute_type=compute_type)
            _whisper_device = device
            print(f"[ModelPipeline] faster-whisper Medium loaded on {device}.")
            return _whisper_model
        except Exception as e:
            print(f"[ModelPipeline] faster-whisper medium error: {e}, falling back to CPU...")
            try:
                from faster_whisper import WhisperModel
                _whisper_model = WhisperModel("medium", device="cpu", compute_type="int8")
                _whisper_device = "cpu"
                print("[ModelPipeline] faster-whisper Medium loaded on CPU.")
                return _whisper_model
            except Exception as e2:
                print(f"[ModelPipeline] faster-whisper failed completely: {e2}")
                _whisper_model = False
                return None

_get_whisper_medium_model = _get_whisper_model  # backward-compat alias

def transcribe_audio(audio_or_video_path: str) -> List[Dict[str, Any]]:
    """
    Transcribes video/audio using faster-whisper Medium.
    Returns list of segments: [{"start": float, "end": float, "text": str}].
    Falls back to openai-whisper if faster-whisper fails. Returns [] on total failure.
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
                    results.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text})
            elapsed = time.time() - t0
            audio_dur = getattr(info, "duration", 0.0)
            print(f"[ModelPipeline] faster-whisper transcribed '{p.name}' ({audio_dur:.2f}s audio, {elapsed:.2f}s elapsed, {len(results)} segments)")
            return results
        except Exception as e:
            print(f"[ModelPipeline] faster-whisper transcription error: {e}")

    # Fallback to openai-whisper
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
                results.append({"start": round(s.get("start", 0.0), 2), "end": round(s.get("end", 0.0), 2), "text": txt})
        print(f"[ModelPipeline] openai-whisper transcribed '{p.name}' in {time.time() - t0:.2f}s")
        return results
    except Exception as e:
        print(f"[ModelPipeline] openai-whisper fallback failed: {e}")

    return []


# ── 5. OCR: Tesseract ──────────────────────────────────────────────────────────
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
