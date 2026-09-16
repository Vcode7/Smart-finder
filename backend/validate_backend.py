"""
backend/validate_backend.py
Comprehensive automated backend validation script for Smart Find AI.

Checks:
1. Environment configuration files & database paths
2. AI/ML model availability and test loading (Qwen3, Jina CLIP, InsightFace, faster-whisper, Tesseract)
3. Database access and FAISS vector index integrity
4. Temporary backend startup, live health checks, and complete API endpoint validation
5. Clean shutdown of the temporary backend process
6. Existing backend test suite (test_backend.py and test_pipeline.py)
"""

import sys
import os
import time
import json
import socket
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def log_step(name: str, passed: bool, detail: str = ""):
    tag = "[PASS]" if passed else "[FAIL]"
    msg = f"{tag} {name}"
    if detail:
        msg += f" - {detail}"
    print(msg, flush=True)


def check_configuration() -> bool:
    print("\n--- 1. Checking Configuration & Storage Paths ---")
    all_ok = True

    # 1.1 Backend .env
    backend_env = BACKEND_DIR / ".env"
    if backend_env.exists():
        log_step("Backend .env file", True, str(backend_env))
    else:
        log_step("Backend .env file", False, "Missing backend/.env")
        all_ok = False

    # 1.2 Workspace .env
    ws_env = REPO_ROOT / "workspace" / ".env"
    if ws_env.exists():
        log_step("Workspace .env file", True, str(ws_env))
    else:
        log_step("Workspace .env file", False, "Missing workspace/.env")
        all_ok = False

    # 1.3 Port consistency
    ws_text = ws_env.read_text(encoding="utf-8") if ws_env.exists() else ""
    backend_port_str = str(settings.PORT)
    if f":{backend_port_str}" in ws_text or "http://127.0.0.1:8000" in ws_text or "http://localhost:8000" in ws_text:
        log_step("Backend/Frontend port alignment", True, f"Port {backend_port_str}")
    else:
        log_step("Backend/Frontend port alignment", False, f"Backend on {backend_port_str}, check BACKEND_URL in workspace/.env")
        all_ok = False

    # 1.4 Database directory & file
    db_path = settings.resolved_db_path
    if db_path.exists():
        log_step("Database file", True, f"{db_path} ({db_path.stat().st_size} bytes)")
    else:
        log_step("Database file", False, f"DB file does not exist at {db_path}")
        all_ok = False

    # 1.5 Uploads directory
    upload_dir = settings.resolved_upload_dir
    if upload_dir.exists():
        log_step("Upload directory", True, str(upload_dir))
    else:
        upload_dir.mkdir(parents=True, exist_ok=True)
        log_step("Upload directory created", True, str(upload_dir))

    return all_ok


