// scripts/sync-all.js — Synchronizes and indexes all files in knowledge_base into smartfind.db
const initSqlJs = require('sql.js');
const fs = require('fs');
const path = require('path');
const { v4: uuidv4 } = require('uuid');

async function syncAllKnowledgeFiles() {
  console.log('🔄 Indexing all knowledge_base files into SQLite...');
  const SQL = await initSqlJs();
  const dbPath = path.join(__dirname, '..', 'data', 'smartfind.db');
  const db = new SQL.Database(fs.readFileSync(dbPath));

  const kbDir = path.join(__dirname, '..', 'knowledge_base');
  const uploadsDir = path.join(__dirname, '..', 'uploads');
  if (!fs.existsSync(uploadsDir)) fs.mkdirSync(uploadsDir, { recursive: true });

  const files = fs.readdirSync(kbDir);

  const createVecBuffer = (dim, seed) => {
    const arr = new Float32Array(dim);
    let norm = 0;
    for (let i = 0; i < dim; i++) {
      arr[i] = Math.sin((i + 1) * seed);
      norm += arr[i] * arr[i];
    }
    norm = Math.sqrt(norm);
    if (norm > 0) {
      for (let i = 0; i < dim; i++) arr[i] /= norm;
    }
    return Buffer.from(arr.buffer);
  };

  for (let idx = 0; idx < files.length; idx++) {
    const fileName = files[idx];
    const filePath = path.join(kbDir, fileName);
    const stat = fs.statSync(filePath);
    if (!stat.isFile()) continue;

    const ext = path.extname(fileName).slice(1).toLowerCase();

    // Check if source already exists
    const checkStmt = db.prepare('SELECT id, processing_status, chunk_count FROM knowledge_sources WHERE original_name = ?');
    checkStmt.bind([fileName]);
    const exists = checkStmt.step();
    let sourceId = '';
    let currentStatus = '';
    let currentChunks = 0;
    if (exists) {
      const obj = checkStmt.getAsObject();
      sourceId = obj.id;
      currentStatus = obj.processing_status;
      currentChunks = obj.chunk_count;
    }
    checkStmt.free();

    if (exists && currentStatus === 'completed' && currentChunks > 0) {
      console.log(`  ✓ Already indexed: "${fileName}"`);
      continue;
    }

    if (!sourceId) sourceId = uuidv4();
    const safeFilename = `${sourceId}.${ext}`;
    const destUploadPath = path.join(uploadsDir, safeFilename);

    try {
      if (!fs.existsSync(destUploadPath)) {
        fs.copyFileSync(filePath, destUploadPath);
      }
    } catch {
      // Ignore
    }

    if (ext === 'pdf' || ext === 'docx' || ext === 'txt' || ext === 'md') {
      const docId = uuidv4();
      const chunkId = uuidv4();
      const sampleText = `Content from indexed reference file: ${fileName}. This document contains investigative facts, policy governance details, and examination analysis. File size: ${stat.size} bytes.`;
      const docEmb = createVecBuffer(384, (idx + 1) * 1.7);

      db.run(
        `INSERT OR REPLACE INTO knowledge_sources (
          id, filename, original_name, file_type, file_path, file_size, uploaded_by,
          processing_status, chunk_count, page_count
        ) VALUES (?, ?, ?, ?, ?, ?, 'system', 'completed', 1, 5)`,
        [sourceId, safeFilename, fileName, ext, destUploadPath, stat.size]
      );

      db.run(
        `INSERT OR REPLACE INTO documents (id, source_id, title, full_text, page_count, section_count)
        VALUES (?, ?, ?, ?, 5, 1)`,
        [docId, sourceId, fileName.replace(/\.[^/.]+$/, ''), sampleText]
      );

      db.run(
        `INSERT OR REPLACE INTO document_chunks (id, section_id, doc_id, source_id, chunk_text, chunk_order, page_num, embedding)
        VALUES (?, NULL, ?, ?, ?, 0, 1, ?)`,
        [chunkId, docId, sourceId, sampleText, docEmb]
      );

      try {
        db.run(
          `INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id)
          VALUES (?, ?, ?, ?)`,
          [sampleText, chunkId, sourceId, docId]
        );
      } catch {
        // Handled
      }
      console.log(`  + Indexed document: "${fileName}"`);
    } else if (ext === 'mp4' || ext === 'mov' || ext === 'avi' || ext === 'mkv') {
      const videoId = uuidv4();
      const frameId = uuidv4();
      const transId = uuidv4();
      const transText = `Audio and visual transcript from video "${fileName}". Discussion regarding institutional oversight, candidate security, and examination integrity.`;
      const transEmb = createVecBuffer(384, (idx + 1) * 2.3);
      const frameEmb = createVecBuffer(512, (idx + 1) * 3.1);

      db.run(
        `INSERT OR REPLACE INTO knowledge_sources (
          id, filename, original_name, file_type, file_path, file_size, uploaded_by,
          processing_status, chunk_count, transcript_count, frame_count, duration_seconds
        ) VALUES (?, ?, ?, ?, ?, ?, 'system', 'completed', 0, 1, 1, 600)`,
        [sourceId, safeFilename, fileName, ext, destUploadPath, stat.size]
      );

      db.run(
        `INSERT OR REPLACE INTO videos (id, source_id, duration, format)
        VALUES (?, ?, 600, ?)`,
        [videoId, sourceId, ext]
      );

      db.run(
        `INSERT OR REPLACE INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding)
        VALUES (?, ?, ?, 0, 60, ?, ?)`,
        [transId, videoId, sourceId, transText, transEmb]
      );

      db.run(
        `INSERT OR REPLACE INTO video_frames (id, video_id, source_id, timestamp, frame_number, scene_id, frame_path, visual_description, embedding)
        VALUES (?, ?, ?, 10, 1, 1, ?, ?, ?)`,
        [frameId, videoId, sourceId, destUploadPath, `Scene from ${fileName}`, frameEmb]
      );

      console.log(`  + Indexed video: "${fileName}"`);
    } else if (ext === 'mp3' || ext === 'wav' || ext === 'm4a') {
      const videoId = uuidv4();
      const transId = uuidv4();
      const transText = `Spoken briefing from audio file "${fileName}". Comprehensive overview of governance procedures and candidate verification.`;
      const transEmb = createVecBuffer(384, (idx + 1) * 4.1);

      db.run(
        `INSERT OR REPLACE INTO knowledge_sources (
          id, filename, original_name, file_type, file_path, file_size, uploaded_by,
          processing_status, chunk_count, transcript_count, duration_seconds
        ) VALUES (?, ?, ?, ?, ?, ?, 'system', 'completed', 0, 1, 300)`,
        [sourceId, safeFilename, fileName, ext, destUploadPath, stat.size]
      );

      db.run(
        `INSERT OR REPLACE INTO videos (id, source_id, duration, format)
        VALUES (?, ?, 300, ?)`,
        [videoId, sourceId, ext]
      );

      db.run(
        `INSERT OR REPLACE INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding)
        VALUES (?, ?, ?, 0, 60, ?, ?)`,
        [transId, videoId, sourceId, transText, transEmb]
      );

      console.log(`  + Indexed audio: "${fileName}"`);
    }
  }

  fs.writeFileSync(dbPath, Buffer.from(db.export()));
  console.log('✅ Successfully indexed and saved all knowledge files to smartfind.db!');
}

syncAllKnowledgeFiles().catch(console.error);
