"""
Download every model Smart Finder uses into the HuggingFace cache (about 14 GB in total;
models already cached are skipped), then load the face model once so InsightFace fetches
buffalo_l.

    venv\\Scripts\\python.exe scripts\\prefetch_models.py

HF_HOME in backend/.env moves the cache to another drive.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Plain HTTPS downloads: the Xet transfer protocol stalled on some connections in testing
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from app.core.config import settings  # noqa: E402,F401  (applies HF_HOME)

MODELS = [
    ("Qwen/Qwen3-Embedding-0.6B", "text search (meaning)", None),
    ("Qwen/Qwen3-Reranker-0.6B", "reranking search results", None),
    ("Qwen/Qwen3-VL-Embedding-2B", "image and video-frame search", None),
    ("Qwen/Qwen3-VL-Reranker-2B", "judging the best picture matches (GPUs with 12 GB or more)", None),
    ("florence-community/Florence-2-base", "describing pictures", ["*.json", "*.safetensors", "*.txt"]),
    ("laion/larger_clap_general", "sound search", ["*.json", "*.safetensors", "*.txt"]),
    ("Systran/faster-whisper-large-v3", "speech transcription", None),
]


def main() -> None:
    from huggingface_hub import snapshot_download
    failed = []
    for repo, purpose, patterns in MODELS:
        t0 = time.time()
        print(f"[models] {repo}  ({purpose})...", flush=True)
        try:
            snapshot_download(repo, allow_patterns=patterns)
            print(f"[models]   ready ({time.time() - t0:.0f}s)", flush=True)
        except Exception as e:
            failed.append(repo)
            print(f"[models]   FAILED: {e}", flush=True)
    print("[models] InsightFace buffalo_l (faces)...", flush=True)
    try:
        from app.search.model_pipeline import LIBRARY_FACE_MODEL, _get_insightface_app
        if _get_insightface_app(LIBRARY_FACE_MODEL) is None:
            raise RuntimeError("could not load")
        print("[models]   ready", flush=True)
    except Exception as e:
        failed.append("buffalo_l")
        print(f"[models]   FAILED: {e}", flush=True)
    print("[models] PaddleOCR PP-OCRv6 (text in images)...", flush=True)
    try:
        from app.search.model_pipeline import _paddle_ocr
        if _paddle_ocr.get() is None:
            raise RuntimeError("could not load")
        print("[models]   ready", flush=True)
    except Exception as e:
        failed.append("PP-OCRv6")
        print(f"[models]   FAILED: {e}", flush=True)
    if failed:
        sys.exit(f"[models] Not downloaded: {', '.join(failed)} (re-run this script when online)")
    print("[models] All models are available.")


if __name__ == "__main__":
    main()
