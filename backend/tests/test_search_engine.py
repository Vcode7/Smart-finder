"""
Search engine over folder libraries (fake models): retrievers, fusion, filters, faces,
'find similar', and the /api/search + /api/knowledge routes serving library sources.
"""
import time
from pathlib import Path

import pytest

from tests.test_ingest_pipeline import _make_pdf, _make_photo, _make_video, _make_wav


@pytest.fixture
def fake_models(mock_models_available, monkeypatch):
    import app.search.model_pipeline as mp
    from tests.conftest import _unit_vector

    def faces(img, min_confidence=0.5, model_name="buffalo_s"):
        if min(img.size) < 500:
            return []
        return [{"box": [0.2, 0.3, 0.5, 0.6], "confidence": 0.93, "embedding": _unit_vector(77, 512), "size_px": 180}]

    segments = [
        {"start": 0.0, "end": 4.0, "text": "Welcome to the solar plant tour."},
        {"start": 30.0, "end": 36.0, "text": "These turbines produce four megawatts of wind power."},
    ]
    monkeypatch.setattr(mp, "detect_and_embed_faces", faces)
    monkeypatch.setattr(mp, "transcribe_media", lambda path, should_stop=None: {
        "segments": list(segments), "language": "en", "language_probability": 0.99, "duration": 40.0})
    return mp


@pytest.fixture
def indexed(manager, tmp_path, fake_models):
    root = tmp_path / "Archive"
    (root / "docs").mkdir(parents=True)
    (root / "notes.txt").write_text(
        "The monsoon planning meeting moved to Friday.\n\nBring the rainfall charts.", encoding="utf-8")
    (root / "recipes.txt").write_text("Mango pickle needs mustard oil and fenugreek.", encoding="utf-8")
    _make_pdf(root / "docs" / "report.pdf")
    _make_photo(root / "holiday beach.jpg")
    _make_video(root / "plant tour.mp4")
    _make_wav(root / "voice memo.wav")
    lib = manager.attach(str(root))
    from app.library.scanner import scan_library
    from tests.test_ingest_pipeline import _process_all
    scan_library(lib)
    _process_all(manager)
    assert lib.db.scalar("SELECT COUNT(*) FROM sources WHERE status != 'indexed'") == 0
    return lib


def _search(text="", files=None, limit=20):
    from app.search.engine import SearchEngine
    from app.search.plan import build_plan
    plan = build_plan(text, files or [])
    return SearchEngine().search(plan, limit)


def _names(items):
    return [i["title"] for i in items]


def test_keyword_search_finds_the_right_document(indexed):
    res = _search("monsoon planning")
    assert _names(res.documents)[0] == "notes.txt"
    top = res.documents[0]
    assert "monsoon" in top["snippet"].lower()
    assert top["relevanceScore"] > 0.5 and top["rerankScore"] is not None
    assert top["libraryName"] == "Archive" and top["relPath"] == "notes.txt"
    assert top["id"] == f"src-{top['sourceId']}"
    # The unrelated recipe is not ranked above it
    assert "recipes.txt" not in _names(res.documents)[:1]


def test_spoken_words_find_the_moment_in_a_video(indexed):
    res = _search("turbines wind power")
    video = next(i for i in res.videos if i["title"] == "plant tour.mp4")
    assert video["startTime"] == 30.0          # the transcript window where it is said
    assert "turbines" in video["snippet"].lower()


def test_filename_and_folder_are_searchable(indexed):
    res = _search("holiday")
    assert "holiday beach.jpg" in _names(res.images)


def test_filters_in_the_query(indexed):
    res = _search("solar kind:video")
    assert res.documents == [] and res.images == [] and res.audio == []
    assert _names(res.videos) == ["plant tour.mp4"]
    res = _search("revenue type:pdf")
    assert _names(res.documents) == ["report.pdf"]
    res = _search("revenue folder:docs")
    assert _names(res.documents) == ["report.pdf"]
    assert _search("monsoon folder:docs").documents == []


def test_face_query_finds_the_person(indexed):
    import io
    from tests.test_ingest_pipeline import _noise_image
    buf = io.BytesIO()
    _noise_image(800, 800, 9).save(buf, "JPEG")
    res = _search("", files=[(buf.getvalue(), "person.jpg", "image/jpeg")])
    photo = next(i for i in res.images if i["title"] == "holiday beach.jpg")
    assert photo["isFaceMatch"] and photo["faceSimilarity"] > 0.99
    assert photo["relevanceScore"] >= 0.9

    # Person + words: only media with that person, ranked by the words
    res = _search("revenue", files=[(buf.getvalue(), "person.jpg", "image/jpeg")])
    titles = _names(res.all())
    assert "notes.txt" not in titles                      # no face → filtered out
    assert set(titles) <= {"holiday beach.jpg", "report.pdf"}


