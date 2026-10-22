"""
API-level regression tests (isolated temp database, fake models).
"""
from pathlib import Path

import pytest

from tests.conftest import TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD


def _upload(client, name: str, content: bytes, mime: str = "text/plain"):
    return client.post("/api/knowledge/upload", files={"files": (name, content, mime)})


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"
    assert "database" not in res.json(), "unauthenticated health must not leak filesystem paths"


def test_admin_login_sets_cookie(client):
    res = client.post("/api/auth/login", json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD})
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "admin"
    assert "sf_auth" in res.cookies


# ── Security ─────────────────────────────────────────────────────────────────

def test_x_user_id_header_is_not_trusted(client):
    """Regression: any client could become admin with `x-user-id: system`."""
    res = client.get("/api/knowledge", headers={"x-user-id": "system"})
    assert res.status_code == 401
    res = client.post("/api/knowledge/reset", headers={"x-user-id": "system"})
    assert res.status_code == 401


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/knowledge", None),
    ("get", "/api/knowledge/some-id/file", None),
    ("get", "/api/knowledge/some-id/thumbnail", None),
    ("post", "/api/search/smart", {"query": "x"}),
    ("post", "/api/search/local", {"query": "x"}),
    ("post", "/api/search/similar", {"sourceId": "x"}),
    ("get", "/api/settings/ollama", None),
    ("post", "/api/summarize", {"source": {"title": "x"}}),
    ("post", "/api/knowledge/import-internet", {"sources": []}),
])
def test_data_routes_require_login(client, method, path, body):
    res = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
    assert res.status_code == 401, f"{method.upper()} {path} answered {res.status_code} without a session"


def test_signup_is_disabled_by_default(client):
    res = client.post("/api/auth/signup", json={"email": "x@y.z", "username": "x", "password": "longpassword1"})
    assert res.status_code == 403
    assert client.get("/api/auth/config").json() == {"allowSignup": False, "allowAdminSignup": False}


def test_login_lockout_after_repeated_failures(client):
    for _ in range(10):
        assert client.post("/api/auth/login", json={"email": TEST_ADMIN_EMAIL, "password": "wrong"}).status_code == 401
    res = client.post("/api/auth/login", json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD})
    assert res.status_code == 429


def test_change_password(admin_client):
    res = admin_client.post("/api/auth/change-password",
                            json={"currentPassword": "nope", "newPassword": "Another-Password-2"})
    assert res.status_code == 400
    res = admin_client.post("/api/auth/change-password",
                            json={"currentPassword": TEST_ADMIN_PASSWORD, "newPassword": "Another-Password-2"})
    assert res.status_code == 200
    admin_client.post("/api/auth/logout")
    assert admin_client.post("/api/auth/login", json={"email": TEST_ADMIN_EMAIL, "password": "Another-Password-2"}).status_code == 200


def test_upload_filename_cannot_escape_storage(admin_client, tmp_path):
    """Regression: the raw multipart filename was joined to the storage folder."""
    res = _upload(admin_client, "../../evil.txt", b"escape attempt")
    assert res.status_code == 200, res.text
    result = res.json()["results"][0]
    assert result.get("original_name") == "evil.txt"
    assert not (tmp_path.parent / "evil.txt").exists()
    from app.library.manager import get_library_manager
    uploads = get_library_manager().uploads()
    assert admin_client.get(f"/api/knowledge/{result['id']}").json()["source"]["file_path"] == "evil.txt"
    assert (uploads.root / "evil.txt").read_bytes() == b"escape attempt"


# ── Knowledge API ────────────────────────────────────────────────────────────

def test_get_sync_route_is_reachable(admin_client):
    """Regression: GET /knowledge/sync was captured by GET /knowledge/{source_id}."""
    res = admin_client.get("/api/knowledge/sync")
    assert res.status_code == 200
    assert res.json()["success"] and "libraries" in res.json()


def test_unicode_filename_streams_with_ranges(admin_client):
    """Regression: non-Latin filenames made Content-Disposition raise (HTTP 500)."""
    content = b"0123456789" * 10
    res = _upload(admin_client, "परीक्षा रिपोर्ट.txt", content)
    source_id = res.json()["results"][0]["id"]

    full = admin_client.get(f"/api/knowledge/{source_id}/file")
    assert full.status_code == 200
    assert full.content == content
    assert "filename*=utf-8''" in full.headers["content-disposition"]

    part = admin_client.get(f"/api/knowledge/{source_id}/file", headers={"Range": "bytes=0-3"})
    assert part.status_code == 206
    assert part.content == b"0123"

    suffix = admin_client.get(f"/api/knowledge/{source_id}/file", headers={"Range": "bytes=-5"})
    assert suffix.status_code == 206
    assert suffix.content == content[-5:]

    beyond = admin_client.get(f"/api/knowledge/{source_id}/file", headers={"Range": "bytes=99999-"})
    assert beyond.status_code == 416


