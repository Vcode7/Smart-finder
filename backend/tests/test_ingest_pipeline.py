"""
Ingestion pipeline tests: extraction + model stage + writes for every file kind, with
deterministic fake models (no GPU, no downloads).
"""
import asyncio
import io
import math
import struct
import time
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


# ── sample files ─────────────────────────────────────────────────────────────
def _noise_image(w: int, h: int, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, size=(h // 8 + 1, w // 8 + 1, 3), dtype=np.uint8)
    return Image.fromarray(base).resize((w, h), Image.Resampling.NEAREST)


def _make_pdf(path: Path) -> None:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Quarterly revenue grew by twelve percent in the northern region.", fontsize=11)
    page.insert_text((72, 100), "The board approved the new solar plant investment.", fontsize=11)
    buf = io.BytesIO()
    _noise_image(240, 200, 1).save(buf, "PNG")
    page.insert_image(fitz.Rect(72, 150, 312, 350), stream=buf.getvalue())
    scanned = doc.new_page()  # image only, no text layer -> OCR path
    buf2 = io.BytesIO()
    _noise_image(600, 800, 2).save(buf2, "PNG")
    scanned.insert_image(scanned.rect, stream=buf2.getvalue())
    doc.save(str(path))
    doc.close()


def _make_photo(path: Path) -> None:
    img = _noise_image(800, 600, 3)
    exif = Image.Exif()
    exif[0x0112] = 6            # rotate 90° on display -> 600 x 800
    exif[0x0110] = "TestCam X1"
    img.save(str(path), "JPEG", exif=exif, quality=90)


def _make_video(path: Path, seconds: int = 12, fps: int = 5, audio: bool = True) -> None:
    import av
    colors = [(220, 30, 30), (30, 200, 30), (30, 30, 220), (230, 230, 40)]
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width, stream.height = 160, 120
        stream.pix_fmt = "yuv420p"
        stream.codec_context.gop_size = 1000   # one key frame: forces the gap-filling pass
        sound = container.add_stream("aac", rate=16000) if audio else None
        if sound is not None:
            sound.layout = "mono"
        for i in range(seconds * fps):
            color = colors[(i // (3 * fps)) % len(colors)]
            arr = np.zeros((120, 160, 3), dtype=np.uint8)
            arr[:, :] = color
            arr[(i * 3) % 120:(i * 3) % 120 + 20, 40:120] = 255 - np.array(color, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
        if sound is not None:
            t = np.arange(seconds * 16000) / 16000.0
            pcm = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
            for start in range(0, len(pcm), 1024):
                chunk = pcm[start:start + 1024]
                frame = av.AudioFrame.from_ndarray(chunk[None, :], format="fltp", layout="mono")
                frame.sample_rate = 16000
                for packet in sound.encode(frame):
                    container.mux(packet)
            for packet in sound.encode():
                container.mux(packet)


def _make_wav(path: Path, seconds: float = 2.0, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * t / rate))) for t in range(int(seconds * rate))
        )
        w.writeframes(frames)


@pytest.fixture
def fake_models(mock_models_available, monkeypatch):
    """Faces on large images, OCR text on scanned pages, a fixed transcript."""
    import app.search.model_pipeline as mp
    from tests.conftest import _unit_vector

    def faces(img, min_confidence=0.5, model_name="buffalo_s"):
        if min(img.size) < 500:
            return []
        return [{"box": [0.2, 0.3, 0.5, 0.6], "confidence": 0.93, "embedding": _unit_vector(77, 512), "size_px": 180}]

    def ocr(img):
        return "Invoice number 12345 total amount due 990 rupees" if min(img.size) >= 1000 else ""

    segments = [
        {"start": 0.0, "end": 4.0, "text": "Welcome to the solar plant tour."},
        {"start": 4.0, "end": 8.5, "text": "These panels produce four megawatts."},
        {"start": 8.5, "end": 11.0, "text": "Thank you for watching."},
    ]
    monkeypatch.setattr(mp, "detect_and_embed_faces", faces)
    monkeypatch.setattr(mp, "run_ocr", ocr)
    monkeypatch.setattr(mp, "transcribe_audio", lambda path, should_stop=None: list(segments))
    monkeypatch.setattr(mp, "transcribe_media", lambda path, should_stop=None: {
        "segments": list(segments), "language": "en", "language_probability": 0.99, "duration": 11.0})
    return mp


@pytest.fixture
def media_library(manager, tmp_path, fake_models):
    root = tmp_path / "Media Library"
    root.mkdir()
    (root / "notes.txt").write_text(
        "Meeting notes\n\nThe solar plant budget was approved.\n\nनमस्ते, यह हिंदी पाठ है।", encoding="utf-8"
    )
    (root / "sales.csv").write_text(
        "region,product,amount\n" + "\n".join(f"north,widget-{i},{i * 10}" for i in range(400)), encoding="utf-8"
    )
    (root / "docs").mkdir()
    _make_pdf(root / "docs" / "report.pdf")
    _make_photo(root / "holiday.jpg")
    _make_video(root / "clip.mp4")
    _make_video(root / "silent.mp4", seconds=4, audio=False)
    _make_wav(root / "voice.wav")
    lib = manager.attach(str(root))
    from app.library.scanner import scan_library
    assert scan_library(lib).new == 7
    return lib


def _process_all(manager, transcribe: bool = True):
    from app.ingest.pipeline import claim_next, finish, prepare, run_transcriptions
    results = {}
    while True:
        job = claim_next(manager)
        if job is None:
            break
        lib, src = job
        prep = prepare(lib, src)
        try:
            results[src["rel_path"]] = finish(prep)
        finally:
            prep.extraction.cleanup()
    if transcribe:
        run_transcriptions(manager)
    return results


def _sid(lib, rel):
    return lib.db.scalar("SELECT id FROM sources WHERE rel_path = ?", (rel,))


# ── tests ────────────────────────────────────────────────────────────────────
def test_every_kind_is_indexed(manager, media_library):
    lib = media_library
    results = _process_all(manager)
    assert set(results) == {"notes.txt", "sales.csv", "docs/report.pdf", "holiday.jpg", "clip.mp4",
                            "silent.mp4", "voice.wav"}
    statuses = {r["rel_path"]: r["status"] for r in lib.db.all("SELECT rel_path, status FROM sources")}
    assert set(statuses.values()) == {"indexed"}, statuses

    # Text file: body chunks (Hindi kept) + a title chunk
    notes = _sid(lib, "notes.txt")
    kinds = [r["kind"] for r in lib.db.all("SELECT kind FROM chunks WHERE source_id = ?", (notes,))]
    assert "body" in kinds and "title" in kinds
    assert lib.db.scalar("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'हिंदी'") >= 1

    # CSV: several table chunks, each repeating the header
    sales = _sid(lib, "sales.csv")
    tables = lib.db.all("SELECT text FROM chunks WHERE source_id = ? AND kind = 'table'", (sales,))
    assert len(tables) >= 3
    assert all(t["text"].startswith("region | product | amount") for t in tables)

    # PDF: page text, embedded image, scanned page OCR'd into page text
    pdf = _sid(lib, "docs/report.pdf")
    src = lib.db.one("SELECT * FROM sources WHERE id = ?", (pdf,))
    assert src["page_count"] == 2
    page1 = lib.db.all("SELECT * FROM chunks WHERE source_id = ? AND page = 1 AND kind = 'body'", (pdf,))
    assert page1 and "revenue" in page1[0]["text"]
    ocr = lib.db.one("SELECT * FROM chunks WHERE source_id = ? AND kind = 'ocr'", (pdf,))
    assert ocr and ocr["page"] == 2 and "Invoice" in ocr["text"] and ocr["visual_item_id"]
    vis_kinds = sorted(r["kind"] for r in lib.db.all("SELECT kind FROM visual_items WHERE source_id = ?", (pdf,)))
    assert vis_kinds == ["doc_image", "page"]
    cache = lib.source_cache_dir(pdf)
    assert (cache / "page_00002.webp").exists() and (cache / "thumb.webp").exists()
    assert not (cache / "_work").exists()
    assert any(s["page"] == 2 for s in lib.db.all("SELECT page FROM sections WHERE source_id = ?", (pdf,)))

    # Photo: EXIF rotation, camera, CLIP vector, a face with identity vector and crop
    photo = _sid(lib, "holiday.jpg")
    src = lib.db.one("SELECT * FROM sources WHERE id = ?", (photo,))
    assert (src["width"], src["height"]) == (600, 800)
    assert "TestCam X1" in src["meta_json"]
    face = lib.db.one("SELECT * FROM faces WHERE source_id = ?", (photo,))
    assert face and face["crop_path"] and (lib.source_cache_dir(photo) / face["crop_path"]).exists()
    assert lib.db.scalar("SELECT COUNT(*) FROM vectors WHERE space = 'face' AND source_id = ?", (photo,)) == 1
    assert lib.db.scalar("SELECT COUNT(*) FROM vectors WHERE space = 'clip' AND source_id = ?", (photo,)) == 1
    assert lib.db.scalar("SELECT phash FROM visual_items WHERE source_id = ?", (photo,)) is not None

    # Video: real duration, several distinct keyframes (gap-filled), transcript windows
    video = _sid(lib, "clip.mp4")
    src = lib.db.one("SELECT * FROM sources WHERE id = ?", (video,))
    assert 11.0 <= src["duration"] <= 13.0
    frames = lib.db.all("SELECT ts, cache_path FROM visual_items WHERE source_id = ? AND kind = 'keyframe' ORDER BY ts", (video,))
    assert len(frames) >= 4
    assert all((lib.source_cache_dir(video) / f["cache_path"]).exists() for f in frames)
    assert lib.db.scalar("SELECT COUNT(*) FROM transcript_segments WHERE source_id = ?", (video,)) == 3
    tr = lib.db.one("SELECT * FROM chunks WHERE source_id = ? AND kind = 'transcript'", (video,))
    assert tr and tr["ts_start"] == 0.0 and "solar" in tr["text"]
    assert not (lib.source_cache_dir(video) / "_work").exists()
    assert lib.db.scalar("SELECT transcript FROM sources WHERE id = ?", (video,)) == "done"
    # A video without a sound track is not sent to Whisper
    silent = _sid(lib, "silent.mp4")
    assert lib.db.scalar("SELECT transcript FROM sources WHERE id = ?", (silent,)) is None
    assert lib.db.scalar("SELECT COUNT(*) FROM transcript_segments WHERE source_id = ?", (silent,)) == 0
    assert lib.db.scalar("SELECT COUNT(*) FROM visual_items WHERE source_id = ?", (silent,)) >= 2

    # Audio: duration + transcript
    voice = _sid(lib, "voice.wav")
    assert abs(lib.db.scalar("SELECT duration FROM sources WHERE id = ?", (voice,)) - 2.0) < 0.2
    assert lib.db.scalar("SELECT COUNT(*) FROM transcript_segments WHERE source_id = ?", (voice,)) == 3

    # FAISS indexes hold exactly the vectors SQLite has
    for space in ("text", "clip", "face"):
        rows = lib.db.scalar("SELECT COUNT(*) FROM vectors WHERE space = ?", (space,))
        assert lib.vectors.spaces[space].ntotal == rows, space
    assert lib.db.scalar("SELECT COUNT(*) FROM chunks") == lib.db.scalar("SELECT COUNT(*) FROM vectors WHERE space = 'text'")


def test_reindexing_never_duplicates(manager, media_library):
    from app.library.sources import queue_source
    lib = media_library
    _process_all(manager)
    pdf = _sid(lib, "docs/report.pdf")

    def snapshot():
        return tuple(lib.db.scalar(f"SELECT COUNT(*) FROM {t} WHERE source_id = ?", (pdf,))
                     for t in ("chunks", "visual_items", "faces", "sections", "vectors"))

    before = snapshot()
    total_text = lib.vectors.spaces["text"].ntotal
    assert queue_source(lib, pdf)
    _process_all(manager)
    assert snapshot() == before
    assert lib.vectors.spaces["text"].ntotal == total_text


def test_transcription_waits_for_main_queue_and_replaces_old_transcript(manager, media_library):
    from app.ingest.pipeline import next_action, run_transcriptions
    from app.library.sources import PRIORITY_UPLOAD
    lib = media_library
    assert next_action(manager) == "index"
    _process_all(manager, transcribe=False)
    video = _sid(lib, "clip.mp4")
    assert lib.db.scalar("SELECT transcript FROM sources WHERE id = ?", (video,)) == "pending"
    # Searchable by image and text already; the soundtrack follows in its own pass
    assert lib.db.scalar("SELECT status FROM sources WHERE id = ?", (video,)) == "indexed"
    assert next_action(manager) == "transcribe"

    # An upload jumps ahead of pending transcriptions
    from app.library.sources import add_or_update_source
    (lib.root / "urgent.txt").write_text("uploaded just now", encoding="utf-8")
    add_or_update_source(lib, "urgent.txt", size=17, mtime=1, priority=PRIORITY_UPLOAD)
    assert next_action(manager) == "index"
    _process_all(manager, transcribe=False)

    assert run_transcriptions(manager) == 2          # clip.mp4 + voice.wav
    text_vectors = lib.vectors.spaces["text"].ntotal
    chunks = lib.db.scalar("SELECT COUNT(*) FROM chunks WHERE source_id = ?", (video,))
    # Transcribing again replaces the transcript instead of adding a second copy
    lib.db.execute("UPDATE sources SET transcript = 'pending' WHERE id = ?", (video,))
    assert run_transcriptions(manager) == 1
    assert lib.db.scalar("SELECT COUNT(*) FROM chunks WHERE source_id = ?", (video,)) == chunks
    assert lib.db.scalar("SELECT COUNT(*) FROM transcript_segments WHERE source_id = ?", (video,)) == 3
    assert lib.vectors.spaces["text"].ntotal == text_vectors
    # Then pictures are described and soundtracks embedded, after which nothing is left
    assert next_action(manager) == "caption"
    from app.ingest.pipeline import run_pass
    assert run_pass(manager, "caption") >= 3        # photo, pdf images, both videos' frames
    assert next_action(manager) == "sounds"
    assert run_pass(manager, "sounds") == 2
    assert next_action(manager) is None


def test_failed_file_leaves_no_partial_data(manager, tmp_path, fake_models):
    from app.ingest.pipeline import claim_next, mark_failed, prepare
    root = tmp_path / "broken"
    root.mkdir()
    (root / "corrupt.pdf").write_bytes(b"%PDF-1.4 this is not really a pdf" * 10)
    lib = manager.attach(str(root))
    from app.library.scanner import scan_library
    scan_library(lib)
    lib2, src = claim_next(manager)
    with pytest.raises(Exception) as exc:
        prepare(lib2, src)
    mark_failed(lib2, src, str(exc.value))
    row = lib.db.one("SELECT status, error, attempts FROM sources WHERE id = ?", (src["id"],))
    assert row["status"] == "failed" and row["error"] and row["attempts"] == 1
    assert lib.db.scalar("SELECT COUNT(*) FROM chunks") == 0
    assert not lib.source_cache_dir(src["id"]).exists()


def test_file_changed_while_indexing_is_requeued(manager, media_library):
    from app.ingest.pipeline import claim_next, finish, prepare
    from app.library.sources import add_or_update_source
    lib = media_library
    while True:
        lib2, src = claim_next(manager)
        if src["rel_path"] == "notes.txt":
            break
        lib2.db.execute("UPDATE sources SET status = 'queued' WHERE id = ?", (src["id"],))
        lib2.db.execute("UPDATE sources SET priority = -1 WHERE id = ?", (src["id"],))
    prep = prepare(lib2, src)
    # The watcher sees a new version of the file mid-run
    add_or_update_source(lib, "notes.txt", size=src["size"] + 10, mtime=src["mtime"] + 60)
    # ...and the same source must not be claimed twice while it is still running
    busy_claim = claim_next(manager, busy=[src["id"]])
    assert busy_claim is None or busy_claim[1]["id"] != src["id"]
    result = finish(prep)
    prep.extraction.cleanup()
    assert result["current"] is False
    assert lib.db.scalar("SELECT status FROM sources WHERE id = ?", (src["id"],)) == "queued"


def test_cancellation_and_requeue(manager, media_library):
    from app.ingest.pipeline import IndexingCancelled, claim_next, finish, prepare, recover_interrupted, requeue
    lib = media_library
    lib2, src = claim_next(manager)
    prep = prepare(lib2, src)
    with pytest.raises(IndexingCancelled):
        finish(prep, should_stop=lambda: True)
    prep.extraction.cleanup()
    requeue(lib2, src)
    row = lib.db.one("SELECT status, attempts FROM sources WHERE id = ?", (src["id"],))
    assert row["status"] == "queued" and row["attempts"] == 0

    # A crash leaves 'processing' rows: recovered with bounded attempts
    lib.db.execute("UPDATE sources SET status = 'processing', attempts = 1 WHERE rel_path = 'notes.txt'")
    lib.db.execute("UPDATE sources SET status = 'processing', attempts = 3 WHERE rel_path = 'sales.csv'")
    assert recover_interrupted(manager) == 1
    assert lib.db.scalar("SELECT status FROM sources WHERE rel_path = 'notes.txt'") == "queued"
    assert lib.db.scalar("SELECT status FROM sources WHERE rel_path = 'sales.csv'") == "failed"


def test_claim_order_priority_then_size(manager, tmp_path, fake_models):
    from app.ingest.pipeline import claim_next
    from app.library.sources import PRIORITY_UPLOAD, add_or_update_source
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    lib_a, lib_b = manager.attach(str(a)), manager.attach(str(b))
    add_or_update_source(lib_a, "big.txt", size=5000, mtime=1)
    add_or_update_source(lib_a, "small.txt", size=10, mtime=1)
    add_or_update_source(lib_b, "upload.txt", size=99999, mtime=1, priority=PRIORITY_UPLOAD)
    order = []
    while (job := claim_next(manager)) is not None:
        order.append(job[1]["rel_path"])
    assert order == ["upload.txt", "small.txt", "big.txt"]

    # Paused libraries are skipped
    lib_a.db.execute("UPDATE sources SET status = 'queued'")
    manager.set_flags(lib_a.id, paused=True)
    assert claim_next(manager) is None


def test_face_tracker_keeps_one_vector_per_appearance():
    from app.ingest.pipeline import FACE_TRACK_RESAMPLE_S, _FaceTracker
    from tests.conftest import _unit_vector
    t = _FaceTracker()
    alice = np.asarray(_unit_vector(1, 512), dtype=np.float32)
    bob = np.asarray(_unit_vector(2, 512), dtype=np.float32)
    first = t.match(alice, 0.0, True)
    first["vector_ts"] = 0.0
    assert t.match(alice, 3.0, True)["id"] == first["id"]
    assert t.match(bob, 3.0, True)["id"] != first["id"]
    # After a long gap the same person starts a new appearance
    assert t.match(alice, 100.0, True)["id"] != first["id"]
    # Within one long appearance a new vector is due once per resample interval
    steady = t.match(alice, 101.0, True)
    assert steady["vector_ts"] is None or 101.0 - steady["vector_ts"] < FACE_TRACK_RESAMPLE_S


def test_background_pipeline_drains_queue(manager, media_library):
    from app.ingest.pipeline import IngestionPipeline
    lib = media_library

    async def run():
        p = IngestionPipeline(manager)
        p.start()
        deadline = time.time() + 120
        while time.time() < deadline:
            await asyncio.sleep(0.2)
            s = p.status()
            if s["queued"] == 0 and s["processing"] == 0 and s["current"] is None:
                break
        status = p.status()
        await p.stop()
        return status

    status = asyncio.run(run())
    assert status["indexed"] == 7 and status["failed"] == 0, status
    assert status["completedThisSession"] == 7
    assert lib.db.scalar("SELECT COUNT(*) FROM sources WHERE status != 'indexed'") == 0
    # Vector indexes were checkpointed on stop
    assert (lib.index_dir / "vectors" / "text.faiss").exists()


def test_long_transcript_segments_are_split_at_punctuation():
    from types import SimpleNamespace as NS
    from app.search.model_pipeline import _split_segment
    words = []
    t = 0.0
    for i in range(40):                      # 40 words, 0.5 s each = 20 s
        token = f" word{i}" + ("." if i in (17, 30) else "")
        words.append(NS(start=t, end=t + 0.5, word=token))
        t += 0.5
    seg = NS(start=0.0, end=20.0, text=" ".join(w.word.strip() for w in words), words=words)
    parts = _split_segment(seg)
    assert len(parts) >= 2
    assert parts[0]["end"] == 9.0 and parts[0]["text"].endswith("word17.")   # cut at the first full stop after 8 s
    assert all(p["end"] - p["start"] <= 14.0 for p in parts)
    assert " ".join(p["text"] for p in parts).split() == seg.text.split()       # nothing lost
    short = NS(start=0.0, end=5.0, text=" hello there ", words=words[:10])
    assert _split_segment(short) == [{"start": 0.0, "end": 5.0, "text": "hello there"}]


def test_icons_are_indexed_by_name_only_and_never_described(manager, tmp_path, fake_models):
    from app.ingest.pipeline import caption_source, claim_next, finish, prepare
    from app.library.scanner import scan_library
    root = tmp_path / "Viewer"
    (root / "ui").mkdir(parents=True)        # icon folders are not scanned at all (test_libraries)
    _noise_image(48, 48, 5).save(root / "ui" / "arrow.png")
    _noise_image(900, 700, 6).save(root / "photo.jpg", "JPEG")
    lib = manager.attach(str(root))
    scan_library(lib)
    while (job := claim_next(manager)) is not None:
        prep = prepare(*job)
        finish(prep)
        prep.extraction.cleanup()
    icon = lib.db.one("SELECT * FROM sources WHERE name = 'arrow.png'")
    assert icon["status"] == "indexed" and icon["captions"] is None
    assert lib.db.scalar("SELECT COUNT(*) FROM visual_items WHERE source_id = ?", (icon["id"],)) == 0
    # Only the title chunk's text vector: no image vector
    assert lib.db.scalar("SELECT COUNT(*) FROM vectors WHERE source_id = ? AND space != 'text'", (icon["id"],)) == 0
    assert lib.db.scalar("SELECT COUNT(*) FROM chunks WHERE source_id = ? AND kind = 'title'", (icon["id"],)) == 1
    # A picture already indexed before this rule (it has a visual item) is still skipped by the caption pass
    sid = icon["id"]
    lib.db.execute("INSERT INTO visual_items (source_id, kind, width, height, cache_path) VALUES (?, 'photo', 48, 48, 'thumb.webp')", (sid,))
    lib.db.execute("UPDATE sources SET captions = 'running' WHERE id = ?", (sid,))
    assert caption_source(lib, lib.db.one("SELECT * FROM sources WHERE id = ?", (sid,)))["captions"] == 0
    assert lib.db.scalar("SELECT caption FROM visual_items WHERE source_id = ?", (sid,)) is None
    # The real photo is described
    photo = lib.db.one("SELECT * FROM sources WHERE name = 'photo.jpg'")
    assert photo["captions"] == "pending"


def test_strips_and_small_pictures_are_not_described(manager, tmp_path, fake_models):
    from app.ingest.pipeline import claim_next, finish, prepare
    from app.library.scanner import scan_library
    root = tmp_path / "Pictures"
    root.mkdir()
    _noise_image(900, 28, 7).save(root / "thickness.png")       # a strip: long, but 28 px thin
    _noise_image(150, 150, 8).save(root / "badge.png")          # gets an image vector, too small to describe
    lib = manager.attach(str(root))
    scan_library(lib)
    results = {}
    while (job := claim_next(manager)) is not None:
        prep = prepare(*job)
        results[job[1]["name"]] = finish(prep)
        prep.extraction.cleanup()
    strip = lib.db.one("SELECT * FROM sources WHERE name = 'thickness.png'")
    assert lib.db.scalar("SELECT COUNT(*) FROM visual_items WHERE source_id = ?", (strip["id"],)) == 0
    assert results["thickness.png"]["small_images"] == 1 and strip["captions"] is None
    badge = lib.db.one("SELECT * FROM sources WHERE name = 'badge.png'")
    assert lib.db.scalar("SELECT COUNT(*) FROM visual_items WHERE source_id = ?", (badge["id"],)) == 1
    assert results["badge.png"]["small_images"] == 0
    assert badge["captions"] is None        # no caption pass queued for nothing to describe


def test_small_images_indexed_before_the_size_rules_are_requeued_once(manager, tmp_path, fake_models):
    from app.ingest.pipeline import claim_next, finish, prepare, requeue_undersized_images
    from app.library.scanner import scan_library
    root = tmp_path / "Old"
    root.mkdir()
    _noise_image(64, 64, 9).save(root / "play.png")
    _noise_image(900, 700, 10).save(root / "photo.jpg", "JPEG")
    lib = manager.attach(str(root))
    scan_library(lib)
    while (job := claim_next(manager)) is not None:
        prep = prepare(*job)
        finish(prep)
        prep.extraction.cleanup()
    icon_id = lib.db.scalar("SELECT id FROM sources WHERE name = 'play.png'")
    # What an older version left behind: a visual (and description) for the icon
    lib.db.execute("INSERT INTO visual_items (source_id, kind, width, height, cache_path, caption) "
                   "VALUES (?, 'photo', 64, 64, 'thumb.webp', 'a black and white abstract background')", (icon_id,))
    # A source without a recorded size (migrated from the old index) is never touched
    photo_id = lib.db.scalar("SELECT id FROM sources WHERE name = 'photo.jpg'")
    lib.db.execute("UPDATE sources SET width = NULL, height = NULL WHERE id = ?", (photo_id,))
    # Nor one in an icon folder: the next scan forgets it (re-indexing it would race the scan)
    from app.library.sources import add_or_update_source
    _noise_image(20, 20, 11).save(root / "back.png")
    btn = add_or_update_source(lib, "viewer/icons/back.png", 100, time.time(), origin="folder")
    lib.db.execute("UPDATE sources SET status = 'indexed', width = 20, height = 20 WHERE id = ?", (btn,))
    lib.db.execute("INSERT INTO visual_items (source_id, kind, width, height) VALUES (?, 'photo', 20, 20)", (btn,))
    assert requeue_undersized_images(lib) == 1
    assert lib.db.scalar("SELECT status FROM sources WHERE id = ?", (icon_id,)) == "queued"
    assert lib.db.scalar("SELECT status FROM sources WHERE name = 'photo.jpg'") == "indexed"
    while (job := claim_next(manager)) is not None:
        prep = prepare(*job)
        finish(prep)
        prep.extraction.cleanup()
    assert lib.db.scalar("SELECT COUNT(*) FROM visual_items WHERE source_id = ?", (icon_id,)) == 0
    assert requeue_undersized_images(lib) == 0


def test_image_model_change_remakes_image_vectors(manager, media_library):
    from app.ingest.pipeline import requeue_stale_image_vectors, run_pass
    from app.search.constants import IMAGE_EMBED_MODEL
    lib = media_library
    _process_all(manager, transcribe=False)
    count = lambda: lib.db.scalar("SELECT COUNT(*) FROM vectors WHERE space = 'clip'")
    made = count()
    # As a library indexed by an older image model looks: vectors, no model recorded
    assert made > 0 and lib.vectors.space_model("clip") is None
    with_pictures = lib.db.scalar("SELECT COUNT(DISTINCT source_id) FROM visual_items")
    assert requeue_stale_image_vectors(lib) == with_pictures
    assert count() == 0 and lib.vectors.spaces["clip"].ntotal == 0
    assert lib.vectors.space_model("clip") == IMAGE_EMBED_MODEL
    assert run_pass(manager, "images") == with_pictures
    assert count() == made and lib.vectors.spaces["clip"].ntotal == made
    assert lib.db.scalar("SELECT COUNT(*) FROM sources WHERE image_vectors = 'done'") == with_pictures
    assert requeue_stale_image_vectors(lib) == 0             # the current model is recorded
    # Indexing a file again makes its vectors with the current model: no image pass left for it
    lib.db.execute("UPDATE sources SET image_vectors = 'pending', status = 'queued' WHERE name = 'holiday.jpg'")
    _process_all(manager, transcribe=False)
    assert lib.db.scalar("SELECT image_vectors FROM sources WHERE name = 'holiday.jpg'") is None


def test_library_without_image_vectors_only_records_the_model(manager, tmp_path, fake_models):
    from app.ingest.pipeline import requeue_stale_image_vectors
    from app.search.constants import IMAGE_EMBED_MODEL
    root = tmp_path / "Texts"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")
    lib = manager.attach(str(root))
    assert requeue_stale_image_vectors(lib) == 0
    assert lib.vectors.space_model("clip") == IMAGE_EMBED_MODEL
