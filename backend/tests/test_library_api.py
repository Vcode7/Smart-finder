"""
Library, upload and system APIs end to end (TestClient + the real lifespan: library
manager, indexing worker and watchers), with fake models.
"""
import os
import time
from pathlib import Path

import pytest

USER_EMAIL = "viewer@smartfind-tests.dev"
USER_PASSWORD = "Viewer-Password-1"


def _wait(predicate, timeout: float = 30.0, interval: float = 0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not reached in time")


def _idle(client) -> dict:
    s = client.get("/api/libraries/status").json()
    if s["queued"] == 0 and s["processing"] == 0 and s["enrichmentPending"] == 0 and s["current"] is None:
        return s
    return {}


@pytest.fixture
def viewer(client):
    """A second, non-admin account (logged in on a separate cookie jar)."""
    from fastapi.testclient import TestClient
    from app.core.security import hash_password
    from app.database.session import db_run
    db_run("INSERT INTO users (id, email, username, password_hash, role) VALUES (?, ?, ?, ?, 'user')",
           ("viewer-1", USER_EMAIL, "viewer", hash_password(USER_PASSWORD)))
    other = TestClient(client.app)   # same running app (lifespan entered by `client`), own cookies
    res = other.post("/api/auth/login", json={"email": USER_EMAIL, "password": USER_PASSWORD})
    assert res.status_code == 200, res.text
    return other


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "Family Docs"
    (root / "trips").mkdir(parents=True)
    (root / "notes.txt").write_text("Grandma's recipe for mango pickle", encoding="utf-8")
    (root / "trips" / "goa.md").write_text("# Goa trip\nBeach day and a boat ride.", encoding="utf-8")
    return root


def test_routes_require_login_and_admin(client, viewer, folder):
    anon = client.__class__(client.app)
    assert anon.get("/api/libraries").status_code == 401
    assert anon.post("/api/uploads", json={"fileName": "a.txt", "size": 1}).status_code == 401
    assert anon.get("/api/system/fs").status_code == 401

    assert viewer.get("/api/libraries").status_code == 200
    assert viewer.post("/api/libraries", json={"path": str(folder)}).status_code == 403
    assert viewer.get("/api/system/fs").status_code == 403
    assert viewer.post("/api/libraries/files", json={"paths": [str(folder / "notes.txt")]}).status_code == 403


def test_attach_index_and_list(admin_client, folder):
    c = admin_client
    res = c.post("/api/libraries", json={"path": str(folder), "name": "Family"})
    assert res.status_code == 201, res.text
    lib = res.json()
    assert lib["name"] == "Family" and lib["online"] and lib["watching"]
    assert (folder / ".smartfind" / "index.db").exists()

    _wait(lambda: _idle(c) and c.get(f"/api/libraries/{lib['id']}").json().get("counts", {}).get("indexed") == 2)
    page = c.get(f"/api/libraries/{lib['id']}/sources").json()
    assert page["total"] == 2
    assert {s["relPath"] for s in page["sources"]} == {"notes.txt", "trips/goa.md"}
    assert all(s["processing_status"] == "completed" for s in page["sources"])
    assert c.get(f"/api/libraries/{lib['id']}/sources", params={"q": "goa"}).json()["total"] == 1

    # Overlapping folders are refused with a readable message
    res = c.post("/api/libraries", json={"path": str(folder / "trips")})
    assert res.status_code == 400 and "inside the library" in res.json()["detail"]

    # Rename, exclusions (file stays on disk), detach keeping the files
    assert c.patch(f"/api/libraries/{lib['id']}", json={"name": "Family archive"}).json()["name"] == "Family archive"
    assert c.post(f"/api/libraries/{lib['id']}/exclusions", json={"pattern": "trips"}).json()["removed"] == 1
    assert (folder / "trips" / "goa.md").exists()
    assert c.get(f"/api/libraries/{lib['id']}/sources").json()["total"] == 1
    assert c.delete(f"/api/libraries/{lib['id']}", params={"deleteIndex": "true"}).json()["ok"]
    assert not (folder / ".smartfind").exists()
    assert (folder / "notes.txt").exists() and (folder / "trips" / "goa.md").exists()


def test_watcher_follows_changes(admin_client, folder):
    c = admin_client
    lib = c.post("/api/libraries", json={"path": str(folder)}).json()
    lib_id = lib["id"]
    _wait(lambda: _idle(c) and c.get(f"/api/libraries/{lib_id}/sources").json()["total"] == 2)

    def rels():
        return {s["relPath"]: s for s in c.get(f"/api/libraries/{lib_id}/sources").json()["sources"]}

    (folder / "new note.txt").write_text("Added while the app was running", encoding="utf-8")
    _wait(lambda: "new note.txt" in rels(), timeout=20)
    note_id = rels()["new note.txt"]["id"]

    (folder / "new note.txt").rename(folder / "renamed note.txt")
    _wait(lambda: "renamed note.txt" in rels() and "new note.txt" not in rels(), timeout=20)
    assert rels()["renamed note.txt"]["id"] == note_id      # same source: nothing re-indexed

    (folder / "renamed note.txt").unlink()
    _wait(lambda: "renamed note.txt" not in rels(), timeout=20)


def test_chunked_upload_resume_and_dedupe(admin_client, viewer, tmp_path):
    c = admin_client
    payload = os.urandom(3 * 1024 * 1024 + 123)
    mtime_ms = 1_600_000_000_000
    start = c.post("/api/uploads", json={"fileName": "../evil/Trip Notes.txt", "size": len(payload),
                                         "lastModified": mtime_ms})
    assert start.status_code == 200, start.text
    up = start.json()
    assert up["status"] == "started" and up["chunkSize"] >= 1024 * 1024
    upload_id = up["uploadId"]

    half = len(payload) // 2
    assert c.put(f"/api/uploads/{upload_id}", params={"offset": 0}, content=payload[:half]).json()["received"] == half
    # Skipping ahead is refused and tells the client where to resume
    bad = c.put(f"/api/uploads/{upload_id}", params={"offset": half + 10}, content=b"x")
    assert bad.status_code == 409 and bad.json()["received"] == half
    # Another user cannot touch this upload
    assert viewer.put(f"/api/uploads/{upload_id}", params={"offset": half}, content=b"x").status_code == 403
    # Resume after a "dropped connection"
    status = c.get(f"/api/uploads/{upload_id}").json()
    assert status["received"] == half
    assert c.put(f"/api/uploads/{upload_id}", params={"offset": half}, content=payload[half:]).json()["received"] == len(payload)
    # Too much data is refused
    assert c.put(f"/api/uploads/{upload_id}", params={"offset": len(payload)}, content=b"extra").status_code == 400

    done = c.post(f"/api/uploads/{upload_id}/complete").json()
    assert done["status"] == "queued", done
    assert done["fileName"] == "Trip Notes.txt" and "/" not in done["relPath"]   # traversal stripped

    from app.library.manager import get_library_manager
    uploads = get_library_manager().uploads()
    stored = uploads.root / done["relPath"]
    assert stored.read_bytes() == payload
    assert abs(stored.stat().st_mtime - mtime_ms / 1000) < 2          # original date kept
    assert not list(uploads.root.glob("*.smartfind-part"))

    # Same name, size and date: nothing is sent at all
    again = c.post("/api/uploads", json={"fileName": "Trip Notes.txt", "size": len(payload), "lastModified": mtime_ms})
    assert again.json()["status"] == "exists" and again.json()["sourceId"] == done["sourceId"]

    # Same content under another name: detected by fingerprint after the transfer, copy dropped
    other = c.post("/api/uploads", json={"fileName": "copy.txt", "size": len(payload)}).json()
    c.put(f"/api/uploads/{other['uploadId']}", params={"offset": 0}, content=payload)
    dup = c.post(f"/api/uploads/{other['uploadId']}/complete").json()
    assert dup["status"] == "exists" and dup["sourceId"] == done["sourceId"]
    assert not (uploads.root / "copy.txt").exists()

    _wait(lambda: _idle(c))
    assert uploads.db.scalar("SELECT status FROM sources WHERE id = ?", (done["sourceId"],)) == "indexed"


def test_upload_validation_and_abort(admin_client):
    c = admin_client
    assert c.post("/api/uploads", json={"fileName": "setup.exe", "size": 10}).status_code == 415
    up = c.post("/api/uploads", json={"fileName": "draft.txt", "size": 100}).json()
    c.put(f"/api/uploads/{up['uploadId']}", params={"offset": 0}, content=b"x" * 40)
    incomplete = c.post(f"/api/uploads/{up['uploadId']}/complete")
    assert incomplete.status_code == 409 and incomplete.json()["received"] == 40
    from app.library.manager import get_library_manager
    uploads = get_library_manager().uploads()
    assert len(list(uploads.root.glob("*.smartfind-part"))) == 1
    assert c.delete(f"/api/uploads/{up['uploadId']}").json()["ok"]
    assert not list(uploads.root.glob("*.smartfind-part"))
    assert c.get(f"/api/uploads/{up['uploadId']}").status_code == 404


def test_folder_upload_keeps_structure(admin_client):
    c = admin_client
    data = b"hello from a folder upload"
    up = c.post("/api/uploads", json={"fileName": "readme.txt", "size": len(data),
                                      "relativePath": "Project X/docs/readme.txt"}).json()
    c.put(f"/api/uploads/{up['uploadId']}", params={"offset": 0}, content=data)
    done = c.post(f"/api/uploads/{up['uploadId']}/complete").json()
    assert done["relPath"] == "Project X/docs/readme.txt"


def test_add_local_files_in_place(admin_client, folder, tmp_path):
    c = admin_client
    lib = c.post("/api/libraries", json={"path": str(folder)}).json()
    outside = tmp_path / "elsewhere" / "invoice.txt"
    outside.parent.mkdir()
    outside.write_text("Invoice 42", encoding="utf-8")
    res = c.post("/api/libraries/files", json={"paths": [
        str(outside), str(folder / "notes.txt"), str(tmp_path / "missing.txt"), str(folder),
    ]}).json()["results"]
    assert res[0]["status"] == "added" and res[0]["libraryId"] == "linked"
    assert res[1]["status"] == "added" and res[1]["libraryId"] == lib["id"]
    assert res[2]["status"] == "error" and res[3]["status"] == "error"
    _wait(lambda: _idle(c))
    from app.library.manager import get_library_manager
    linked = get_library_manager().linked()
    row = linked.db.one("SELECT * FROM sources WHERE id = ?", (res[0]["sourceId"],))
    assert row["status"] == "indexed" and Path(row["rel_path"]) == outside.resolve()
    assert not any(p.name == "invoice.txt" for p in get_library_manager().uploads().root.rglob("*"))  # never copied


def test_folder_browser(admin_client, folder):
    c = admin_client
    roots = c.get("/api/system/fs").json()
    assert roots["path"] is None and roots["entries"]
    listing = c.get("/api/system/fs", params={"path": str(folder), "files": "true"}).json()
    names = [e["name"] for e in listing["entries"]]
    assert names == ["trips", "notes.txt"]          # folders first; .smartfind never shown
    assert listing["parent"] == str(folder.resolve().parent)
    assert c.get("/api/system/fs", params={"path": str(folder / "nope")}).status_code == 404