def test_find_similar_uses_stored_signals(indexed):
    from app.search.engine import SearchEngine, plan_from_source
    photo_id = indexed.db.scalar("SELECT id FROM sources WHERE name = 'holiday beach.jpg'")
    plan = plan_from_source(indexed, photo_id)
    assert plan.images and plan.images[0].faces and photo_id in plan.exclude_sources
    res = SearchEngine().search(plan, 20)
    titles = _names(res.all())
    assert "holiday beach.jpg" not in titles             # never itself
    assert "report.pdf" in titles                         # shares the face (scanned page)


def test_nonsense_query_returns_nothing_relevant(indexed):
    res = _search("xylophone quasar zeppelin")
    assert all(i["relevanceScore"] < 0.5 for i in res.all())


def test_multiple_libraries_are_searched_together(indexed, manager, tmp_path):
    other = tmp_path / "Second"
    other.mkdir()
    (other / "monsoon budget.txt").write_text("Monsoon budget approved for the drainage project.", encoding="utf-8")
    lib2 = manager.attach(str(other))
    from app.library.scanner import scan_library
    from tests.test_ingest_pipeline import _process_all
    scan_library(lib2)
    _process_all(manager)
    res = _search("monsoon")
    libs = {i["libraryName"] for i in res.documents}
    assert libs == {"Archive", "Second"}
    # Library filter by name
    res = _search('monsoon in:"Second"')
    assert {i["libraryName"] for i in res.documents} == {"Second"}


# ── API: search and knowledge routes over libraries ──────────────────────────
@pytest.fixture
def api_library(admin_client, tmp_path):
    root = tmp_path / "Shared"
    root.mkdir()
    (root / "minutes.txt").write_text("Quarterly minutes: the drainage contract was signed.", encoding="utf-8")
    _make_photo(root / "team photo.jpg")
    c = admin_client
    lib = c.post("/api/libraries", json={"path": str(root)}).json()
    deadline = time.time() + 60
    while time.time() < deadline:
        s = c.get("/api/libraries/status").json()
        info = c.get(f"/api/libraries/{lib['id']}").json()
        if s["queued"] == 0 and s["processing"] == 0 and not s["enrichmentPending"] and not s["current"] and info.get("counts", {}).get("indexed") == 2:
            break
        time.sleep(0.2)
    return lib, root


