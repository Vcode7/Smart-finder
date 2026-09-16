import uuid
import math
import numpy as np
from pathlib import Path
from app.core.config import settings
from app.core.security import hash_password
from app.database.session import db_get, db_run, get_db_context

def create_vec_bytes(dim: int, seed: float) -> bytes:
    arr = np.zeros(dim, dtype=np.float32)
    for i in range(dim):
        arr[i] = math.sin((i + 1) * seed)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr.tobytes()

def seed_system_user() -> None:
    exists = db_get("SELECT id FROM users WHERE id = 'system'")
    if not exists:
        db_run(
            "INSERT OR IGNORE INTO users (id, email, username, password_hash, role) VALUES ('system', 'system@smartfind.ai', 'System', 'disabled', 'admin')"
        )
        print("[DB] System user seeded: system@smartfind.ai")

def seed_admin() -> None:
    seed_system_user()
    admin_email = settings.ADMIN_EMAIL
    admin_password = settings.ADMIN_PASSWORD
    if not admin_email or not admin_password:
        return

    exists = db_get("SELECT id FROM users WHERE role = 'admin' AND id != 'system'")
    if exists:
        return

    admin_id = str(uuid.uuid4())
    pw_hash = hash_password(admin_password)

    db_run(
        "INSERT INTO users (id, email, username, password_hash, role) VALUES (?, ?, ?, ?, 'admin')",
        (admin_id, admin_email.lower(), "Admin", pw_hash),
    )
    print(f"[DB] Admin account seeded: {admin_email}")