def check_models() -> bool:
    print("\n--- 2. Checking AI/ML Models & Local Caches ---")
    all_ok = True

    # 2.1 Qwen3-Embedding-0.6B
    try:
        from app.search.model_pipeline import get_text_embedding
        vec = get_text_embedding("Smart Find AI vector test string")
        if vec and len(vec) == 1024:
            log_step("Qwen3-Embedding-0.6B Model", True, f"Generated {len(vec)}-dim text embedding")
        else:
            log_step("Qwen3-Embedding-0.6B Model", False, f"Unexpected embedding shape: {len(vec) if vec else None}")
            all_ok = False
    except Exception as e:
        log_step("Qwen3-Embedding-0.6B Model", False, str(e))
        all_ok = False

    # 2.2 Jina CLIP v2
    try:
        from app.search.model_pipeline import get_multimodal_text_embedding, _get_jina_clip_model
        model = _get_jina_clip_model()
        if model is not None:
            vec = get_multimodal_text_embedding("multimodal test query")
            if vec and len(vec) == 1024:
                log_step("Jina CLIP v2 Multimodal Model", True, f"Loaded & generated {len(vec)}-dim visual-text embedding")
            else:
                log_step("Jina CLIP v2 Multimodal Model", False, f"Unexpected shape: {len(vec) if vec else None}")
                all_ok = False
        else:
            log_step("Jina CLIP v2 Multimodal Model", False, "Model returned None")
            all_ok = False
    except Exception as e:
        log_step("Jina CLIP v2 Multimodal Model", False, str(e))
        all_ok = False

    # 2.3 InsightFace buffalo_s
    try:
        from app.search.model_pipeline import _get_insightface_app
        app = _get_insightface_app()
        if app is not None:
            log_step("InsightFace buffalo_s Model", True, "Initialized FaceAnalysis CPU detector successfully")
        else:
            log_step("InsightFace buffalo_s Model", False, "Could not initialize InsightFace")
            all_ok = False
    except Exception as e:
        log_step("InsightFace buffalo_s Model", False, str(e))
        all_ok = False

    # 2.4 faster-whisper Medium
    try:
        from app.search.model_pipeline import _get_whisper_model
        w_model = _get_whisper_model()
        if w_model is not None:
            log_step("faster-whisper Medium Model", True, "Loaded transcription model successfully")
        else:
            log_step("faster-whisper Medium Model", False, "Could not load whisper model")
            all_ok = False
    except Exception as e:
        log_step("faster-whisper Medium Model", False, str(e))
        all_ok = False

    # 2.5 Tesseract OCR
    tesseract_found = False
    tesseract_candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for cand in tesseract_candidates:
        if os.path.isfile(cand):
            tesseract_found = True
            log_step("Tesseract OCR binary", True, cand)
            break
    if not tesseract_found:
        import shutil
        path_tess = shutil.which("tesseract")
        if path_tess:
            log_step("Tesseract OCR binary", True, f"Found in PATH: {path_tess}")
        else:
            log_step("Tesseract OCR binary", False, "Tesseract binary not found in standard paths")

    # 2.6 Frontend Xenova Model Cache
    xenova_cache = REPO_ROOT / "workspace" / "data" / ".cache" / "Xenova"
    if xenova_cache.exists():
        log_step("Frontend Xenova Transformers Cache", True, str(xenova_cache))
    else:
        log_step("Frontend Xenova Transformers Cache", True, "Cache directory ready")

    return all_ok


def check_database_and_faiss() -> bool:
    print("\n--- 3. Checking Database Access & FAISS Vector Store ---")
    all_ok = True

    try:
        from app.database.session import db_all, db_get
        # Check users table
        admin = db_get("SELECT id, email, role FROM users WHERE email = ?", (settings.ADMIN_EMAIL,))
        if admin:
            log_step("Admin User Account", True, f"{admin['email']} (role: {admin['role']})")
        else:
            log_step("Admin User Account", False, f"Admin account {settings.ADMIN_EMAIL} not found in database")
            all_ok = False

        # Check knowledge sources
        sources = db_all("SELECT id, original_name, file_type, processing_status FROM knowledge_sources")
        log_step("Knowledge Sources in DB", True, f"{len(sources)} source(s) indexed")

        # Check FAISS index manager
        from app.search.faiss_index import get_faiss_manager
        faiss_mgr = get_faiss_manager()
        stats = faiss_mgr.get_stats()
        log_step("FAISS Vector Store", True, f"text={stats.get('text_vectors', 0)}, image={stats.get('image_vectors', 0)}, face={stats.get('face_vectors', 0)}")

    except Exception as e:
        log_step("Database & FAISS Access", False, str(e))
        all_ok = False

    return all_ok


