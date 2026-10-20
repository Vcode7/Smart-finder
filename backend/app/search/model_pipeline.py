"""
app/search/model_pipeline.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
All embedding/model functions return Optional — never a fallback vector.
Callers MUST check for None and skip FAISS insertion / FAISS query when None.

Models loaded (lazily, on first use):
  1. Qwen3-Embedding-0.6B  → 1024-dim text embeddings (queries use the model's "query" prompt)
  2. Qwen3-VL-Embedding-2B → 1024-dim image / text-for-image / image+text embeddings
     (plus Qwen3-VL-Reranker-2B, which judges the best pictures for a typed query)
  3. InsightFace buffalo_s → 512-dim face embeddings (ArcFace), GPU when available
  4. faster-whisper        → audio / video transcription
  5. Tesseract             → OCR

A model that fails to load is retried after MODEL_RETRY_SECONDS instead of being
disabled for the lifetime of the process. Each model has an inference lock:
HF fast tokenizers are not safe for concurrent use ("Already borrowed").
"""
import contextlib
import os
import io
import math
import time
import threading
from pathlib import Path
import re
from typing import Callable, Dict, Any, Iterator, List, Optional, Tuple, Union
import numpy as np
from PIL import Image, ImageOps
import torch

from app.core.config import settings
from app.search.constants import IMAGE_EMBED_MODEL, TEXT_EMBED_MAX_CHARS, VISUAL_RERANK_MODEL

# ── Dimension Constants ────────────────────────────────────────────────────────
TEXT_DIM  = 1024   # Qwen3-Embedding-0.6B
IMAGE_DIM = 1024   # Qwen3-VL-Embedding-2B (2048-dim, Matryoshka-truncated)
FACE_DIM  = 512    # InsightFace ArcFace

MODEL_RETRY_SECONDS = 300.0
WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3")

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

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


class _LazyModel:
    """
    Thread-safe lazy loader that remembers failures only for a retry interval.

    A loaded model can be *parked* in system RAM (park_fn) and brought back to the GPU
    in about a second (unpark_fn) — far cheaper than reloading from disk. unload_fn
    releases memory that garbage collection alone would not (CTranslate2).
    """

    def __init__(self, name: str, loader, park_fn=None, unpark_fn=None, unload_fn=None):
        self.name = name
        self._loader = loader
        self._park_fn = park_fn
        self._unpark_fn = unpark_fn
        self._unload_fn = unload_fn
        self._model = None
        self.parked = False
        self._failed_at: Optional[float] = None
        self._load_lock = threading.Lock()
        self.infer_lock = threading.Lock()

    def get(self):
        if self._model is not None:
            return self._model
        if self._failed_at is not None and (time.time() - self._failed_at) < MODEL_RETRY_SECONDS:
            return None
        with self._load_lock:
            if self._model is not None:
                return self._model
            if self._failed_at is not None and (time.time() - self._failed_at) < MODEL_RETRY_SECONDS:
                return None
            try:
                t0 = time.time()
                self._model = self._loader()
                self._failed_at = None
                print(f"[ModelPipeline] {self.name} ready in {time.time() - t0:.1f}s")
            except Exception as e:
                self._failed_at = time.time()
                print(f"[ModelPipeline] {self.name} failed to load (will retry in {int(MODEL_RETRY_SECONDS)}s): {e}")
        return self._model

    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> bool:
        """Drop the model (waiting for a running inference) and return its memory."""
        with self._load_lock, self.infer_lock:
            model, self._model = self._model, None
            self.parked = False
            if model is not None and self._unload_fn is not None:
                try:
                    self._unload_fn(model)
                except Exception as e:
                    print(f"[ModelPipeline] {self.name} unload notice: {e}")
        if model is None:
            return False
        del model
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"[ModelPipeline] {self.name} unloaded")
        return True

    def park(self) -> bool:
        """Move the loaded model to system RAM (frees its VRAM; still usable for torch models)."""
        if self._park_fn is None or not torch.cuda.is_available():
            return False
        with self.infer_lock:
            if self._model is None or self.parked:
                return False
            try:
                self._park_fn(self._model)
                self.parked = True
            except Exception as e:
                print(f"[ModelPipeline] {self.name} could not be parked: {e}")
                return False
        torch.cuda.empty_cache()
        print(f"[ModelPipeline] {self.name} parked in system RAM")
        return True

    def unpark(self) -> bool:
        if self._unpark_fn is None:
            return False
        with self.infer_lock:
            if self._model is None or not self.parked:
                return False
            try:
                self._unpark_fn(self._model)
                self.parked = False
            except Exception as e:
                print(f"[ModelPipeline] {self.name} could not return to the GPU: {e}")
                return False
        return True


def _device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def _cached_first(load):
    """
    Load from the local HuggingFace cache without any network round-trips (about 20 s
    faster per model, and works offline); download only when the model isn't cached.
    """
    try:
        return load(True)
    except Exception as e:
        print(f"[ModelPipeline] Not in the local cache ({type(e).__name__}); downloading...")
        return load(False)


def _torch_park(model) -> None:
    model.to("cpu")


def _torch_unpark(model) -> None:
    model.to("cuda")


# Measured on an RTX 4050 (6 GB): larger batches are no faster, only use more VRAM
TEXT_BATCH_SIZE = 8
IMAGE_BATCH_SIZE = 4


# ── 1. Text Embeddings: Qwen3-Embedding-0.6B ──────────────────────────────────
def _load_qwen():
    from sentence_transformers import SentenceTransformer
    device = _device()
    print(f"[ModelPipeline] Loading Qwen3-Embedding-0.6B on {device}...")
    kwargs = {"device": device, "trust_remote_code": True}
    if device == "cuda":
        kwargs["model_kwargs"] = {"dtype": torch.float16}
    model = _cached_first(lambda local: SentenceTransformer(
        "Qwen/Qwen3-Embedding-0.6B", local_files_only=local, **kwargs))
    print("[ModelPipeline] Qwen3-Embedding-0.6B loaded successfully.")
    return model


_qwen = _LazyModel("Qwen3-Embedding-0.6B", _load_qwen, park_fn=_torch_park, unpark_fn=_torch_unpark)


def _get_qwen_model():
    return _qwen.get()


def _encode_text(texts: List[str], is_query: bool) -> Optional[np.ndarray]:
    model = _get_qwen_model()
    if model is None:
        return None
    kwargs: Dict[str, Any] = {"normalize_embeddings": True, "batch_size": TEXT_BATCH_SIZE}
    if is_query and "query" in (getattr(model, "prompts", None) or {}):
        kwargs["prompt_name"] = "query"
    with _qwen.infer_lock:
        embs = model.encode(texts, **kwargs)
    return np.asarray(embs, dtype=np.float32)


def get_text_embedding(text: str) -> Optional[List[float]]:
    """
    Encodes a document/passage into a 1024-dim Qwen3 vector (no instruction prompt).
    Returns None when the model is unavailable or encoding fails.
    """
    clean = text.strip()[:TEXT_EMBED_MAX_CHARS] if text else ""
    if not clean:
        return None
    try:
        embs = _encode_text([clean], is_query=False)
        if embs is not None and embs.shape[-1] == TEXT_DIM:
            return embs[0].tolist()
        if embs is not None:
            print(f"[ModelPipeline] Unexpected Qwen3 dimension {embs.shape[-1]}, expected {TEXT_DIM}")
    except Exception as e:
        print(f"[ModelPipeline] Qwen3 encode error: {e}")
    return None


