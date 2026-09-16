// src/lib/db/seed-demo.ts
// Seeds sample multimodal knowledge assets (including the SSC Chairman Gopal Krishna video/podcast and NEET documents)
// with face embeddings, visual frame embeddings, transcripts, and metadata for seamless testing.

import fs from 'fs';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import { dbGet, dbAll, dbTransaction } from './client';
import {
  getImageEmbedding,
  getTextEmbedding,
  floatArrayToBuffer,
} from '@/lib/embeddings/multimodal-embeddings';

export async function seedDemoDataIfNeeded() {
  const existing = dbGet<{ id: string }>('SELECT id FROM knowledge_sources WHERE original_name LIKE ?', ['%SSC Chairman Gopal Krishna%']);
  if (existing) {
    console.log('[SeedDemo] Sample SSC Chairman Gopal Krishna video already indexed.');
    return;
  }

  console.log('[SeedDemo] Seeding sample SSC Chairman Gopal Krishna knowledge asset & NEET documents...');

  const adminUser = dbGet<{ id: string }>('SELECT id FROM users LIMIT 1');
  const userId = adminUser?.id || 'admin-user';

  // 1. Seed "SSC Chairman Gopal Krishna - Exclusive Interview Podcast.mp4"
  const sscSourceId = uuidv4();
  const sscVideoId = uuidv4();
  const sscFramesDir = path.join(process.cwd(), 'uploads', 'frames', sscSourceId);
  const sscFacesDir = path.join(process.cwd(), 'uploads', 'faces', sscSourceId);
  
  if (!fs.existsSync(sscFramesDir)) fs.mkdirSync(sscFramesDir, { recursive: true });
  if (!fs.existsSync(sscFacesDir)) fs.mkdirSync(sscFacesDir, { recursive: true });

  // Create sample keyframe images with SVG/Canvas/buffer representation if not existing
  const frame1Path = path.join(sscFramesDir, 'frame_0001.jpg');
  const frame2Path = path.join(sscFramesDir, 'frame_0002.jpg');
  const face1CropPath = path.join(sscFacesDir, 'face_crop_0001.jpg');

  // Write a simple valid JPEG placeholder buffer if not on disk
  const sampleJpgBuffer = Buffer.from([
    0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x01, 0x00, 0x48,
    0x00, 0x48, 0x00, 0x00, 0xff, 0xdb, 0x00, 0x43, 0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
    0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0a, 0x0c, 0x14, 0x0d, 0x0c, 0x0b, 0x0b, 0x0c, 0x19, 0x12,
    0x13, 0x0f, 0x14, 0x1d, 0x1a, 0x1f, 0x1e, 0x1d, 0x1a, 0x1c, 0x1c, 0x20, 0x24, 0x2e, 0x27, 0x20,
    0x22, 0x2c, 0x23, 0x1c, 0x1c, 0x28, 0x37, 0x29, 0x2c, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1f, 0x27,
    0x39, 0x3d, 0x38, 0x32, 0x3c, 0x2e, 0x33, 0x34, 0x32, 0xff, 0xc0, 0x00, 0x0b, 0x08, 0x00, 0x20,
    0x00, 0x20, 0x01, 0x01, 0x11, 0x00, 0xff, 0xda, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3f, 0x00,
    0xbf, 0x00, 0xff, 0xd9
  ]);

  fs.writeFileSync(frame1Path, sampleJpgBuffer);
  fs.writeFileSync(frame2Path, sampleJpgBuffer);
  fs.writeFileSync(face1CropPath, sampleJpgBuffer);

  // Compute realistic embeddings for face, visual, and transcript
  const faceEmbVec = await getImageEmbedding(face1CropPath);
  const visualEmbVec = await getImageEmbedding(frame1Path);
  const faceEmbBuffer = floatArrayToBuffer(faceEmbVec);
  const visualEmbBuffer = floatArrayToBuffer(visualEmbVec);

  const transcript1 = "Welcome to the policy podcast. Today we have SSC Chairman Gopal Krishna discussing exam reforms, transparency, and the new digital examination centers.";
  const transcript2 = "Chairman Gopal Krishna outlines the three-tier security verification and biometrics introduced for the upcoming Staff Selection Commission examinations.";
  
  const textEmb1 = floatArrayToBuffer(await getTextEmbedding(transcript1));
  const textEmb2 = floatArrayToBuffer(await getTextEmbedding(transcript2));

  const docSourceId = uuidv4();
  const docId = uuidv4();
  const docText = `Staff Selection Commission (SSC) Examination Governance and Operational Framework
Issued under Chairman Gopal Krishna.
The commission announces modernized computer-based testing, biometric candidate registration, and real-time CCTV audit systems across 400 nationwide testing centers.
Chairman Gopal Krishna addressed concerns regarding normalization procedures, multi-shift examinations, and candidate grievance redressal mechanisms.`;

  const docChunkId = uuidv4();
  const docEmb = floatArrayToBuffer(await getTextEmbedding(docText));

  const frame1Id = uuidv4();
  const frame2Id = uuidv4();
  const faceId1 = uuidv4();

  dbTransaction((db) => {
    // 1. Insert Video Knowledge Source
    db.prepare(`
      INSERT INTO knowledge_sources (
        id, filename, original_name, file_type, file_path, file_size, uploaded_by,
        processing_status, chunk_count, transcript_count, face_count, frame_count, duration_seconds
      ) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', 0, 2, 1, 2, 840)
    `).run(
      sscSourceId,
      'ssc_chairman_gopal_krishna.mp4',
      'SSC Chairman Gopal Krishna - Exclusive Interview Podcast.mp4',
      'mp4',
      path.join(process.cwd(), 'uploads', 'ssc_chairman_gopal_krishna.mp4'),
      18663641,
      userId
    );

    // 2. Insert Video record
    db.prepare(`
      INSERT INTO videos (id, source_id, duration, format, thumbnail_path)
      VALUES (?, ?, 840, 'mp4', ?)
    `).run(sscVideoId, sscSourceId, frame1Path);

    // 3. Insert Video Transcripts
    db.prepare(`
      INSERT INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding)
      VALUES (?, ?, ?, 0, 45, ?, ?)
    `).run(uuidv4(), sscVideoId, sscSourceId, transcript1, textEmb1);

    db.prepare(`
      INSERT INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding)
      VALUES (?, ?, ?, 84, 140, ?, ?)
    `).run(uuidv4(), sscVideoId, sscSourceId, transcript2, textEmb2);

    // 4. Insert Video Frames
    db.prepare(`
      INSERT INTO video_frames (id, video_id, source_id, timestamp, frame_number, scene_id, frame_path, visual_description, embedding)
      VALUES (?, ?, ?, 15, 1, 1, ?, 'SSC Chairman Gopal Krishna seated in official studio interview setting', ?)
    `).run(frame1Id, sscVideoId, sscSourceId, frame1Path, visualEmbBuffer);

    db.prepare(`
      INSERT INTO video_frames (id, video_id, source_id, timestamp, frame_number, scene_id, frame_path, visual_description, embedding)
      VALUES (?, ?, ?, 84, 2, 2, ?, 'Close-up portrait of SSC Chairman Gopal Krishna answering questions on exam governance', ?)
    `).run(frame2Id, sscVideoId, sscSourceId, frame2Path, visualEmbBuffer);

    // 5. Insert Face Embeddings
    db.prepare(`
      INSERT INTO face_embeddings (id, source_id, video_id, frame_id, timestamp, embedding, confidence, bbox_json)
      VALUES (?, ?, ?, ?, 84, ?, 0.95, ?)
    `).run(
      faceId1,
      sscSourceId,
      sscVideoId,
      frame2Id,
      faceEmbBuffer,
      JSON.stringify({ xMin: 0.28, yMin: 0.12, xMax: 0.72, yMax: 0.65 })
    );

    // 6. Seed related Document: "Staff Selection Commission Examination Reforms & Governance.pdf"
    db.prepare(`
      INSERT INTO knowledge_sources (
        id, filename, original_name, file_type, file_path, file_size, uploaded_by,
        processing_status, chunk_count, page_count
      ) VALUES (?, ?, ?, 'pdf', ?, 416238, ?, 'completed', 1, 12)
    `).run(
      docSourceId,
      'ssc_reforms_governance.pdf',
      'Staff Selection Commission Examination Reforms & Governance.pdf',
      path.join(process.cwd(), 'uploads', 'ssc_reforms_governance.pdf'),
      userId
    );

    db.prepare(`
      INSERT INTO documents (id, source_id, title, full_text, page_count, section_count)
      VALUES (?, ?, 'Staff Selection Commission Examination Reforms & Governance', ?, 12, 1)
    `).run(docId, docSourceId, docText);

    db.prepare(`
      INSERT INTO document_chunks (id, section_id, doc_id, source_id, chunk_text, chunk_order, page_num, embedding)
      VALUES (?, NULL, ?, ?, ?, 0, 1, ?)
    `).run(docChunkId, docId, docSourceId, docText, docEmb);
  });

  console.log('[SeedDemo] Successfully seeded demo knowledge sources.');
}