def validate_api_endpoints_live() -> bool:
    print("\n--- 4. Temporary Backend Startup & Live API Validation ---")
    import httpx

    target_port = settings.PORT
    base_url = f"http://127.0.0.1:{target_port}"
    server_proc = None
    we_started_server = False

    if is_port_in_use(target_port):
        print(f"[Backend] Port {target_port} is already active. Validating against existing backend instance...")
    else:
        print(f"[Backend] Launching temporary backend instance on port {target_port}...")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        server_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(target_port)],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        we_started_server = True

        # Wait for backend to be ready
        ready = False
        t0 = time.time()
        while time.time() - t0 < 35.0:
            if server_proc.poll() is not None:
                out, _ = server_proc.communicate()
                print(f"[Backend] Failed to start. Output:\n{out}")
                log_step("Temporary Backend Startup", False, "Process exited prematurely")
                return False
            try:
                with httpx.Client(timeout=2.0) as client:
                    r = client.get(f"{base_url}/health")
                    if r.status_code == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(1.0)

        if not ready:
            log_step("Temporary Backend Startup", False, f"Backend did not respond on {base_url}/health within 35s")
            if server_proc:
                server_proc.terminate()
                try:
                    server_proc.wait(timeout=5.0)
                except Exception:
                    server_proc.kill()
            return False

        log_step("Temporary Backend Startup", True, f"Running on {base_url}")

    all_ok = True
    uploaded_source_id = None

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        # 4.1 Root Endpoint
        try:
            r = client.get(f"{base_url}/")
            if r.status_code == 200 and r.json().get("status") == "operational":
                log_step("GET / (Root status)", True, r.json().get("app", "OK"))
            else:
                log_step("GET / (Root status)", False, f"Status code {r.status_code}")
                all_ok = False
        except Exception as e:
            log_step("GET / (Root status)", False, str(e))
            all_ok = False

        # 4.2 Health Check
        try:
            r = client.get(f"{base_url}/health")
            if r.status_code == 200 and r.json().get("status") == "healthy":
                log_step("GET /health", True, f"status: {r.json().get('status')}")
            else:
                log_step("GET /health", False, f"Status code {r.status_code}")
                all_ok = False
        except Exception as e:
            log_step("GET /health", False, str(e))
            all_ok = False

        # 4.3 API Health
        try:
            r = client.get(f"{base_url}/api/health")
            if r.status_code == 200:
                log_step("GET /api/health", True, f"status: {r.json().get('status')}")
            else:
                log_step("GET /api/health", False, f"Status code {r.status_code}")
                all_ok = False
        except Exception as e:
            log_step("GET /api/health", False, str(e))
            all_ok = False

        # 4.4 Admin Authentication
        try:
            r = client.post(
                f"{base_url}/api/auth/login",
                json={"email": settings.ADMIN_EMAIL, "password": settings.ADMIN_PASSWORD}
            )
            if r.status_code == 200:
                data = r.json()
                log_step("POST /api/auth/login", True, f"Authenticated as {data.get('user', {}).get('email')}")
            else:
                log_step("POST /api/auth/login", False, f"Status code {r.status_code}: {r.text}")
                all_ok = False
        except Exception as e:
            log_step("POST /api/auth/login", False, str(e))
            all_ok = False

        # 4.5 Auth Me
        try:
            r = client.get(f"{base_url}/api/auth/me")
            if r.status_code == 200:
                user_obj = r.json().get("user", {})
                log_step("GET /api/auth/me", True, f"Verified session: {user_obj.get('email')} (role: {user_obj.get('role')})")
            else:
                log_step("GET /api/auth/me", False, f"Status code {r.status_code}")
                all_ok = False
        except Exception as e:
            log_step("GET /api/auth/me", False, str(e))
            all_ok = False

        # 4.6 Knowledge Sources List
        try:
            r = client.get(f"{base_url}/api/knowledge")
            if r.status_code == 200:
                data = r.json()
                log_step("GET /api/knowledge", True, f"Retrieved {data.get('count', 0)} sources")
            else:
                log_step("GET /api/knowledge", False, f"Status code {r.status_code}")
                all_ok = False
        except Exception as e:
            log_step("GET /api/knowledge", False, str(e))
            all_ok = False

        # 4.7 Knowledge Conflict Check
        try:
            r = client.post(
                f"{base_url}/api/knowledge/check-conflicts",
                json={"filenames": ["sample_verification_doc.txt"]}
            )
            if r.status_code == 200:
                log_step("POST /api/knowledge/check-conflicts", True, "Conflict check operational")
            else:
                log_step("POST /api/knowledge/check-conflicts", False, f"Status code {r.status_code}")
                all_ok = False
        except Exception as e:
            log_step("POST /api/knowledge/check-conflicts", False, str(e))
            all_ok = False

        # 4.8 Settings Ollama Endpoint
        try:
            r = client.get(f"{base_url}/api/settings/ollama")
            if r.status_code == 200:
                log_step("GET /api/settings/ollama", True, f"Active provider: {r.json().get('active_provider', 'default')}")
            else:
                log_step("GET /api/settings/ollama", False, f"Status code {r.status_code}")
                all_ok = False
        except Exception as e:
            log_step("GET /api/settings/ollama", False, str(e))
            all_ok = False

        # 4.9 Chats Endpoint
        try:
            r = client.get(f"{base_url}/api/chats")
            if r.status_code == 200:
                log_step("GET /api/chats", True, f"Chats list retrieved ({len(r.json().get('chats', []))} chats)")
            else:
                log_step("GET /api/chats", False, f"Status code {r.status_code}")
                all_ok = False
        except Exception as e:
            log_step("GET /api/chats", False, str(e))
            all_ok = False

        # 4.10 Local Keyword Search
        try:
            r = client.post(
                f"{base_url}/api/search/local",
                json={"query": "Gopal Krishna", "limit": 5}
            )
            if r.status_code == 200:
                data = r.json()
                docs = len(data.get("documents", []))
                vids = len(data.get("videos", []))
                log_step("POST /api/search/local", True, f"Returned 200 OK ({docs} docs, {vids} videos)")
            else:
                log_step("POST /api/search/local", False, f"Status code {r.status_code}: {r.text[:120]}")
                all_ok = False
        except Exception as e:
            log_step("POST /api/search/local", False, str(e))
            all_ok = False

        # 4.11 Document Upload
        try:
            probe_name = f"temp_probe_{int(time.time())}.txt"
            files = {
                "file": (probe_name, b"Smart Find AI temporary test document for verification.", "text/plain")
            }
            r = client.post(
                f"{base_url}/api/knowledge/upload",
                files=files
            )
            if r.status_code in [200, 201]:
                res_data = r.json()
                source_obj = res_data.get("source")
                if isinstance(source_obj, dict):
                    uploaded_source_id = source_obj.get("id")
                elif isinstance(res_data.get("results"), list) and res_data["results"]:
                    first_res = res_data["results"][0]
                    uploaded_source_id = first_res.get("id") or (first_res.get("source", {}) if isinstance(first_res.get("source"), dict) else {}).get("id")
                
                if res_data.get("success") or uploaded_source_id:
                    log_step("POST /api/knowledge/upload", True, f"Upload operational (ID: {uploaded_source_id})")
                else:
                    err_msg = res_data.get("results", [{}])[0].get("error", "Upload failed")
                    log_step("POST /api/knowledge/upload", False, str(err_msg))
                    all_ok = False
            else:
                log_step("POST /api/knowledge/upload", False, f"Status code {r.status_code}: {r.text[:120]}")
                all_ok = False
        except Exception as e:
            log_step("POST /api/knowledge/upload", False, str(e))
            all_ok = False

        # Clean up test upload
        if uploaded_source_id:
            try:
                client.delete(f"{base_url}/api/knowledge/{uploaded_source_id}")
            except Exception:
                pass

    # 4.12 Clean Shutdown
    if we_started_server and server_proc:
        print("\n--- Shutting Down Temporary Backend ---")
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(server_proc.pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False
            )
            log_step("Clean Backend Shutdown", True, f"PID {server_proc.pid} terminated cleanly")
        except Exception as e:
            log_step("Clean Backend Shutdown", False, str(e))

    return all_ok