def get_text_query_embedding(text: str) -> Optional[List[float]]:
    """
    Encodes a search query with Qwen3's retrieval instruction ("query" prompt).
    Documents are embedded without a prompt; queries with it — as the model expects.
    """
    clean = text.strip()[:TEXT_EMBED_MAX_CHARS] if text else ""
    if not clean:
        return None
    try:
        embs = _encode_text([clean], is_query=True)
        if embs is not None and embs.shape[-1] == TEXT_DIM:
            return embs[0].tolist()
    except Exception as e:
        print(f"[ModelPipeline] Qwen3 query encode error: {e}")
    return None


def get_text_embeddings_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """
    Batch-encodes documents/passages. Returns a list of Optional embeddings — entries
    are None when that text is empty or encoding fails.
    """
    if not texts:
        return []
    clean_texts = [t.strip()[:TEXT_EMBED_MAX_CHARS] if t else "" for t in texts]
    non_empty = [(i, t) for i, t in enumerate(clean_texts) if t]
    out: List[Optional[List[float]]] = [None] * len(texts)
    if not non_empty:
        return out
    try:
        embs = _encode_text([t for _, t in non_empty], is_query=False)
        if embs is None:
            return out
        if embs.shape[-1] != TEXT_DIM:
            print("[ModelPipeline] Qwen3 batch encode unexpected shape")
            return out
        for (i, _), e in zip(non_empty, embs):
            out[i] = e.tolist()
    except Exception as e:
        print(f"[ModelPipeline] Qwen3 batch encode error: {e}")
    return out


# ── 2. Image + Video Frame Embeddings: Qwen3-VL-Embedding-2B ──────────────────
# Pictures, text and picture+text share one space. Inputs go through the model's chat
# template (the instruction is the system message) and are pooled at the last token, as
# in the reference implementation (scripts/qwen3_vl_embedding.py; cosine >= 0.998 with
# it). The model is Matryoshka-trained: vectors keep their first IMAGE_DIM dimensions.
VL_MIN_PIXELS = 64 * 32 * 32           # small pictures are enlarged to at least 64 visual tokens
VL_MAX_PIXELS = 640 * 640              # ~400 visual tokens: 2.3 pictures/s on an RTX 4050 (6 GB)
VL_FACTOR = 32                         # 16 px patches, merged 2 x 2
VL_MAX_TOKENS = 8192
IMAGE_INSTRUCTION = "Represent the user's input."       # pictures: the model's default
# Picked on eval/visual_queries.json (MRR 0.91; "Retrieve images or video frames that
# match the description." 0.83, the default instruction 0.74)
IMAGE_QUERY_INSTRUCTION = "Find a picture that matches the given description."
COMPOSE_INSTRUCTION = "Retrieve images that look like the given image, changed as the text describes."


def vl_resize(img: Image.Image, min_pixels: int = VL_MIN_PIXELS, max_pixels: int = VL_MAX_PIXELS) -> Image.Image:
    """Sides rounded to multiples of 32 px and the area brought within [min, max] pixels,
    keeping the aspect ratio (qwen_vl_utils.smart_resize)."""
    img = img.convert("RGB")
    w, h = img.size
    hb, wb = max(VL_FACTOR, round(h / VL_FACTOR) * VL_FACTOR), max(VL_FACTOR, round(w / VL_FACTOR) * VL_FACTOR)
    if hb * wb > max_pixels:
        beta = math.sqrt(h * w / max_pixels)
        hb = max(VL_FACTOR, math.floor(h / beta / VL_FACTOR) * VL_FACTOR)
        wb = max(VL_FACTOR, math.floor(w / beta / VL_FACTOR) * VL_FACTOR)
    elif hb * wb < min_pixels:
        beta = math.sqrt(min_pixels / (h * w))
        hb, wb = math.ceil(h * beta / VL_FACTOR) * VL_FACTOR, math.ceil(w * beta / VL_FACTOR) * VL_FACTOR
    return img if (wb, hb) == img.size else img.resize((wb, hb), Image.Resampling.BICUBIC)


def _vl_conversation(system: str, content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"role": "system", "content": [{"type": "text", "text": system}]},
            {"role": "user", "content": content}]


def _load_image_model():
    from transformers import AutoProcessor
    from transformers.models.qwen3_vl.modeling_qwen3_vl import Qwen3VLModel
    device = _device()
    print(f"[ModelPipeline] Loading {IMAGE_EMBED_MODEL} on {device}...")
    kwargs: Dict[str, Any] = {"dtype": torch.bfloat16} if device == "cuda" else {}
    # The checkpoint keeps its weights under "model." (it was saved from an embedding wrapper)
    model = _cached_first(lambda local: Qwen3VLModel.from_pretrained(
        IMAGE_EMBED_MODEL, key_mapping={r"^model\.": ""}, local_files_only=local, **kwargs)).to(device).eval()
    processor = _cached_first(lambda local: AutoProcessor.from_pretrained(
        IMAGE_EMBED_MODEL, padding_side="right", local_files_only=local))
    return {"model": model, "processor": processor}


_vision = _LazyModel("Qwen3-VL-Embedding-2B", _load_image_model,
                     park_fn=lambda r: r["model"].to("cpu"), unpark_fn=lambda r: r["model"].to("cuda"))


def _get_image_model():
    """The image embedding model ({"model", "processor"}), or None if unavailable. Never raises."""
    return _vision.get()


@contextlib.contextmanager
def pictures_on_gpu() -> Iterator[None]:
    """One trip to the GPU for several picture queries in a row (a search's attachments)
    when the image model waits in system RAM; see _vl_embed."""
    visit = _vision.parked and small_gpu()
    if visit:
        make_room(VRAM_HEADROOM_GIB + IMAGE_VRAM_GIB, keep=(_vision, _paddle_ocr))
        _vision.unpark()
    try:
        yield
    finally:
        if visit:
            settle_for_search()


def _vl_embed(items: List[Tuple[Optional[Image.Image], Optional[str]]], instruction: str) -> Optional[np.ndarray]:
    """[n, IMAGE_DIM] unit vectors for (picture, text) inputs; None when the model is unavailable."""
    r = _get_image_model()
    if r is None:
        return None
    model, proc = r["model"], r["processor"]
    convs, images = [], []
    for img, text in items:
        content: List[Dict[str, Any]] = []
        if img is not None:
            img = vl_resize(img)
            images.append(img)
            content.append({"type": "image", "image": img})
        if text:
            content.append({"type": "text", "text": text})
        convs.append(_vl_conversation(instruction, content or [{"type": "text", "text": "NULL"}]))
    prompts = proc.apply_chat_template(convs, add_generation_prompt=True, tokenize=False)
    # On small GPUs the model waits in system RAM while searching. Words alone are quick on
    # the CPU (~1.6 s); a picture is not (40 s), so it visits the GPU (~6 s with the move back).
    visit = bool(images) and _vision.parked and small_gpu()
    if visit:
        _vision.unpark()
    try:
        with _vision.infer_lock, torch.inference_mode():
            device = next(model.parameters()).device
            inputs = proc(text=prompts, images=images or None, padding=True, truncation=True, max_length=VL_MAX_TOKENS,
                          do_resize=False, return_tensors="pt").to(device)
            hidden = model(**inputs).last_hidden_state
            last = inputs["attention_mask"].sum(dim=1) - 1          # padding is on the right
            emb = hidden[torch.arange(hidden.shape[0], device=device), last][:, :IMAGE_DIM].float()
            return torch.nn.functional.normalize(emb, dim=-1).cpu().numpy()
    finally:
        if visit:
            _vision.park()