def test_large_upload_has_no_size_limit(admin_client):
    payload = b"a" * (6 * 1024 * 1024)
    res = _upload(admin_client, "big.txt", payload)
    assert res.status_code == 200
    assert res.json()["results"][0]["file_size"] == len(payload)


def test_unsupported_upload_is_rejected(admin_client):
    res = _upload(admin_client, "tool.exe", b"MZ\x00\x01binary", "application/octet-stream")
    assert "Unsupported" in res.json()["results"][0]["error"]


def test_delete_removes_rows_files_and_kb_copy(admin_client):
    """Regression: deleting left a copy behind, so the next folder sync re-imported it."""
    import time
    from app.library.manager import get_library_manager

    res = _upload(admin_client, "notes.txt", b"Some notes about photosynthesis in plants.")
    source_id = res.json()["results"][0]["id"]
    uploads = get_library_manager().uploads()
    stored = uploads.root / "notes.txt"
    assert stored.exists()

    assert admin_client.delete(f"/api/knowledge/{source_id}").status_code == 200
    assert not stored.exists()
    assert uploads.db.scalar("SELECT COUNT(*) FROM sources WHERE id = ?", (source_id,)) == 0
    assert uploads.db.scalar("SELECT COUNT(*) FROM chunks WHERE source_id = ?", (source_id,)) == 0
    # A rescan doesn't bring it back
    admin_client.post("/api/knowledge/sync")
    time.sleep(0.5)
    assert all(s["original_name"] != "notes.txt" for s in admin_client.get("/api/knowledge").json()["sources"])


def test_reindex_all_skips_internet_sources(admin_client):
    """Regression: reindex-all emptied every internet import (its file_path is a URL)."""
    from app.database.session import db_get, db_all
    res = admin_client.post("/api/knowledge/import-internet", json={"sources": [{
        "title": "An article", "url": "https://example.com/a", "category": "article",
        "snippet": "Solar panels convert sunlight into electricity using photovoltaic cells.",
    }]})
    assert res.status_code == 200, res.text
    source_id = res.json()["imported"][0]["id"]

    # Imports are saved as Markdown files, so re-indexing re-reads them instead of
    # emptying them
    import time
    from app.library.manager import get_library_manager
    uploads = get_library_manager().uploads()

    def indexed_chunks() -> int:
        if uploads.db.scalar("SELECT status FROM sources WHERE id = ?", (source_id,)) != "indexed":
            return 0
        return uploads.db.scalar("SELECT COUNT(*) FROM chunks WHERE source_id = ?", (source_id,))

    for _ in range(100):
        if indexed_chunks():
            break
        time.sleep(0.2)
    assert indexed_chunks() >= 1
    assert admin_client.post("/api/knowledge/reindex-all").json()["success"]
    for _ in range(100):
        time.sleep(0.2)
        if indexed_chunks():
            break
    assert indexed_chunks() >= 1
    assert admin_client.post(f"/api/knowledge/{source_id}/reprocess").status_code == 200


def test_list_sources_omits_processing_logs(admin_client):
    _upload(admin_client, "a.txt", b"hello world content for listing")
    data = admin_client.get("/api/knowledge").json()
    assert data["total"] >= 1
    assert all("processing_info" not in (s.get("metadata_json") or "") for s in data["sources"])


def test_local_search_finds_uploaded_text(admin_client):
    import time
    _upload(admin_client, "biology.txt", b"Mitochondria are the powerhouse of the cell and produce ATP.")
    for _ in range(50):
        sources = admin_client.get("/api/knowledge").json()["sources"]
        if sources and sources[0]["processing_status"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    assert sources[0]["processing_status"] == "completed", sources[0].get("error_message")

    res = admin_client.post("/api/search/local", json={"query": "mitochondria powerhouse"})
    assert res.status_code == 200
    titles = [d["title"] for d in res.json()["documents"]]
    assert "biology.txt" in titles


def test_reset_keeps_stored_upload_files(admin_client):
    """Regression: resetting the legacy index deleted the stored originals in data/uploads."""
    from app.core.config import settings
    upload_dir = settings.resolved_upload_dir
    (upload_dir / "frames").mkdir(parents=True, exist_ok=True)
    original = upload_dir / "0ee1c0ce-00a1-45f6-9365-56690bf88418.pdf"
    original.write_bytes(b"%PDF-1.4 original")
    derived = upload_dir / "frames" / "f.jpg"
    derived.write_bytes(b"jpg")

    res = admin_client.post("/api/knowledge/reset")
    assert res.status_code == 200, res.text
    assert original.read_bytes() == b"%PDF-1.4 original"
    assert not derived.exists()
