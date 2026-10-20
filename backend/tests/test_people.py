"""
People: grouping faces across libraries, stable names, corrections, the People API,
and searching by a person's name. Also sound search (CLAP) through the engine.
"""
import time

import numpy as np
import pytest


def _vec(base: int, noise_seed: int, noise: float = 0.15) -> list:
    rng = np.random.default_rng(base)
    v = rng.standard_normal(512)
    v /= np.linalg.norm(v)
    n = np.random.default_rng(1000 + noise_seed).standard_normal(512)
    n /= np.linalg.norm(n)
    out = v + noise * n
    return (out / np.linalg.norm(out)).tolist()


def _add_faces(lib, source_name: str, faces: list) -> str:
    """Insert a source with faces (vector or None) directly into a library index."""
    import json
    from app.library.sources import add_or_update_source
    from app.library.vector_store import VectorStore
    root = lib.root
    (root / source_name).write_bytes(b"\xff\xd8placeholder")
    sid = add_or_update_source(lib, source_name, size=10, mtime=1)
    rows = []
    with lib.db.write() as c:
        c.execute("UPDATE sources SET status = 'indexed', meta_json = ? WHERE id = ?", (json.dumps({}), sid))
        vid = c.execute("INSERT INTO visual_items (source_id, kind) VALUES (?, 'photo')", (sid,)).lastrowid
        for i, (vec, track) in enumerate(faces):
            fid = c.execute(
                "INSERT INTO faces (source_id, visual_item_id, ts, bbox, det_score, quality, crop_path, track_id) "
                "VALUES (?, ?, ?, '[0,0,1,1]', 0.9, ?, ?, ?)",
                (sid, vid, float(i), 0.9 - i * 0.01, f"faces/{vid}_{i}.webp", track)).lastrowid
            if vec is not None:
                rows.append((fid, sid, vec))
        ids = VectorStore.insert_rows(c, "face", rows)
    lib.vectors.index_rows("face", ids, [r[2] for r in rows])
    return sid


@pytest.fixture
def people_lib(manager, tmp_path):
    root = tmp_path / "Photos"
    root.mkdir()
    lib = manager.attach(str(root))
    alice = [_vec(1, i) for i in range(4)]
    bob = [_vec(2, i) for i in range(3)]
    _add_faces(lib, "party.jpg", [(alice[0], None), (bob[0], None)])
    _add_faces(lib, "trip.jpg", [(alice[1], None), (alice[2], None)])
    _add_faces(lib, "office.jpg", [(bob[1], None), (bob[2], None), (_vec(3, 0), None)])   # + a stranger
    # A video: one face with a vector, two more appearances in the same track without
    _add_faces(lib, "birthday.mp4", [(alice[3], 7), (None, 7), (None, 7)])
    return lib


def _persons():
    from app.database.session import db_all
    return {r["id"]: r for r in db_all("SELECT * FROM persons")}


def test_faces_are_grouped_into_people(people_lib, manager):
    from app.people.cluster import recluster
    res = recluster(manager)
    assert res["people"] == 2 and res["faces"] == 8          # faces with an identity vector
    counts = sorted(p["face_count"] for p in _persons().values())
    assert counts == [3, 4]                                # Bob 3, Alice 4 (stranger stays alone)
    lib = people_lib
    stranger = lib.db.scalar("SELECT COUNT(*) FROM faces WHERE person_id IS NULL AND track_id IS NULL")
    assert stranger == 1
    # Video appearances without a vector follow their track
    tracked = lib.db.all("SELECT DISTINCT person_id FROM faces WHERE track_id = 7")
    assert len(tracked) == 1 and tracked[0]["person_id"] is not None


def test_names_survive_regrouping(people_lib, manager):
    from app.database.session import db_run
    from app.people.cluster import recluster
    recluster(manager)
    alice_id = max(_persons().values(), key=lambda p: p["face_count"])["id"]
    db_run("UPDATE persons SET name = 'Alice' WHERE id = ?", (alice_id,))
    _add_faces(people_lib, "beach.jpg", [(_vec(1, 9), None)])        # one more photo of her
    recluster(manager)
    persons = _persons()
    assert persons[alice_id]["name"] == "Alice" and persons[alice_id]["face_count"] == 5