def _load_pil_image(image_input: Union[str, bytes, Image.Image]) -> Optional[Image.Image]:
    """Load an image as RGB with EXIF orientation applied; never leaves the file open."""
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
        print(f"[ModelPipeline] Image load notice: {e}")
    return None


def get_image_embedding(image_input: Union[str, bytes, Image.Image]) -> Optional[List[float]]:
    """
    Encodes an image into a 1024-dim Qwen3-VL vector.
    Returns None if the model is unavailable or encoding fails.
    """
    img = _load_pil_image(image_input)
    if img is None:
        return None
    return get_image_embeddings_batch([img])[0]


def get_image_embeddings_batch(images: List[Image.Image], batch_size: int = IMAGE_BATCH_SIZE) -> List[Optional[List[float]]]:
    """Batch-encode PIL images with Qwen3-VL. Entries are None when encoding fails."""
    out: List[Optional[List[float]]] = [None] * len(images)
    if not images or _get_image_model() is None:
        return out
    for start in range(0, len(images), batch_size):
        part = images[start:start + batch_size]
        try:
            arr = _vl_embed([(im, None) for im in part], IMAGE_INSTRUCTION)
        except Exception as e:
            print(f"[ModelPipeline] Qwen3-VL image encode error: {e}")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if len(part) > 1:   # e.g. short of GPU memory for the batch: one picture at a time
                for i, im in enumerate(part):
                    out[start + i] = get_image_embeddings_batch([im], 1)[0]
            continue
        if arr is None:
            return out
        for i, vec in enumerate(arr):
            out[start + i] = vec.tolist()
    return out


def get_multimodal_text_embedding(text: str) -> Optional[List[float]]:
    """
    Encodes a text query into the 1024-dim image space (for text→image search), using
    the retrieval instruction. Returns None if the model is unavailable. Callers must handle None.
    """
    clean = text.strip()[:TEXT_EMBED_MAX_CHARS] if text else ""
    if not clean:
        return None
    try:
        arr = _vl_embed([(None, clean)], IMAGE_QUERY_INSTRUCTION)
        return arr[0].tolist() if arr is not None else None
    except Exception as e:
        print(f"[ModelPipeline] Qwen3-VL text encode error: {e}")
    return None


def get_composed_query_embedding(image: Optional[Image.Image], text: str) -> Optional[List[float]]:
    """A picture and words as one query in the image space ("this photo, but at night")."""
    clean = text.strip()[:TEXT_EMBED_MAX_CHARS] if text else ""
    if image is None or not clean:
        return None
    try:
        arr = _vl_embed([(image, clean)], COMPOSE_INSTRUCTION)
        return arr[0].tolist() if arr is not None else None
    except Exception as e:
        print(f"[ModelPipeline] Qwen3-VL composed query error: {e}")
    return None


# Zero-shot "does this image contain readable text?" check on the image vector that
# indexing computes anyway. Tesseract takes ~1 s per photo and finds nothing in most
# natural photos, so it only runs on images that look like screenshots, documents,
# slides, signs, receipts and the like.
# Softmax temperature over the prompt similarities. 20 keeps the share of pictures sent
# to OCR per kind close to what Jina CLIP v2 did at 100 (94% of decisions agree on 1,317
# library pictures: pages 0.97, document images 0.98, keyframes 0.73, photos 0.35).
TEXT_GATE_SCALE = 20.0
_TEXT_PROMPTS = (
    "a screenshot of a computer or phone screen", "a scanned document page with printed text",
    "a photo of a printed page or letter", "a presentation slide with text", "a receipt or invoice",
    "a sign or poster with large text", "a whiteboard or blackboard with writing", "a chart or table with labels",
    "a handwritten note", "an identity card or certificate",
)
_NON_TEXT_PROMPTS = (
    "a photo of people", "a selfie", "a landscape or nature photo", "a photo of an animal",
    "a photo of food", "a photo of a building or street", "a photo of a room or furniture",
    "a photo of a car or vehicle", "a group photo at an event", "a close-up photo of an object",
)
_text_gate: Optional[np.ndarray] = None
_text_gate_lock = threading.Lock()


def text_likelihood(image_vec: Optional[List[float]]) -> Optional[float]:
    """Probability (0..1) that an image contains readable text; None when the image model is unavailable."""
    global _text_gate
    if image_vec is None:
        return None
    if _text_gate is None:
        with _text_gate_lock:
            if _text_gate is None:
                try:
                    vecs = _vl_embed([(None, p) for p in _TEXT_PROMPTS + _NON_TEXT_PROMPTS], IMAGE_QUERY_INSTRUCTION)
                except Exception as e:
                    print(f"[ModelPipeline] Text gate notice: {e}")
                    vecs = None
                if vecs is None:
                    return None
                _text_gate = np.asarray(vecs, dtype=np.float32)
    logits = (_text_gate @ np.asarray(image_vec, dtype=np.float32)) * TEXT_GATE_SCALE
    probs = np.exp(logits - logits.max())
    probs /= probs.sum()
    return float(probs[:len(_TEXT_PROMPTS)].sum())


# ── Reranker: Qwen3-Reranker-0.6B ─────────────────────────────────────────────
RERANKER_NAME = "Qwen/Qwen3-Reranker-0.6B"
RERANK_BATCH_SIZE = 8
RERANK_MAX_DOC_TOKENS = 480
RERANK_INSTRUCTION = (
    "Given a search query, judge whether this passage from the user's files (a document, "
    "a transcript of speech, text read from an image, or a description) is relevant to the query"
)
_RERANK_PREFIX = ("<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and "
                  "the Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n")
_RERANK_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def _load_reranker():
    from transformers import AutoModelForCausalLM, AutoTokenizer
    device = _device()
    print(f"[ModelPipeline] Loading {RERANKER_NAME} on {device}...")
    tokenizer = _cached_first(lambda local: AutoTokenizer.from_pretrained(
        RERANKER_NAME, padding_side="left", local_files_only=local))
    kwargs: Dict[str, Any] = {"dtype": torch.float16} if device == "cuda" else {}
    model = _cached_first(lambda local: AutoModelForCausalLM.from_pretrained(
        RERANKER_NAME, local_files_only=local, **kwargs)).to(device).eval()
    yes_no = [tokenizer.convert_tokens_to_ids("no"), tokenizer.convert_tokens_to_ids("yes")]
    return {
        "model": model,
        "tokenizer": tokenizer,
        "prefix": tokenizer.encode(_RERANK_PREFIX, add_special_tokens=False),
        "suffix": tokenizer.encode(_RERANK_SUFFIX, add_special_tokens=False),
        "yes_no": yes_no,
    }