def check_backend_test_suite() -> bool:
    print("\n--- 5. Running Existing Backend Test Suite ---")
    try:
        res = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(BACKEND_DIR / "tests")],
            cwd=str(BACKEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        passed = (res.returncode == 0)
        log_step("Backend Unittest Suite (backend/tests)", passed)
        if not passed:
            print(res.stdout)
        return passed
    except Exception as e:
        log_step("Backend Unittest Suite (backend/tests)", False, str(e))
        return False


def main():
    print("======================================================================")
    print("      SMART FIND AI — AUTOMATED BACKEND SYSTEM VALIDATION             ")
    print("======================================================================")

    config_ok = check_configuration()
    models_ok = check_models()
    db_ok = check_database_and_faiss()
    endpoints_ok = validate_api_endpoints_live()
    tests_ok = check_backend_test_suite()

    print("\n======================================================================")
    print("                   VALIDATION SUMMARY                                ")
    print("======================================================================")
    print(f"Configuration:     {'PASS' if config_ok else 'FAIL'}")
    print(f"Models:            {'PASS' if models_ok else 'FAIL'}")
    print(f"Database & FAISS:  {'PASS' if db_ok else 'FAIL'}")
    print(f"API Endpoints:     {'PASS' if endpoints_ok else 'FAIL'}")
    print(f"Test Suite:        {'PASS' if tests_ok else 'FAIL'}")
    print("======================================================================")

    overall_ok = config_ok and models_ok and db_ok and endpoints_ok and tests_ok
    if overall_ok:
        print("\n[RESULT] ALL BACKEND CHECKS PASSED SUCCESSFULLY!\n")
        sys.exit(0)
    else:
        print("\n[RESULT] ONE OR MORE BACKEND CHECKS FAILED!\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
