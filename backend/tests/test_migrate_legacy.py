"""The legacy → Uploads library migration: copies with preserved ids, aliases, rollback, finalize."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture
def legacy(manager, tmp_path):
    from app.core.config import settings
    from app.database.session import db_run
    up = settings.resolved_upload_dir
    up.mkdir(parents=True, exist_ok=True)
    db_run("INSERT OR IGNORE INTO users (id, email, username, password_hash, role) "
           "VALUES ('system', 'system@x.dev', 'System', 'disabled', 'admin')")
    (up / "aaa.txt").write_text("Monsoon planning notes for the drainage project.", encoding="utf-8")
    (up / "bbb.txt").write_text("Monsoon planning notes for the drainage project.", encoding="utf-8")   # same bytes
    rows = [
        ("aaa", "Monsoon notes.txt", "txt", str(up / "aaa.txt"), "{}"),
        ("bbb", "Monsoon notes copy.txt", "txt", str(up / "bbb.txt"), "{}"),
        ("web1", "Rainfall outlook", "article", "https://example.org/rain",
         json.dumps({"source_type": "internet", "url": "https://example.org/rain"})),
    ]
    for sid, name, ext, path, meta in rows:
        db_run("INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, "
               "processing_status, metadata_json, upload_date, uploaded_by) VALUES (?, ?, ?, ?, ?, 10, 'completed', ?, '2026-01-01', 'system')",
               (sid, name, name, ext, path, meta))
    db_run("INSERT INTO documents (id, source_id, title, full_text) VALUES ('d1', 'web1', 'Rainfall outlook', "
           "'Above normal rainfall is expected along the coast.')")
    return up


def test_apply_rollback_and_finalize(legacy, manager, mock_models_available):
    import migrate_legacy as ml
    from app.database.session import db_all, db_get
    m = ml.plan_and_apply(apply=True)
    assert [c["id"] for c in m["copied"]] == ["aaa"]
    assert m["aliases"] == [{"id": "bbb", "target": "aaa"}]
    assert [x["id"] for x in m["markdown"]] == ["web1"]
    uploads = manager.uploads()
    assert (uploads.root / "Monsoon notes.txt").read_text(encoding="utf-8").startswith("Monsoon planning")
    md = (uploads.root / "Internet" / "Rainfall outlook.md").read_text(encoding="utf-8")
    assert "https://example.org/rain" in md and "Above normal rainfall" in md
    # Old ids keep working, including the duplicate's
    assert manager.find_source("aaa")[1]["status"] == "queued"
    assert manager.find_source("src-bbb")[1]["id"] == "aaa"
    assert manager.find_source("web1")[1]["origin"] == "internet"
    assert {r["source_id"] for r in db_all("SELECT source_id FROM legacy_migrated")} == {"aaa", "bbb", "web1"}
    assert (legacy / "aaa.txt").exists()                      # nothing deleted by --apply
    # Running again changes nothing
    again = ml.plan_and_apply(apply=True)
    assert not again["copied"] and not again["markdown"]

    path = legacy.parent / "manifest.json"
    path.write_text(json.dumps(m), encoding="utf-8")
    ml.rollback(path)
    assert not (uploads.root / "Monsoon notes.txt").exists()
    assert manager.find_source("aaa") is None
    assert db_all("SELECT source_id FROM legacy_migrated") == []

    m = ml.plan_and_apply(apply=True)
    path.write_text(json.dumps(m), encoding="utf-8")
    ml.finalize(path)
    assert not (legacy / "aaa.txt").exists()                  # the app's old copy
    assert (legacy / "bbb.txt").exists()                      # duplicates' files are left for the user to judge
    assert db_all("SELECT id FROM knowledge_sources") == []
    assert (uploads.root / "Monsoon notes.txt").exists()