def _reranker_park(r) -> None:
    r["model"].to("cpu")


def _reranker_unpark(r) -> None:
    r["model"].to("cuda")


_reranker = _LazyModel("Qwen3-Reranker-0.6B", _load_reranker, park_fn=_reranker_park, unpark_fn=_reranker_unpark)


def rerank(query: str, passages: List[str], instruction: Optional[str] = None) -> Optional[List[float]]:
    """
    Relevance of each passage to the query as a probability in [0, 1] (the model's
    P("yes")). Returns None when the reranker is unavailable.
    """
    if not query.strip() or not passages:
        return [] if not passages else None
    r = _reranker.get()
    if r is None:
        return None
    model, tok = r["model"], r["tokenizer"]
    instruction = instruction or RERANK_INSTRUCTION
    prefix, suffix = r["prefix"], r["suffix"]
    scores: List[float] = []
    try:
        with _reranker.infer_lock, torch.inference_mode():
            device = next(model.parameters()).device
            head = model.get_output_embeddings().weight[r["yes_no"]]            # [2, hidden]
            for start in range(0, len(passages), RERANK_BATCH_SIZE):
                batch = passages[start:start + RERANK_BATCH_SIZE]
                pairs = [f"<Instruct>: {instruction}\n<Query>: {query.strip()[:1000]}\n<Document>: {p}" for p in batch]
                enc = tok(pairs, padding=False, truncation=True, return_attention_mask=False,
                          max_length=RERANK_MAX_DOC_TOKENS + 160)
                enc["input_ids"] = [prefix + ids + suffix for ids in enc["input_ids"]]
                enc = tok.pad(enc, padding=True, return_tensors="pt")
                enc = {k: v.to(device) for k, v in enc.items()}
                # Only the last position's yes/no logits are needed: projecting every
                # position onto the 152k-token vocabulary would cost ~1.5 GB per batch
                hidden = model.model(**enc).last_hidden_state[:, -1, :]
                logits = hidden @ head.T                                          # [batch, 2]
                probs = torch.softmax(logits.float(), dim=-1)[:, 1]
                scores.extend(float(p) for p in probs.cpu())
        return scores
    except Exception as e:
        print(f"[ModelPipeline] Rerank error: {e}")
        return None


# ── Picture reranker: Qwen3-VL-Reranker-2B ────────────────────────────────────
# Judges whether a picture matches a typed query: P("yes") at the last position, read
# through the yes-minus-no row of the LM head, with the prompt format of the reference
# implementation (scripts/qwen3_vl_reranker.py). Needs ~4 GB more VRAM, so "auto" only
# turns it on for GPUs with at least VISUAL_RERANK_MIN_VRAM_GIB.
VL_RERANK_MAX_PIXELS = 448 * 448
VL_RERANK_BATCH_SIZE = 4
VISUAL_RERANK_MIN_VRAM_GIB = 12.0
VL_RERANK_INSTRUCTION = "Retrieve images or video frames that match the description."
_VL_RERANK_SYSTEM = ('Judge whether the Document meets the requirements based on the Query and the Instruct '
                     'provided. Note that the answer can only be "yes" or "no".')


def _load_vl_reranker():
    from transformers import AutoProcessor
    from transformers.models.qwen3_vl.modeling_qwen3_vl import Qwen3VLForConditionalGeneration
    device = _device()
    print(f"[ModelPipeline] Loading {VISUAL_RERANK_MODEL} on {device}...")
    kwargs: Dict[str, Any] = {"dtype": torch.bfloat16} if device == "cuda" else {}
    lm = _cached_first(lambda local: Qwen3VLForConditionalGeneration.from_pretrained(
        VISUAL_RERANK_MODEL, local_files_only=local, **kwargs))
    processor = _cached_first(lambda local: AutoProcessor.from_pretrained(
        VISUAL_RERANK_MODEL, padding_side="left", local_files_only=local))
    vocab = processor.tokenizer.get_vocab()
    head = lm.lm_head.weight.data
    yes_minus_no = (head[vocab["yes"]] - head[vocab["no"]]).clone()
    model = lm.model.to(device).eval()      # the full LM head is not needed
    del lm, head
    return {"model": model, "processor": processor, "yes_minus_no": yes_minus_no}


_vl_reranker = _LazyModel("Qwen3-VL-Reranker-2B", _load_vl_reranker,
                          park_fn=lambda r: r["model"].to("cpu"), unpark_fn=lambda r: r["model"].to("cuda"))


def visual_rerank_enabled() -> bool:
    mode = settings.VISUAL_RERANK.strip().lower()
    if mode in ("on", "true", "1"):
        return True
    if mode in ("off", "false", "0") or not torch.cuda.is_available():
        return False
    return torch.cuda.get_device_properties(0).total_memory / 2**30 >= VISUAL_RERANK_MIN_VRAM_GIB


def rerank_images(query: str, images: List[Image.Image], instruction: Optional[str] = None) -> Optional[List[float]]:
    """
    How well each picture matches the query, as a probability in [0, 1]. Returns None
    when the picture reranker is unavailable.
    """
    if not query.strip() or not images:
        return [] if not images else None
    r = _vl_reranker.get()
    if r is None:
        return None
    model, proc = r["model"], r["processor"]
    head = [{"type": "text", "text": f"<Instruct>: {instruction or VL_RERANK_INSTRUCTION}"},
            {"type": "text", "text": "<Query>:"}, {"type": "text", "text": query.strip()[:1000]},
            {"type": "text", "text": "\n<Document>:"}]
    scores: List[float] = []
    try:
        with _vl_reranker.infer_lock, torch.inference_mode():
            device = next(model.parameters()).device
            dtype = next(model.parameters()).dtype
            direction = r["yes_minus_no"].to(device, dtype)
            for start in range(0, len(images), VL_RERANK_BATCH_SIZE):
                part = [vl_resize(im, max_pixels=VL_RERANK_MAX_PIXELS) for im in images[start:start + VL_RERANK_BATCH_SIZE]]
                convs = [_vl_conversation(_VL_RERANK_SYSTEM, head + [{"type": "image", "image": im}]) for im in part]
                prompts = proc.apply_chat_template(convs, add_generation_prompt=True, tokenize=False)
                inputs = proc(text=prompts, images=part, padding=True, do_resize=False, return_tensors="pt").to(device)
                last = model(**inputs).last_hidden_state[:, -1]          # padding is on the left
                scores.extend(float(s) for s in torch.sigmoid((last @ direction).float()).cpu())
        return scores
    except Exception as e:
        print(f"[ModelPipeline] Picture rerank error: {e}")
        return None


# ── Captions & on-screen text: Florence-2-base ────────────────────────────────
FLORENCE_NAME = "florence-community/Florence-2-base"   # native transformers weights
CAPTION_BATCH_SIZE = 4
CAPTION_TASK = "<MORE_DETAILED_CAPTION>"
OCR_TASK = "<OCR>"


