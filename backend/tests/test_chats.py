"""
Chat API regression tests (isolated temp database, fake LLM client).
"""
import datetime
import uuid
from types import SimpleNamespace

from app.database.session import db_run


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Fake answer"))])


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_latest_messages_reach_the_llm(admin_client, monkeypatch):
    """Regression: history was read oldest-first with LIMIT 10, so new messages never reached the LLM."""
    fake = _FakeClient()
    import app.ai.groq_client as groq_client
    monkeypatch.setattr(groq_client, "get_async_groq_client", lambda: fake)

    chat_id = admin_client.post("/api/chats", json={"title": "History"}).json()["chat"]["id"]
    base = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    for i in range(12):
        db_run(
            "INSERT INTO chat_messages (id, chat_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), chat_id, "user" if i % 2 == 0 else "assistant", f"message {i}",
             (base + datetime.timedelta(minutes=i)).isoformat())
        )

    res = admin_client.post(f"/api/chats/{chat_id}/messages", json={"message": "newest question"})
    assert res.status_code == 200, res.text
    assert res.json()["assistantMessage"]["content"] == "Fake answer"

    sent = fake.chat.completions.calls[0]["messages"]
    contents = [m["content"] for m in sent[1:]]
    assert contents[-1] == "newest question"
    assert "message 0" not in contents


def test_audio_context_type_is_kept(admin_client):
    chat_id = admin_client.post("/api/chats", json={"title": "Audio"}).json()["chat"]["id"]
    res = admin_client.put(f"/api/chats/{chat_id}/context", json={"contextItems": [
        {"type": "audio", "refId": "src-abc", "title": "Podcast", "snippet": "We discussed budgets"},
    ]})
    assert res.status_code == 200
    items = admin_client.get(f"/api/chats/{chat_id}").json()["contextItems"]
    assert items[0]["type"] == "audio"


def test_chat_list_has_camelcase_fields(admin_client):
    admin_client.post("/api/chats", json={"title": "Fields", "searchMode": "local"})
    chat = admin_client.get("/api/chats").json()["chats"][0]
    assert chat["searchMode"] == "local"
    assert chat["updatedAt"] == chat["updated_at"]


def test_context_items_with_null_fields_are_accepted(admin_client, monkeypatch):
    """Regression: relevanceScore null or a non-object metadata raised a 500."""
    import app.ai.groq_client as groq_client
    monkeypatch.setattr(groq_client, "get_async_groq_client", lambda: _FakeClient())
    chat_id = admin_client.post("/api/chats", json={"title": "Nulls"}).json()["chat"]["id"]
    odd = [{"id": "web-1", "type": "web", "title": "Page", "relevanceScore": None, "metadata": "x", "snippet": None}]

    assert admin_client.put(f"/api/chats/{chat_id}/context", json={"contextItems": odd}).status_code == 200
    res = admin_client.post(f"/api/chats/{chat_id}/messages", json={"message": "hi", "contextItems": odd})
    assert res.status_code == 200, res.text
    item = admin_client.get(f"/api/chats/{chat_id}").json()["contextItems"][0]
    assert item["relevanceScore"] == 0.8
    assert item["title"] == "Page"


def test_first_message_names_the_chat(admin_client, monkeypatch):
    import app.ai.groq_client as groq_client
    monkeypatch.setattr(groq_client, "get_async_groq_client", lambda: _FakeClient())
    chat_id = admin_client.post("/api/chats", json={"title": "New Chat"}).json()["chat"]["id"]

    res = admin_client.post(f"/api/chats/{chat_id}/messages", json={"message": "budget of the 2024 exam reforms"})
    assert res.json()["chat"]["title"] == "budget of the 2024 exam reforms"
    assert admin_client.patch(f"/api/chats/{chat_id}", json={"title": "   "}).status_code == 400


def test_the_ai_is_told_which_folder_a_file_is_in(admin_client, monkeypatch, tmp_path):
    import time
    import app.ai.groq_client as groq_client
    fake = _FakeClient()
    monkeypatch.setattr(groq_client, "get_async_groq_client", lambda: fake)
    root = tmp_path / "Family"
    (root / "Trips" / "Goa 2023").mkdir(parents=True)
    (root / "Trips" / "Goa 2023" / "day one.txt").write_text("We walked along the beach at sunset.", encoding="utf-8")
    lib = admin_client.post("/api/libraries", json={"path": str(root)}).json()
    deadline = time.time() + 60
    while time.time() < deadline and admin_client.get(f"/api/libraries/{lib['id']}").json().get("counts", {}).get("indexed") != 1:
        time.sleep(0.2)
    from app.library.manager import get_library_manager
    sid = get_library_manager().get(lib["id"]).db.scalar("SELECT id FROM sources")

    chat_id = admin_client.post("/api/chats", json={"title": "Trip"}).json()["chat"]["id"]
    items = [
        {"type": "document", "refId": f"src-{sid}", "title": "day one.txt", "snippet": "beach at sunset",
         "metadata": {"sourceId": sid}},
        # Not in any library any more: the folder sent with the item is used
        {"type": "image", "refId": "src-gone", "title": "IMG_2041.jpg", "snippet": "people dancing",
         "metadata": {"sourceId": "gone", "relPath": "Events/Rahul Wedding/Haldi/IMG_2041.jpg", "libraryName": "Photos"}},
    ]
    res = admin_client.post(f"/api/chats/{chat_id}/messages", json={"message": "where was this?", "contextItems": items})
    assert res.status_code == 200, res.text
    system = fake.chat.completions.calls[0]["messages"][0]["content"]
    assert "[DOCUMENT] day one.txt — folder: Family › Trips/Goa 2023:" in system
    assert "[IMAGE] IMG_2041.jpg — folder: Photos › Events/Rahul Wedding/Haldi:" in system
    assert "Folder names often name the event" in system
