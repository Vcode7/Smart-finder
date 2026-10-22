"""
Admin-managed accounts and per-library sharing: admins create users/admins and share
libraries; users can only query what was shared with them and cannot upload.
"""
import time

import pytest

from tests.conftest import TEST_ADMIN_EMAIL

USER_PASSWORD = "Another-User-Pw-1"


def _new_client(client):
    from fastapi.testclient import TestClient
    return TestClient(client.app)   # same running app, own cookie jar


def _login(client, email, password=USER_PASSWORD):
    other = _new_client(client)
    res = other.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return other


def _create_user(admin, email="alice@smartfind-tests.dev", role="user"):
    res = admin.post("/api/users", json={"email": email, "username": email.split("@")[0],
                                         "password": USER_PASSWORD, "role": role})
    assert res.status_code == 201, res.text
    return res.json()["user"]


def _attach(admin, root, name):
    lib = admin.post("/api/libraries", json={"path": str(root), "name": name}).json()
    deadline = time.time() + 60
    while time.time() < deadline:
        s = admin.get("/api/libraries/status").json()
        info = admin.get(f"/api/libraries/{lib['id']}").json()
        if s["queued"] == 0 and s["processing"] == 0 and not s["enrichmentPending"] and not s["current"] \
                and info.get("counts", {}).get("indexed") == 1:
            return lib
        time.sleep(0.2)
    raise AssertionError("library was not indexed in time")


@pytest.fixture
def two_libraries(admin_client, tmp_path):
    shared = tmp_path / "Shared"
    private = tmp_path / "Private"
    shared.mkdir()
    private.mkdir()
    (shared / "minutes.txt").write_text("Quarterly minutes: the drainage contract was signed.", encoding="utf-8")
    (private / "salary.txt").write_text("Confidential salary revision for the drainage engineers.", encoding="utf-8")
    return _attach(admin_client, shared, "Shared"), _attach(admin_client, private, "Private")


# ── account management ───────────────────────────────────────────────────────
def test_admin_creates_users_and_admins(admin_client):
    alice = _create_user(admin_client)
    assert alice["role"] == "user" and alice["libraryIds"] == []
    boss = _create_user(admin_client, "boss@smartfind-tests.dev", role="admin")
    assert boss["role"] == "admin"

    dup = admin_client.post("/api/users", json={"email": "ALICE@smartfind-tests.dev", "username": "x",
                                                "password": USER_PASSWORD})
    assert dup.status_code == 409

    emails = {u["email"] for u in admin_client.get("/api/users").json()["users"]}
    assert {"alice@smartfind-tests.dev", "boss@smartfind-tests.dev", TEST_ADMIN_EMAIL} <= emails
    assert not any(u["id"] == "system" for u in admin_client.get("/api/users").json()["users"])

    # The new admin can sign in and manage users; the plain user cannot
    assert _login(admin_client, "boss@smartfind-tests.dev").get("/api/users").status_code == 200
    assert _login(admin_client, "alice@smartfind-tests.dev").get("/api/users").status_code == 403


def test_user_management_requires_admin(client, admin_client):
    _create_user(admin_client)
    anon = _new_client(client)
    assert anon.get("/api/users").status_code == 401
    alice = _login(client, "alice@smartfind-tests.dev")
    assert alice.post("/api/users", json={"email": "m@smartfind-tests.dev", "username": "m",
                                          "password": USER_PASSWORD, "role": "admin"}).status_code == 403
    assert alice.put("/api/users/x/libraries", json={"libraryIds": []}).status_code == 403


def test_last_admin_and_self_guards(admin_client):
    me = next(u for u in admin_client.get("/api/users").json()["users"] if u["email"] == TEST_ADMIN_EMAIL)
    assert admin_client.delete(f"/api/users/{me['id']}").status_code == 400
    assert admin_client.patch(f"/api/users/{me['id']}", json={"role": "user"}).status_code == 400
    assert admin_client.delete("/api/users/system").status_code == 404

    alice = _create_user(admin_client)
    res = admin_client.patch(f"/api/users/{alice['id']}", json={"password": "Brand-New-Pw-2"})
    assert res.status_code == 200
    assert admin_client.delete(f"/api/users/{alice['id']}").status_code == 200
    assert all(u["id"] != alice["id"] for u in admin_client.get("/api/users").json()["users"])


def test_admin_signup_needs_the_setup_code(client, monkeypatch):
    from app.core import config as cfg
    body = {"email": "root@smartfind-tests.dev", "username": "root", "password": USER_PASSWORD, "setupCode": "s3cret"}
    anon = _new_client(client)

    assert anon.get("/api/auth/config").json()["allowAdminSignup"] is False
    assert anon.post("/api/auth/signup-admin", json=body).status_code == 403

    monkeypatch.setattr(cfg.settings, "ADMIN_SETUP_CODE", "s3cret", raising=False)
    assert anon.get("/api/auth/config").json()["allowAdminSignup"] is True
    assert anon.post("/api/auth/signup-admin", json={**body, "setupCode": "nope"}).status_code == 403

    res = anon.post("/api/auth/signup-admin", json=body)
    assert res.status_code == 201 and res.json()["user"]["role"] == "admin"
    assert anon.get("/api/users").status_code == 200          # signed in as the new admin
    assert anon.post("/api/auth/signup-admin", json=body).status_code == 409


def test_admin_signup_placeholder_code_is_disabled(client, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "ADMIN_SETUP_CODE", "choose-a-setup-code", raising=False)
    assert _new_client(client).get("/api/auth/config").json()["allowAdminSignup"] is False