def _load_florence():
    from transformers import AutoProcessor, Florence2ForConditionalGeneration
    device = _device()
    print(f"[ModelPipeline] Loading Florence-2-base on {device}...")
    kwargs: Dict[str, Any] = {"dtype": torch.float16} if device == "cuda" else {}
    model = _cached_first(lambda local: Florence2ForConditionalGeneration.from_pretrained(
        FLORENCE_NAME, local_files_only=local, **kwargs)).to(device).eval()
    processor = _cached_first(lambda local: AutoProcessor.from_pretrained(FLORENCE_NAME, local_files_only=local))
    return {"model": model, "processor": processor}


_florence = _LazyModel("Florence-2-base", _load_florence,
                       park_fn=lambda r: r["model"].to("cpu"), unpark_fn=lambda r: r["model"].to("cuda"))


def florence_describe(images: List[Image.Image], task: str = CAPTION_TASK, max_new_tokens: int = 96) -> List[Optional[str]]:
    """
    Florence-2 on a list of images: a detailed caption (default) or the text in the image
    (task=OCR_TASK). Entries are None when the model is unavailable or fails.
    """
    out: List[Optional[str]] = [None] * len(images)
    if not images:
        return out
    r = _florence.get()
    if r is None:
        return out
    if _florence.parked:
        _florence.unpark()
    model, proc = r["model"], r["processor"]
    try:
        with _florence.infer_lock, torch.inference_mode():
            device = next(model.parameters()).device
            dtype = next(model.parameters()).dtype
            for start in range(0, len(images), CAPTION_BATCH_SIZE):
                batch = [im.convert("RGB") for im in images[start:start + CAPTION_BATCH_SIZE]]
                inputs = proc(text=[task] * len(batch), images=batch, return_tensors="pt")
                ids = model.generate(
                    input_ids=inputs["input_ids"].to(device),
                    pixel_values=inputs["pixel_values"].to(device, dtype),
                    max_new_tokens=max_new_tokens, num_beams=3, do_sample=False,
                )
                for i, (text, im) in enumerate(zip(proc.batch_decode(ids, skip_special_tokens=False), batch)):
                    parsed = proc.post_process_generation(text, task=task, image_size=im.size)
                    value = parsed.get(task) if isinstance(parsed, dict) else parsed
                    out[start + i] = re.sub(r"\s+", " ", str(value or "")).replace("<pad>", "").strip() or None
    except Exception as e:
        print(f"[ModelPipeline] Florence-2 error: {e}")
    return out


def release_caption_model() -> bool:
    return _florence.unload()


# ── Sound: CLAP (laion/larger_clap_general) ───────────────────────────────────
CLAP_NAME = "laion/larger_clap_general"
CLAP_RATE = 48000
CLAP_WINDOW_S = 10.0
CLAP_HOP_S = 5.0
CLAP_BATCH = 8
CLAP_SILENCE_RMS = 1e-3


def _load_clap():
    from transformers import ClapModel, ClapProcessor
    device = _device()
    print(f"[ModelPipeline] Loading CLAP on {device}...")
    kwargs: Dict[str, Any] = {"dtype": torch.float16} if device == "cuda" else {}
    model = _cached_first(lambda local: ClapModel.from_pretrained(CLAP_NAME, local_files_only=local, **kwargs)).to(device).eval()
    processor = _cached_first(lambda local: ClapProcessor.from_pretrained(CLAP_NAME, local_files_only=local))
    return {"model": model, "processor": processor}


_clap = _LazyModel("CLAP", _load_clap, park_fn=lambda r: r["model"].to("cpu"), unpark_fn=lambda r: r["model"].to("cuda"))


def _iter_audio_windows(path: str, should_stop=None):
    """Yield (start_s, samples) windows of 10 s every 5 s, decoded and resampled as a stream."""
    import av
    win, hop = int(CLAP_WINDOW_S * CLAP_RATE), int(CLAP_HOP_S * CLAP_RATE)
    buf = np.zeros(0, dtype=np.float32)
    offset = 0
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            return
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=CLAP_RATE)
        for frame in container.decode(stream):
            if should_stop is not None and should_stop():
                return
            for f in resampler.resample(frame):
                buf = np.concatenate([buf, f.to_ndarray()[0].astype(np.float32)])
            while len(buf) >= win:
                yield offset / CLAP_RATE, buf[:win]
                buf = buf[hop:]
                offset += hop
        for f in resampler.resample(None):
            buf = np.concatenate([buf, f.to_ndarray()[0].astype(np.float32)])
    if len(buf) >= 2 * CLAP_RATE:          # a trailing piece of at least 2 s
        yield offset / CLAP_RATE, buf


def _clap_embed_audio(model, proc, windows: List[np.ndarray]) -> np.ndarray:
    inputs = proc(audio=windows, sampling_rate=CLAP_RATE, return_tensors="pt")
    device = next(model.parameters()).device
    dtype = next(model.parameters()).dtype
    inputs = {k: (v.to(device, dtype) if v.dtype.is_floating_point else v.to(device)) for k, v in inputs.items()}
    feats = model.get_audio_features(**inputs)
    return torch.nn.functional.normalize(feats.float(), dim=-1).cpu().numpy()


def clap_audio_windows(path: str, should_stop=None) -> List[Tuple[float, float, List[float]]]:
    """CLAP vectors for every 10 s window (5 s hop) of a file's soundtrack; silent windows skipped."""
    r = _clap.get()
    if r is None:
        return []
    if _clap.parked:
        _clap.unpark()
    model, proc = r["model"], r["processor"]
    out: List[Tuple[float, float, List[float]]] = []
    pending: List[Tuple[float, np.ndarray]] = []

    def flush() -> None:
        if not pending:
            return
        with _clap.infer_lock, torch.inference_mode():
            vecs = _clap_embed_audio(model, proc, [w for _, w in pending])
        for (start, w), v in zip(pending, vecs):
            out.append((round(start, 2), round(start + len(w) / CLAP_RATE, 2), v.tolist()))
        pending.clear()

    try:
        for start, window in _iter_audio_windows(path, should_stop):
            if float(np.sqrt(np.mean(window ** 2))) < CLAP_SILENCE_RMS:
                continue
            pending.append((start, window))
            if len(pending) >= CLAP_BATCH:
                flush()
        flush()
    except Exception as e:
        print(f"[ModelPipeline] CLAP audio error: {e}")
    return out


def clap_audio_embedding(path: str) -> Optional[List[float]]:
    """One CLAP vector for a short query clip (mean of its windows)."""
    wins = clap_audio_windows(path)
    if not wins:
        return None
    mean = np.mean(np.asarray([w[2] for w in wins], dtype=np.float32), axis=0)
    return normalize_vector(mean).tolist()


def clap_text_embedding(text: str) -> Optional[List[float]]:
    clean = (text or "").strip()
    if not clean:
        return None
    r = _clap.get()
    if r is None:
        return None
    model, proc = r["model"], r["processor"]
    try:
        with _clap.infer_lock, torch.inference_mode():
            inputs = proc(text=[clean[:300]], return_tensors="pt", padding=True)
            device = next(model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}
            feats = model.get_text_features(**inputs)
            return torch.nn.functional.normalize(feats.float(), dim=-1)[0].cpu().tolist()
    except Exception as e:
        print(f"[ModelPipeline] CLAP text error: {e}")
        return None