def test_merge_and_not_this_person(people_lib, manager):
    from app.people.cluster import assign_face, merge, recluster
    recluster(manager)
    by_size = sorted(_persons().values(), key=lambda p: p["face_count"])
    bob, alice = by_size[0]["id"], by_size[1]["id"]
    # "Not this person": one of Alice's faces is taken out and stays out
    face = people_lib.db.scalar("SELECT id FROM faces WHERE person_id = ? ORDER BY id LIMIT 1", (alice,))
    assign_face(manager, people_lib.id, face, None)
    recluster(manager)
    assert people_lib.db.scalar("SELECT person_id FROM faces WHERE id = ?", (face,)) is None
    # Merging two people moves every face and keeps them together
    merge(manager, bob, alice)
    recluster(manager)
    persons = _persons()
    assert bob not in persons
    assert people_lib.db.scalar("SELECT COUNT(*) FROM faces WHERE person_id = ?", (alice,)) >= 5


def test_search_by_person_name(people_lib, manager, mock_models_available):
    from app.database.session import db_run
    from app.people.cluster import recluster
    from app.search.engine import SearchEngine
    from app.search.plan import build_plan
    recluster(manager)
    alice_id = max(_persons().values(), key=lambda p: p["face_count"])["id"]
    db_run("UPDATE persons SET name = 'Alice Smith' WHERE id = ?", (alice_id,))
    plan = build_plan("photos of alice smith")
    assert [p["name"] for p in plan.people] == ["Alice Smith"]
    assert plan.visual_text == "photos of"
    titles = {i["title"] for i in SearchEngine().search(plan, 20).all()}
    assert {"party.jpg", "trip.jpg", "birthday.mp4"} <= titles
    assert "office.jpg" not in titles                       # only Bob and a stranger there


def test_people_api(people_lib, admin_client):
    c = admin_client
    assert c.post("/api/people/recluster").json()["people"] == 2
    people = c.get("/api/people").json()["people"]
    assert len(people) == 2 and all(p["coverUrl"].startswith("/api/knowledge/") for p in people)
    alice = max(people, key=lambda p: p["faceCount"])
    renamed = c.patch(f"/api/people/{alice['id']}", json={"name": "Alice"}).json()
    assert renamed["name"] == "Alice"
    detail = c.get(f"/api/people/{alice['id']}").json()
    titles = {m["title"] for m in detail["media"]["items"]}
    assert titles == {"party.jpg", "trip.jpg", "birthday.mp4"}
    video = next(m for m in detail["media"]["items"] if m["title"] == "birthday.mp4")
    assert video["faces"] == 3 and video["timestamps"] == [0.0, 1.0, 2.0]
    hidden = c.patch(f"/api/people/{alice['id']}", json={"hidden": True}).json()
    assert hidden["hidden"] is True
    assert all(p["id"] != alice["id"] for p in c.get("/api/people").json()["people"])


def test_sound_search_finds_the_moment(manager, tmp_path, mock_models_available, monkeypatch):
    """A text query that describes a sound goes through CLAP to the matching 10 s window."""
    import app.search.model_pipeline as mp
    from tests.conftest import _stable_seed, _unit_vector
    from tests.test_ingest_pipeline import _make_wav
    root = tmp_path / "Recordings"
    root.mkdir()
    _make_wav(root / "garden birds.wav")
    _make_wav(root / "kitchen.wav")
    lib = manager.attach(str(root))
    from app.library.scanner import scan_library
    from app.ingest.pipeline import claim_next, finish, prepare, run_pass
    scan_library(lib)
    while (job := claim_next(manager)) is not None:
        prep = prepare(*job)
        finish(prep)
        prep.extraction.cleanup()
    assert run_pass(manager, "sounds") == 2
    assert lib.db.scalar("SELECT COUNT(*) FROM audio_segments") == 2
    # Make "birds chirping" sound exactly like the garden recording
    target = _unit_vector(_stable_seed("clap-win:garden birds.wav"), 512)
    monkeypatch.setattr(mp, "clap_text_embedding", lambda text: target)
    from app.search.engine import SearchEngine
    from app.search.plan import build_plan
    plan = build_plan("birds chirping")
    assert plan.clap_text_vec is not None
    top = SearchEngine().search(plan, 10).audio[0]
    assert top["title"] == "garden birds.wav" and top["evidence"] == "sound"
    assert top["startTime"] == 0.0 and top["snippet"].startswith("Sound match at 0:00")