def test_admin_signup_code_guesses_are_rate_limited(client, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "ADMIN_SETUP_CODE", "s3cret", raising=False)
    anon = _new_client(client)
    body = {"email": "guesser@smartfind-tests.dev", "username": "g", "password": USER_PASSWORD, "setupCode": "bad"}
    for _ in range(cfg.settings.LOGIN_MAX_FAILURES):
        assert anon.post("/api/auth/signup-admin", json=body).status_code == 403
    assert anon.post("/api/auth/signup-admin", json={**body, "setupCode": "s3cret"}).status_code == 429


# ── users can query only; admins upload ──────────────────────────────────────
def test_users_cannot_upload_or_import(client, admin_client):
    _create_user(admin_client)
    alice = _login(client, "alice@smartfind-tests.dev")
    assert alice.post("/api/uploads", json={"fileName": "a.txt", "size": 1}).status_code == 403
    assert alice.put("/api/uploads/x", params={"offset": 0}, content=b"x").status_code == 403
    assert alice.post("/api/knowledge/upload",
                      files={"files": ("a.txt", b"hello", "text/plain")}).status_code == 403
    assert alice.post("/api/knowledge/check-conflicts", json={"filenames": ["a.txt"]}).status_code == 403
    assert alice.post("/api/knowledge/import-internet", json={"sources": []}).status_code == 403
    assert alice.post("/api/knowledge/scrape-search", json={"query": "x"}).status_code == 403
    assert admin_client.post("/api/uploads", json={"fileName": "a.txt", "size": 1}).status_code == 200


# ── sharing ──────────────────────────────────────────────────────────────────
def _titles(c, query):
    res = c.post("/api/search/local", json={"query": query})
    assert res.status_code == 200, res.text
    return {d["title"] for d in res.json()["documents"]}


def test_user_sees_only_shared_libraries(client, admin_client, two_libraries):
    shared, private = two_libraries
    alice_row = _create_user(admin_client)
    alice = _login(client, "alice@smartfind-tests.dev")
    sources = {r["original_name"]: r["id"] for r in admin_client.get("/api/knowledge").json()["sources"]}
    secret_id, minutes_id = sources["salary.txt"], sources["minutes.txt"]

    # Nothing shared yet: nothing visible anywhere
    assert alice.get("/api/libraries").json()["libraries"] == []
    assert alice.get("/api/knowledge").json()["sources"] == []
    assert _titles(alice, "drainage") == set()
    assert alice.get(f"/api/knowledge/{minutes_id}").status_code == 404
    assert alice.get(f"/api/knowledge/{minutes_id}/file").status_code == 404
    assert alice.get(f"/api/libraries/{shared['id']}").status_code == 404
    assert alice.get(f"/api/libraries/{shared['id']}/sources").status_code == 404

    # Share one library
    res = admin_client.put(f"/api/users/{alice_row['id']}/libraries", json={"libraryIds": [shared["id"]]})
    assert res.status_code == 200 and res.json()["libraryIds"] == [shared["id"]]

    libs = alice.get("/api/libraries").json()["libraries"]
    assert [lib["name"] for lib in libs] == ["Shared"]
    assert "path" not in libs[0] and "indexPath" not in libs[0]          # server paths stay admin-only
    assert {r["original_name"] for r in alice.get("/api/knowledge").json()["sources"]} == {"minutes.txt"}
    assert _titles(alice, "drainage") == {"minutes.txt"}
    assert alice.get(f"/api/knowledge/{minutes_id}/file").status_code == 200
    assert alice.get(f"/api/libraries/{shared['id']}/sources").json()["total"] == 1

    # ...but not the other one, however it is asked for
    assert alice.get(f"/api/knowledge/{secret_id}").status_code == 404
    assert alice.get(f"/api/knowledge/{secret_id}/file").status_code == 404
    assert alice.get(f"/api/libraries/{private['id']}/sources").status_code == 404
    assert _titles(alice, 'drainage in:"Private"') == set()               # in: cannot widen access
    assert alice.post("/api/search/similar", json={"sourceId": secret_id}).status_code == 404

    # Users cannot delete or reprocess even shared data
    assert alice.delete(f"/api/knowledge/{minutes_id}").status_code == 403
    assert alice.post(f"/api/knowledge/{minutes_id}/reprocess").status_code == 403

    # Admins still see everything
    assert _titles(admin_client, "drainage") == {"minutes.txt", "salary.txt"}

    # Revoking takes access away again
    admin_client.put(f"/api/users/{alice_row['id']}/libraries", json={"libraryIds": []})
    assert alice.get("/api/libraries").json()["libraries"] == []
    assert _titles(alice, "drainage") == set()


def test_sharing_validates_libraries_and_roles(admin_client, two_libraries):
    shared, _private = two_libraries
    alice = _create_user(admin_client)
    boss = _create_user(admin_client, "boss@smartfind-tests.dev", role="admin")
    assert admin_client.put(f"/api/users/{alice['id']}/libraries",
                            json={"libraryIds": ["no-such-library"]}).status_code == 400
    assert admin_client.put(f"/api/users/{boss['id']}/libraries",
                            json={"libraryIds": [shared["id"]]}).status_code == 400
    assert admin_client.put("/api/users/nobody/libraries", json={"libraryIds": []}).status_code == 404


def test_deleting_a_user_drops_their_grants(admin_client, two_libraries):
    shared, _private = two_libraries
    alice = _create_user(admin_client)
    admin_client.put(f"/api/users/{alice['id']}/libraries", json={"libraryIds": [shared["id"]]})
    assert admin_client.delete(f"/api/users/{alice['id']}").status_code == 200
    from app.database.session import db_get
    assert db_get("SELECT 1 AS x FROM library_access WHERE user_id = ?", (alice["id"],)) is None