def release_sound_model() -> bool:
    return _clap.unload()


def warmup_query_models() -> None:
    """Load the models every search needs, so the first query doesn't pay a cold start."""
    loaders = [_get_qwen_model, _reranker.get, _get_image_model]
    if visual_rerank_enabled():
        loaders.insert(2, _vl_reranker.get)
    for loader in loaders:
        try:
            loader()
        except Exception as e:
            print(f"[ModelPipeline] Warm-up notice: {e}")
    if small_gpu():
        _vision.park()


# ── 3. Face Detection & Embeddings: InsightFace ────────────────────────────────
# buffalo_l (SCRFD-10G + ArcFace R50) is used for folder libraries; buffalo_s remains
# only for the legacy index, whose stored face vectors were made with it.
LIBRARY_FACE_MODEL = "buffalo_l"


def _make_insightface_loader(name: str):
    def _load():
        import onnxruntime as ort
        if hasattr(ort, "preload_dlls"):
            try:
                ort.preload_dlls()
            except Exception:
                pass
        from insightface.app import FaceAnalysis
        providers = ["CPUExecutionProvider"]
        ctx_id = -1
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            ctx_id = 0
        print(f"[ModelPipeline] Initializing InsightFace FaceAnalysis ({name}, {providers[0]})...")
        app = FaceAnalysis(name=name, allowed_modules=["detection", "recognition"], providers=providers)
        app.prepare(ctx_id=ctx_id, det_size=(640, 640))
        return app
    return _load


_insightface_models: Dict[str, _LazyModel] = {
    "buffalo_s": _LazyModel("InsightFace buffalo_s", _make_insightface_loader("buffalo_s")),
    "buffalo_l": _LazyModel("InsightFace buffalo_l", _make_insightface_loader("buffalo_l")),
}
_insightface = _insightface_models["buffalo_s"]


def _get_insightface_app(model_name: str = "buffalo_s"):
    return _insightface_models[model_name].get()


def detect_and_embed_faces(
    image_input: Union[str, bytes, Image.Image],
    min_confidence: float = 0.5,
    model_name: str = "buffalo_s",
) -> List[Dict[str, Any]]:
    """
    Runs InsightFace face detection and embedding extraction on an image.
    Returns list of dicts: {"box": [ymin, xmin, ymax, xmax], "confidence": float,
    "embedding": List[float], "size_px": int} (size_px = shorter side of the face box).
    Returns [] when the model is unavailable.
    """
    img = _load_pil_image(image_input)
    if img is None:
        return []
    lazy = _insightface_models[model_name]
    app = _get_insightface_app(model_name)
    if app is None:
        return []
    try:
        np_img = np.array(img)[:, :, ::-1].copy()  # BGR for InsightFace
        with lazy.infer_lock:
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
            raw_emb = getattr(f, "embedding", None)
            if raw_emb is None:
                continue
            norm_emb = normalize_vector(np.asarray(raw_emb, dtype=np.float32)).tolist()
            results.append({
                "box": [ymin, xmin, ymax, xmax],
                "confidence": conf,
                "embedding": norm_emb,
                "size_px": int(min(bbox[2] - bbox[0], bbox[3] - bbox[1])),
            })
        return results
    except Exception as e:
        print(f"[ModelPipeline] InsightFace inference error: {e}")
    return []


# ── 4. Audio & Video Transcription: faster-whisper ────────────────────────────
_whisper_device: Optional[str] = None


def _load_whisper():
    global _whisper_device
    from faster_whisper import WhisperModel
    if torch.cuda.is_available():
        try:
            print(f"[ModelPipeline] Loading faster-whisper {WHISPER_MODEL_NAME} on cuda (int8_float16)...")
            model = _cached_first(lambda local: WhisperModel(
                WHISPER_MODEL_NAME, device="cuda", compute_type="int8_float16", local_files_only=local))
            _whisper_device = "cuda"
            return model
        except Exception as e:
            print(f"[ModelPipeline] faster-whisper CUDA load failed ({e}), falling back to CPU...")
    print(f"[ModelPipeline] Loading faster-whisper {WHISPER_MODEL_NAME} on cpu (int8)...")
    model = _cached_first(lambda local: WhisperModel(
        WHISPER_MODEL_NAME, device="cpu", compute_type="int8", local_files_only=local))
    _whisper_device = "cpu"
    return model


def _whisper_park(model) -> None:
    if _whisper_device == "cuda":
        model.model.unload_model(to_cpu=True)   # weights stay in RAM; back on the GPU in ~1 s


def _whisper_unpark(model) -> None:
    if _whisper_device == "cuda":
        model.model.load_model()


def _whisper_unload(model) -> None:
    model.model.unload_model()                  # garbage collection alone keeps the VRAM


_whisper = _LazyModel("faster-whisper", _load_whisper,
                      park_fn=_whisper_park, unpark_fn=_whisper_unpark, unload_fn=_whisper_unload)


def _get_whisper_model():
    return _whisper.get()


_get_whisper_medium_model = _get_whisper_model  # backward-compat alias


# ── VRAM coordination for indexing ─────────────────────────────────────────────
# Search keeps resident: Qwen3-Embedding 1.1 + Qwen3-VL-Embedding 4.0 (+0.3 per batch of
# 640 px pictures) + reranker 1.2 + faces 0.4 GB, and the picture reranker (4.0) where
# it is enabled. On a 6 GB card (Windows already holds ~1 GB) that does not all fit:
# passes park the rerankers, then the image model, in system RAM.
# PP-OCRv6 takes ~1 GB while indexing (two ONNX Runtime arenas + cuDNN workspace) and is
# dropped last when a pass needs room; it reloads in a few seconds.
#
# Below SMALL_GPU_GIB the search models don't all fit, and the one that spills into shared
# memory crawls: on a 6 GB card, reranking 40 passages took 40 s instead of 1.3 s. There
# the image model waits in system RAM while searching and takes the GPU only while
# pictures are indexed (the rerankers wait in RAM meanwhile).
WHISPER_VRAM_GIB = 1.6
IMAGE_VRAM_GIB = 4.3        # Qwen3-VL-Embedding-2B bf16 + a batch of pictures
VRAM_HEADROOM_GIB = 0.7
SMALL_GPU_GIB = 10.0


def small_gpu() -> bool:
    return torch.cuda.is_available() and torch.cuda.get_device_properties(0).total_memory / 2**30 < SMALL_GPU_GIB


def vram_free_gib() -> Optional[float]:
    if not torch.cuda.is_available():
        return None
    free, _total = torch.cuda.mem_get_info()
    return free / 2**30


CAPTION_VRAM_GIB = 1.1      # Florence-2-base fp16 + beam-search activations
SOUND_VRAM_GIB = 0.8        # CLAP fp16 + a batch of 10 s windows
_parked_for_passes: List["_LazyModel"] = []
_arbiter_lock = threading.Lock()