def test_smart_search_api_shape(api_library, admin_client):
    c = admin_client
    res = c.post("/api/search/smart", json={"query": "drainage contract"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body["local"]) >= {"documents", "videos", "images", "audio", "total"}
    doc = body["local"]["documents"][0]
    assert doc["title"] == "minutes.txt" and doc["libraryName"] == "Shared"
    assert body["discoveryTrace"]["engine"]["libraries"]
    local = c.post("/api/search/local", json={"query": "drainage"}).json()
    assert local["documents"][0]["title"] == "minutes.txt"


def test_knowledge_routes_serve_library_sources(api_library, admin_client):
    lib, root = api_library
    c = admin_client
    listing = c.get("/api/knowledge").json()
    rows = {r["original_name"]: r for r in listing["sources"]}
    assert {"minutes.txt", "team photo.jpg"} <= set(rows)
    assert rows["minutes.txt"]["processing_status"] == "completed" and rows["minutes.txt"]["libraryName"] == "Shared"

    sid = rows["minutes.txt"]["id"]
    detail = c.get(f"/api/knowledge/{sid}").json()
    assert detail["source"]["original_name"] == "minutes.txt" and detail["chunks"]
    assert c.get(f"/api/knowledge/{sid}/file").content == (root / "minutes.txt").read_bytes()

    photo = rows["team photo.jpg"]["id"]
    assert c.get(f"/api/knowledge/{photo}/thumbnail").status_code == 200
    pdetail = c.get(f"/api/knowledge/{photo}").json()
    assert pdetail["image"]["width"] == 600

    # Removing a folder file only takes it out of the index; the file stays
    res = c.delete(f"/api/knowledge/{sid}").json()
    assert res["success"] and res["fileDeleted"] is False
    assert (root / "minutes.txt").exists()
    assert c.get(f"/api/knowledge/{sid}").status_code == 404


def test_legacy_multipart_upload_goes_to_the_uploads_library(admin_client):
    c = admin_client
    files = {"files": ("field notes.txt", b"Soil samples from the eastern ridge.", "text/plain")}
    res = c.post("/api/knowledge/upload", files=files).json()
    assert res["success"], res
    sid = res["source"]["id"]
    from app.library.manager import get_library_manager
    uploads = get_library_manager().uploads()
    stored = uploads.root / "field notes.txt"
    assert stored.read_bytes() == b"Soil samples from the eastern ridge."
    # Uploaded copies are app-managed: deleting removes the copy
    deadline = time.time() + 30
    while time.time() < deadline and uploads.db.scalar("SELECT status FROM sources WHERE id = ?", (sid,)) != "indexed":
        time.sleep(0.2)
    res = c.delete(f"/api/knowledge/{sid}").json()
    assert res["fileDeleted"] is True and not stored.exists()


def test_internet_import_becomes_a_markdown_file(admin_client):
    c = admin_client
    res = c.post("/api/knowledge/import-internet", json={"sources": [{
        "title": "Monsoon outlook 2026", "url": "https://example.org/monsoon", "category": "article",
        "snippet": "Above-normal rainfall is expected across the western coast.",
    }]}).json()
    assert res["success"] and res["count"] == 1
    from app.library.manager import get_library_manager
    uploads = get_library_manager().uploads()
    md = uploads.root / "Internet" / "Monsoon outlook 2026.md"
    text = md.read_text(encoding="utf-8")
    assert "https://example.org/monsoon" in text and "western coast" in text
    sid = res["imported"][0]["id"]
    # Opening an internet item goes to the original page
    r = c.get(f"/api/knowledge/{sid}/file", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "https://example.org/monsoon"


def test_photo_bursts_collapse_into_one_result(manager, tmp_path, fake_models):
    from tests.test_ingest_pipeline import _noise_image, _process_all
    root = tmp_path / "Burst"
    root.mkdir()
    base = _noise_image(800, 600, 42)
    base.save(root / "sunset 1.jpg", "JPEG", quality=95)
    base.save(root / "sunset 2.jpg", "JPEG", quality=70)      # same shot, different encoding
    _noise_image(800, 600, 43).save(root / "sunset 3.jpg", "JPEG", quality=95)   # a different picture
    lib = manager.attach(str(root))
    from app.library.scanner import scan_library
    scan_library(lib)
    _process_all(manager)
    images = _search("sunset").images
    titles = [i["title"] for i in images]
    assert len(images) == 2 and "sunset 3.jpg" in titles
    burst = next(i for i in images if i["title"] != "sunset 3.jpg")
    assert len(burst.get("similarPhotos") or []) == 1


def test_picture_reranker_leads_with_the_picture_it_is_sure_about(indexed, monkeypatch):
    import app.search.model_pipeline as mp
    judged = []

    def judge(query, images, instruction=None):
        judged.append((query, len(images)))
        return [0.95 if min(im.size) >= 500 else 0.05 for im in images]   # only the holiday photo is large

    monkeypatch.setattr(mp, "visual_rerank_enabled", lambda: True)
    monkeypatch.setattr(mp, "rerank_images", judge)
    res = _search("sunny beach")
    assert [q for q, _ in judged] == ["sunny beach"] and judged[0][1] >= 2
    photo = next(i for i in res.images if i["title"] == "holiday beach.jpg")
    assert photo["relevanceScore"] >= 0.665 and photo["evidence"] == "clip_text"
    assert res.all()[0]["title"] == "holiday beach.jpg"


def test_picture_and_words_are_one_query(indexed, monkeypatch):
    import io
    import app.search.model_pipeline as mp
    from app.search.plan import build_plan
    from tests.conftest import _unit_vector
    from tests.test_ingest_pipeline import _noise_image
    asked = []

    def compose(image, text):
        asked.append((image.size, text))
        return _unit_vector(5, 1024)

    monkeypatch.setattr(mp, "get_composed_query_embedding", compose)
    buf = io.BytesIO()
    _noise_image(1200, 900, 4).save(buf, "PNG")
    plan = build_plan("at night", [(buf.getvalue(), "q.png", "image/png")])
    assert asked == [((768, 576), "at night")]               # a thumbnail, with the typed words
    assert plan.images[0].compose_vec == _unit_vector(5, 1024)
    assert plan.images[0].image is None                      # not kept once the plan is built


# ── folders ──────────────────────────────────────────────────────────────────
@pytest.fixture
def events(manager, tmp_path, fake_models):
    """Events/<event>/<day>/… — folder names say what the files are from."""
    root = tmp_path / "Family"
    day1 = root / "Events" / "Diwali 2023" / "Day 1"
    day2 = root / "Events" / "Diwali 2023" / "Day 2"
    for d in (day1, day2, root / "Events" / "Holi", root / "Work"):
        d.mkdir(parents=True)
    for i in range(60):      # more than the 50 files the name retriever returns
        (day1 / f"note {i}.txt").write_text(f"Guests arrived at {i} minutes past seven.", encoding="utf-8")
    (day2 / "courtyard.txt").write_text("Everyone was dancing in the courtyard until late.", encoding="utf-8")
    (root / "Events" / "Holi" / "colours.txt").write_text("Colour powder everywhere on the terrace.", encoding="utf-8")
    (root / "Work" / "party.txt").write_text("People were dancing at the office party.", encoding="utf-8")
    for i in range(30):      # so the Diwali folder isn't nearly the whole library
        (root / "Work" / f"memo {i}.txt").write_text(f"Quarterly memo number {i} about budgets.", encoding="utf-8")
    lib = manager.attach(str(root))
    from app.library.scanner import scan_library
    from tests.test_ingest_pipeline import _process_all
    scan_library(lib)
    _process_all(manager)
    assert lib.db.scalar("SELECT COUNT(*) FROM sources WHERE status != 'indexed'") == 0
    return lib


def test_folder_column_follows_the_path(events):
    from app.library.sources import move_sources
    rows = dict([(r["name"], r["folder"]) for r in events.db.all(
                    "SELECT name, folder FROM sources WHERE name IN ('courtyard.txt', 'party.txt')")])
    assert rows == {"courtyard.txt": "Events/Diwali 2023/Day 2", "party.txt": "Work"}
    move_sources(events, "Work", "Office")
    assert events.db.scalar("SELECT folder FROM sources WHERE name = 'party.txt'") == "Office"


def test_a_named_folder_brings_all_its_files(events):
    res = _search("diwali", limit=100)
    titles = _names(res.documents)
    assert len(titles) == 61 and "courtyard.txt" in titles           # every file, no 50 cap
    assert all(d["folderMatch"] == "Events/Diwali 2023" for d in res.documents)
    assert [f["path"] for f in res.trace["folders"]] == ["Events/Diwali 2023"]
    assert res.trace["folderQuery"] == ""
    assert "colours.txt" not in titles and "party.txt" not in titles


def test_other_words_rank_inside_the_folder(events):
    res = _search("dancing diwali", limit=100)
    titles = _names(res.documents)
    assert res.trace["folderQuery"] == "dancing"
    assert titles[0] == "courtyard.txt"                               # inside the folder and dancing
    assert "party.txt" in titles                                      # dancing elsewhere: still found
    party = titles.index("party.txt")
    assert all(t.startswith("note ") for t in titles[party + 1:])     # then the rest of the folder
    assert res.documents[party]["folderMatch"] is None
    assert res.documents[0]["relevanceScore"] > res.documents[party]["relevanceScore"]


def test_the_deepest_folder_the_words_name(events):
    res = _search("diwali day 2")
    assert [f["path"] for f in res.trace["folders"]] == ["Events/Diwali 2023/Day 2"]
    assert _names(res.documents)[0] == "courtyard.txt"
    # Typed as a path
    res = _search("dancing in diwali 2023/day 2")
    assert [f["path"] for f in res.trace["folders"]] == ["Events/Diwali 2023/Day 2"]
    assert res.trace["folderQuery"] == "dancing in"


def test_folder_filter_takes_a_folder_name(events):
    res = _search('dancing folder:"Day 2"')
    assert _names(res.documents) == ["courtyard.txt"]
    assert _names(_search("colour folder:holi").documents) == ["colours.txt"]
    # Filters alone list the folder ("Search only here" when every word named the folder)
    res = _search('folder:"Events/Diwali 2023" in:"Family"', limit=100)
    assert len(res.documents) == 61 and _names(res.documents)[0] == "note 0.txt"
    assert res.documents[0]["snippet"] == "In folder Events/Diwali 2023/Day 1"


def test_renamed_folders_match_by_their_new_name(events):
    from app.library.sources import move_sources
    move_sources(events, "Events/Holi", "Events/Rangpanchami")
    res = _search("rangpanchami")
    assert _names(res.documents) == ["colours.txt"]
    assert res.documents[0]["folderMatch"] == "Events/Rangpanchami"
    assert not _search("holi").trace.get("folders")


def test_kind_words_and_folders_above_everything_are_no_scope(events):
    from app.library.sources import move_sources
    from app.search.folders import match_folders
    assert [m.path for m in match_folders(events, "events")] == ["Events"]   # 62 of 93 files: still narrows
    assert [m.path for m in match_folders(events, "work documents")] == ["Work"]
    assert match_folders(events, "documents") == []                   # a kind of file, not a folder
    move_sources(events, "Events", "Family/Events")
    move_sources(events, "Work", "Family/Work")
    assert match_folders(events, "family") == []                      # above every file


def test_folder_word_forms(events):
    from app.search.folders import words, word_matches
    assert words("Diwali2023") == ["diwali", "2023"] and words("RahulWedding_Haldi") == ["rahul", "wedding", "haldi"]
    assert word_matches("wedding", "weddings") and not word_matches("day", "days")
    assert not word_matches("2", "2023")