def seed_demo_knowledge() -> None:
    seed_system_user()
    exists = db_get("SELECT id FROM knowledge_sources WHERE original_name LIKE '%SSC Chairman Gopal Krishna%'")
    if exists:
        return

    ssc_source_id = str(uuid.uuid4())
    ssc_video_id = str(uuid.uuid4())
    frame1_id = str(uuid.uuid4())
    frame2_id = str(uuid.uuid4())
    face_id1 = str(uuid.uuid4())

    frames_dir = settings.resolved_upload_dir / "frames" / ssc_source_id
    faces_dir = settings.resolved_upload_dir / "faces" / ssc_source_id
    frames_dir.mkdir(parents=True, exist_ok=True)
    faces_dir.mkdir(parents=True, exist_ok=True)

    frame1_path = frames_dir / "frame_0001.jpg"
    frame2_path = frames_dir / "frame_0002.jpg"
    face1_crop_path = faces_dir / "face_crop_0001.jpg"

    sample_jpg_bytes = bytes([
        0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x01, 0x00, 0x48,
        0x00, 0x48, 0x00, 0x00, 0xff, 0xdb, 0x00, 0x43, 0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
        0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0a, 0x0c, 0x14, 0x0d, 0x0c, 0x0b, 0x0b, 0x0c, 0x19, 0x12,
        0x13, 0x0f, 0x14, 0x1d, 0x1a, 0x1f, 0x1e, 0x1d, 0x1a, 0x1c, 0x1c, 0x20, 0x24, 0x2e, 0x27, 0x20,
        0x22, 0x2c, 0x23, 0x1c, 0x1c, 0x28, 0x37, 0x29, 0x2c, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1f, 0x27,
        0x39, 0x3d, 0x38, 0x32, 0x3c, 0x2e, 0x33, 0x34, 0x32, 0xff, 0xc0, 0x00, 0x0b, 0x08, 0x00, 0x20,
        0x00, 0x20, 0x01, 0x01, 0x11, 0x00, 0xff, 0xda, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3f, 0x00,
        0xbf, 0x00, 0xff, 0xd9
    ])

    try:
        frame1_path.write_bytes(sample_jpg_bytes)
        frame2_path.write_bytes(sample_jpg_bytes)
        face1_crop_path.write_bytes(sample_jpg_bytes)
    except Exception:
        pass

    face_emb = create_vec_bytes(512, 1.23)
    visual_emb = create_vec_bytes(1024, 1.23)
    text_emb1 = create_vec_bytes(1024, 2.34)
    text_emb2 = create_vec_bytes(1024, 3.45)

    transcript1 = "Welcome to the policy podcast. Today we have SSC Chairman Gopal Krishna discussing exam reforms, transparency, and the new digital examination centers."
    transcript2 = "Chairman Gopal Krishna outlines the three-tier security verification and biometrics introduced for the upcoming Staff Selection Commission examinations."

    with get_db_context() as conn:
        cursor = conn.cursor()
        # 1. Insert Video Knowledge Source
        cursor.execute("""
            INSERT INTO knowledge_sources (
                id, filename, original_name, file_type, file_path, file_size, uploaded_by,
                processing_status, chunk_count, transcript_count, face_count, frame_count, duration_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, 'system', 'completed', 0, 2, 1, 2, 840)
        """, (
            ssc_source_id,
            "ssc_chairman_gopal_krishna.mp4",
            "SSC Chairman Gopal Krishna - Exclusive Interview Podcast.mp4",
            "mp4",
            str(settings.resolved_upload_dir / "ssc_chairman_gopal_krishna.mp4"),
            18663641
        ))

        # 2. Insert Video record
        cursor.execute("""
            INSERT INTO videos (id, source_id, duration, format, thumbnail_path)
            VALUES (?, ?, 840, 'mp4', ?)
        """, (ssc_video_id, ssc_source_id, str(frame1_path)))

        # 3. Insert Video Transcripts
        t1_id = str(uuid.uuid4())
        t2_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding)
            VALUES (?, ?, ?, 0, 45, ?, ?)
        """, (t1_id, ssc_video_id, ssc_source_id, transcript1, text_emb1))

        cursor.execute("""
            INSERT INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding)
            VALUES (?, ?, ?, 84, 140, ?, ?)
        """, (t2_id, ssc_video_id, ssc_source_id, transcript2, text_emb2))

        try:
            cursor.execute("""
                INSERT INTO transcripts_fts (text, transcript_id, video_id, source_id, start_time, end_time)
                VALUES (?, ?, ?, ?, 0, 45)
            """, (transcript1, t1_id, ssc_video_id, ssc_source_id))
            cursor.execute("""
                INSERT INTO transcripts_fts (text, transcript_id, video_id, source_id, start_time, end_time)
                VALUES (?, ?, ?, ?, 84, 140)
            """, (transcript2, t2_id, ssc_video_id, ssc_source_id))
        except Exception:
            pass

        # 4. Insert Video Frames
        cursor.execute("""
            INSERT INTO video_frames (id, video_id, source_id, timestamp, frame_number, scene_id, frame_path, visual_description, embedding)
            VALUES (?, ?, ?, 15, 1, 1, ?, 'SSC Chairman Gopal Krishna seated in official studio interview setting', ?)
        """, (frame1_id, ssc_video_id, ssc_source_id, str(frame1_path), visual_emb))

        cursor.execute("""
            INSERT INTO video_frames (id, video_id, source_id, timestamp, frame_number, scene_id, frame_path, visual_description, embedding)
            VALUES (?, ?, ?, 84, 2, 2, ?, 'Close-up portrait of SSC Chairman Gopal Krishna answering questions on exam governance', ?)
        """, (frame2_id, ssc_video_id, ssc_source_id, str(frame2_path), visual_emb))

        # 5. Insert Face Embeddings
        cursor.execute("""
            INSERT INTO face_embeddings (id, source_id, video_id, frame_id, timestamp, embedding, confidence, bbox_json)
            VALUES (?, ?, ?, ?, 84, ?, 0.95, ?)
        """, (
            face_id1,
            ssc_source_id,
            ssc_video_id,
            frame2_id,
            face_emb,
            '{"xMin": 0.28, "yMin": 0.12, "xMax": 0.72, "yMax": 0.65}'
        ))

        # 6. Seed Document
        doc_source_id = str(uuid.uuid4())
        doc_id = str(uuid.uuid4())
        doc_text = (
            "Staff Selection Commission (SSC) Examination Governance and Operational Framework\n"
            "Issued under Chairman Gopal Krishna.\n"
            "The commission announces modernized computer-based testing, biometric candidate registration, "
            "and real-time CCTV audit systems across 400 nationwide testing centers.\n"
            "Chairman Gopal Krishna addressed concerns regarding normalization procedures, multi-shift examinations, "
            "and candidate grievance redressal mechanisms."
        )
        doc_emb = create_vec_bytes(1024, 4.56)

        cursor.execute("""
            INSERT INTO knowledge_sources (
                id, filename, original_name, file_type, file_path, file_size, uploaded_by,
                processing_status, chunk_count, page_count
            ) VALUES (?, ?, ?, 'pdf', ?, 416238, 'system', 'completed', 1, 12)
        """, (
            doc_source_id,
            "ssc_reforms_governance.pdf",
            "Staff Selection Commission Examination Reforms & Governance.pdf",
            str(settings.resolved_upload_dir / "ssc_reforms_governance.pdf")
        ))

        cursor.execute("""
            INSERT INTO documents (id, source_id, title, full_text, page_count, section_count)
            VALUES (?, ?, 'Staff Selection Commission Examination Reforms & Governance', ?, 12, 1)
        """, (doc_id, doc_source_id, doc_text))

        chunk_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO document_chunks (id, section_id, doc_id, source_id, chunk_text, chunk_order, page_num, embedding)
            VALUES (?, NULL, ?, ?, ?, 0, 1, ?)
        """, (chunk_id, doc_id, doc_source_id, doc_text, doc_emb))

        try:
            cursor.execute("""
                INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id)
                VALUES (?, ?, ?, ?)
            """, (doc_text, chunk_id, doc_source_id, doc_id))
        except Exception:
            pass

        conn.commit()
    print("[DB] Seeded demo knowledge source for SSC Chairman Gopal Krishna")

    try:
        from app.search.sync_faiss import sync_existing_data_to_faiss
        sync_existing_data_to_faiss()
    except Exception as e:
        print(f"[DB] Notice syncing demo data to FAISS: {e}")

def seed_database() -> None:
    seed_system_user()
    seed_admin()
    if settings.SEED_DEMO_KNOWLEDGE:
        seed_demo_knowledge()