def make_room(need_gib: float, keep: Tuple["_LazyModel", ...] = ()) -> None:
    """
    Free VRAM for an indexing pass by parking search models in system RAM — the
    rerankers first, then the image model (searches keep working meanwhile, on the CPU) —
    and, if that is not enough, dropping PaddleOCR (ONNX sessions cannot be parked; it
    reloads when next needed). Qwen3-Embedding stays: every pass embeds text with it.
    """
    if not torch.cuda.is_available():
        return
    with _arbiter_lock:
        torch.cuda.empty_cache()
        for model in (_vl_reranker, _reranker, _vision):
            if (vram_free_gib() or 0.0) >= need_gib:
                break
            if model in keep:
                continue
            if model.is_loaded() and not model.parked and model.park():
                _parked_for_passes.append(model)
        if (vram_free_gib() or 0.0) < need_gib and _paddle_ocr.is_loaded() and _paddle_ocr not in keep:
            _paddle_ocr.unload()


def restore_parked() -> None:
    with _arbiter_lock:
        while _parked_for_passes:
            model = _parked_for_passes.pop()
            if model is _vision and small_gpu():
                continue        # stays in RAM until pictures are indexed again
            model.unpark()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def on_gpu(model: "_LazyModel") -> bool:
    return torch.cuda.is_available() and model.is_loaded() and not model.parked


def reranker_on_gpu() -> bool:
    return on_gpu(_reranker)


def prepare_for_transcription() -> None:
    """Make room for Whisper on the GPU."""
    whisper_on_gpu = on_gpu(_whisper)
    make_room(VRAM_HEADROOM_GIB + (0.0 if whisper_on_gpu else WHISPER_VRAM_GIB))
    if _whisper.parked:
        _whisper.unpark()


def finish_transcription() -> None:
    """Park Whisper in system RAM and give the search models their VRAM back."""
    _whisper.park()
    restore_parked()


def prepare_for_captions() -> None:
    make_room(VRAM_HEADROOM_GIB + (0.0 if on_gpu(_florence) else CAPTION_VRAM_GIB))
    if _florence.parked:
        _florence.unpark()


def finish_captions() -> None:
    _florence.park()
    restore_parked()


def prepare_for_image_vectors() -> None:
    """The image pass needs only the image model: the rerankers make way for it."""
    make_room(VRAM_HEADROOM_GIB + (0.0 if on_gpu(_vision) else IMAGE_VRAM_GIB), keep=(_vision,))
    if _vision.parked:
        _vision.unpark()


def finish_image_vectors() -> None:
    settle_for_search()


def prepare_for_pictures() -> None:
    """Pictures are about to be indexed: on small GPUs the image model takes the GPU."""
    if small_gpu() and not on_gpu(_vision):
        prepare_for_image_vectors()


def settle_for_search() -> None:
    """Picture indexing is over: on small GPUs the image model returns to system RAM and
    the rerankers to the GPU."""
    if small_gpu():
        _vision.park()
    restore_parked()


def prepare_for_sounds() -> None:
    make_room(VRAM_HEADROOM_GIB + (0.0 if on_gpu(_clap) else SOUND_VRAM_GIB))
    if _clap.parked:
        _clap.unpark()


def finish_sounds() -> None:
    _clap.park()
    restore_parked()


def release_transcription_model() -> bool:
    """Free Whisper entirely (VRAM and RAM); it reloads from disk on the next transcription."""
    released = _whisper.unload()
    restore_parked()
    return released


def release_indexing_models() -> None:
    """Idle for a while: free the RAM held by parked indexing-only models."""
    for model in (_whisper, _florence, _clap):
        model.unload()
    restore_parked()


def release_cached_vram() -> None:
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def trim_vram(min_free_gib: float = 0.6) -> None:
    """Return cached blocks to the driver when the GPU is nearly full (avoids spilling into
    shared system memory on Windows, which makes every model slow)."""
    free = vram_free_gib()
    if free is not None and free < min_free_gib:
        torch.cuda.empty_cache()


WHISPER_BATCH_SIZE = 8
SEGMENT_SPLIT_S = 8.0       # long segments are split at punctuation after this long...
SEGMENT_MAX_S = 14.0        # ...and at the next word boundary after this long
_SENTENCE_END_CHARS = (".", "?", "!", "।", "॥", ",", ";", ":")
_batched_pipelines: Dict[int, Any] = {}


def _split_segment(seg) -> List[Dict[str, Any]]:
    """Split one Whisper segment into shorter pieces using its word timestamps."""
    words = list(getattr(seg, "words", None) or [])
    text = seg.text.strip()
    if not words or seg.end - seg.start <= SEGMENT_MAX_S:
        return [{"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text}] if text else []
    out: List[Dict[str, Any]] = []
    cur: List[Any] = []
    for w in words:
        cur.append(w)
        dur = w.end - cur[0].start
        token = w.word.strip()
        if (dur >= SEGMENT_SPLIT_S and token.endswith(_SENTENCE_END_CHARS)) or dur >= SEGMENT_MAX_S:
            piece = "".join(x.word for x in cur).strip()
            if piece:
                out.append({"start": round(cur[0].start, 2), "end": round(w.end, 2), "text": piece})
            cur = []
    if cur:
        piece = "".join(x.word for x in cur).strip()
        if piece:
            out.append({"start": round(cur[0].start, 2), "end": round(cur[-1].end, 2), "text": piece})
    return out


def transcribe_media(audio_or_video_path: str, should_stop=None) -> Dict[str, Any]:
    """
    Transcribes audio (or a video's soundtrack) with faster-whisper's batched pipeline —
    about 6x faster than sequential decoding at the same accuracy (measured on Hindi
    speech). Long segments are split at punctuation/pauses using word timestamps so a
    search hit seeks to the right moment.
    Returns {"segments": [{"start", "end", "text"}], "language", "language_probability", "duration"}.
    `should_stop` (optional callable) ends a long transcription early between segments.
    Short of GPU memory it retries with smaller batches, then sequentially; if every
    attempt fails it raises (a failed transcription must not look like silence).
    """
    empty: Dict[str, Any] = {"segments": [], "language": None, "language_probability": None, "duration": None}
    p = Path(audio_or_video_path)
    if not p.exists():
        return empty
    t0 = time.time()
    model = _get_whisper_model()
    if model is None:
        return empty
    if _whisper.parked:
        _whisper.unpark()
    attempts: List[Tuple[str, int]] = [("batched", WHISPER_BATCH_SIZE), ("batched", 4), ("batched", 2), ("sequential", 1)]
    last_error: Optional[Exception] = None
    with _whisper.infer_lock:
        for mode, batch_size in attempts:
            try:
                if mode == "batched":
                    from faster_whisper import BatchedInferencePipeline
                    pipeline = _batched_pipelines.get(id(model))
                    if pipeline is None:
                        _batched_pipelines.clear()
                        pipeline = _batched_pipelines[id(model)] = BatchedInferencePipeline(model=model)
                    segments_gen, info = pipeline.transcribe(
                        str(p), batch_size=batch_size, beam_size=5, without_timestamps=False, word_timestamps=True)
                else:
                    segments_gen, info = model.transcribe(str(p), beam_size=5, vad_filter=True, word_timestamps=True)
                results: List[Dict[str, Any]] = []
                for seg in segments_gen:          # decoding happens while iterating
                    if should_stop is not None and should_stop():
                        break
                    results.extend(_split_segment(seg))
            except Exception as e:
                last_error = e
                print(f"[ModelPipeline] Transcription attempt ({mode}, batch {batch_size}) failed: {e}")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                continue
            elapsed = time.time() - t0
            audio_dur = float(getattr(info, "duration", 0.0) or 0.0)
            print(f"[ModelPipeline] faster-whisper transcribed '{p.name}' ({audio_dur:.1f}s audio in {elapsed:.1f}s, "
                  f"{len(results)} segments, {getattr(info, 'language', '?')}, {mode} {batch_size}, {_whisper_device})")
            return {"segments": results, "language": getattr(info, "language", None),
                    "language_probability": getattr(info, "language_probability", None), "duration": audio_dur}
    raise RuntimeError(f"Transcription failed: {last_error}")


def transcribe_audio(audio_or_video_path: str, should_stop=None) -> List[Dict[str, Any]]:
    """Segments only: [{"start": float, "end": float, "text": str}]. [] on failure."""
    try:
        return transcribe_media(audio_or_video_path, should_stop=should_stop)["segments"]
    except Exception as e:
        print(f"[ModelPipeline] {e}")
        return []


# ── 5. OCR: PaddleOCR PP-OCRv6, Tesseract for Hindi ───────────────────────────
# PP-OCRv6 reads English and Latin-script text far better than Tesseract and runs on the
# same ONNX Runtime CUDA provider as InsightFace (no Paddle framework). It has no
# Devanagari model: Hindi lines come back as low-confidence junk (CJK look-alikes at
# ~0.6), so those lines are re-read by Tesseract (eng+hin) and its Devanagari lines kept.
OCR_DET_MAX_SIDE = 1280         # detector input; scanned pages and 30 MP photos read fine at this size
OCR_GPU_MEM_MIB = 1024          # ONNX Runtime arena cap per model (detector, recognizer)
OCR_DROP_SCORE = 0.5            # lines read with less confidence are noise
OCR_WEAK_MIN_CHARS = 8          # unsure lines must hold this much text before Tesseract is asked
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_CJK = re.compile(r"[\u3040-\u30FF\u3400-\u9FFF\uF900-\uFAFF]")
_ocr_lang: Optional[str] = None


def _load_paddle_ocr():
    import onnxruntime as ort
    if hasattr(ort, "preload_dlls"):
        try:
            ort.preload_dlls()
        except Exception:
            pass
    from paddleocr import PaddleOCR
    gpu = "CUDAExecutionProvider" in ort.get_available_providers()
    # medium on a GPU (~0.5 s a page); on the CPU small reads as well, 4x faster
    tier = settings.OCR_PADDLE_MODEL.strip().lower() or ("medium" if gpu else "small")
    kwargs: Dict[str, Any] = {}
    if gpu:
        # HEURISTIC: the default exhaustive cuDNN search reruns for every new line-batch
        # shape (15 s a page instead of 0.5 s)
        kwargs["engine_config"] = {
            "providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
            "provider_options": [{"device_id": 0, "cudnn_conv_algo_search": "HEURISTIC",
                                  "arena_extend_strategy": "kSameAsRequested",
                                  "gpu_mem_limit": OCR_GPU_MEM_MIB * 2**20}, {}],
        }
    print(f"[ModelPipeline] Initializing PaddleOCR PP-OCRv6_{tier} ({'CUDA' if gpu else 'CPU'})...")
    return PaddleOCR(
        engine="onnxruntime", device="gpu:0" if gpu else "cpu",
        text_detection_model_name=f"PP-OCRv6_{tier}_det", text_recognition_model_name=f"PP-OCRv6_{tier}_rec",
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
        text_det_limit_side_len=OCR_DET_MAX_SIDE, text_det_limit_type="max", **kwargs,
    )


_paddle_ocr = _LazyModel("PaddleOCR PP-OCRv6", _load_paddle_ocr)


def _paddle_read(img: Image.Image) -> Optional[List[Tuple[str, float]]]:
    """(text, confidence) per detected line in reading order; None when PaddleOCR is unavailable."""
    ocr = _paddle_ocr.get()
    if ocr is None:
        return None
    try:
        with _paddle_ocr.infer_lock:
            res = ocr.predict(np.asarray(img.convert("RGB")))
        out = res[0].json["res"]
        return [(t.strip(), float(s)) for t, s in zip(out["rec_texts"], out["rec_scores"]) if t.strip()]
    except Exception as e:      # e.g. VRAM exhausted: this image goes to Tesseract
        print(f"[ModelPipeline] PaddleOCR notice: {e}")
        return None


def _ocr_languages() -> str:
    """Configured OCR languages, restricted to those Tesseract actually has installed."""
    global _ocr_lang
    if _ocr_lang is None:
        wanted = [l for l in settings.OCR_LANGUAGES.split("+") if l.strip()]
        try:
            import pytesseract
            available = set(pytesseract.get_languages(config=""))
            chosen = [l for l in wanted if l in available]
            _ocr_lang = "+".join(chosen) if chosen else "eng"
        except Exception:
            _ocr_lang = "eng"
    return _ocr_lang


def _tesseract_read(img: Image.Image) -> str:
    try:
        import pytesseract
        return pytesseract.image_to_string(img, lang=_ocr_languages()).strip()
    except Exception as e:
        print(f"[ModelPipeline] OCR notice: {e}")
        return ""


def _pick_ocr_text(lines: List[Tuple[str, float]], read_tesseract: Callable[[], str],
                   hindi: bool, min_conf: float) -> str:
    """
    Text from PP-OCRv6's lines. When Hindi is wanted and enough text was read with low
    confidence, Tesseract's Devanagari lines replace PP-OCRv6's unsure lines and its CJK
    look-alikes. No lines at all means no text: Tesseract would only invent some.
    """
    weak = sum(len(t) for t, s in lines if s < min_conf)
    if hindi and weak >= OCR_WEAK_MIN_CHARS:
        deva = [l.strip() for l in read_tesseract().splitlines() if len(_DEVANAGARI.findall(l)) >= 2]
        if deva:
            return "\n".join([t for t, s in lines if s >= min_conf and not _CJK.search(t)] + deva)
    return "\n".join(t for t, s in lines if s >= OCR_DROP_SCORE)


def run_ocr(image_input: Union[str, bytes, Image.Image]) -> str:
    """Text in an image: PP-OCRv6, with Tesseract for Hindi (or for everything when OCR_ENGINE=tesseract)."""
    try:
        img = _load_pil_image(image_input)
        if img is None:
            return ""
        lines = _paddle_read(img) if settings.OCR_ENGINE.strip().lower() == "paddle" else None
        if lines is None:
            return _tesseract_read(img)
        hindi = "hin" in _ocr_languages().split("+")
        return _pick_ocr_text(lines, lambda: _tesseract_read(img), hindi, settings.OCR_PADDLE_MIN_CONFIDENCE).strip()
    except Exception as e:
        print(f"[ModelPipeline] OCR notice: {e}")
        return ""
