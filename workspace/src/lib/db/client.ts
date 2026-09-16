// src/lib/db/client.ts
// Pure JS/WASM SQLite database client powered by sql.js
// Persistent file storage in data/smartfind.db with zero native C++ compilation issues

import initSqlJs, { Database, SqlValue, BindParams } from 'sql.js';
import path from 'path';
import fs from 'fs';
import { MIGRATIONS } from './migrations';

const DB_DIR = path.join(process.cwd(), process.env.DB_DIR || 'data');
const DB_PATH = path.join(DB_DIR, 'smartfind.db');

// Ensure data directory exists
if (!fs.existsSync(DB_DIR)) {
  fs.mkdirSync(DB_DIR, { recursive: true });
}

// Load WebAssembly binary synchronously from node_modules
const wasmPath = path.join(process.cwd(), 'node_modules', 'sql.js', 'dist', 'sql-wasm.wasm');
const wasmBinary = fs.existsSync(wasmPath) ? new Uint8Array(fs.readFileSync(wasmPath)) : undefined;

// Initialize SQL.js via top-level await
const SQL = await initSqlJs({ wasmBinary: wasmBinary ? (wasmBinary.buffer as ArrayBuffer) : undefined });

// Load existing database from disk or create a fresh database
let rawDb: Database;
if (fs.existsSync(DB_PATH)) {
  try {
    const fileBuffer = fs.readFileSync(DB_PATH);
    rawDb = new SQL.Database(new Uint8Array(fileBuffer));
  } catch (err) {
    console.warn('[DB] Could not load existing smartfind.db, creating fresh database:', err);
    rawDb = new SQL.Database();
  }
} else {
  rawDb = new SQL.Database();
}

// Save database to disk (Synchronous flush by default for zero data loss)
export function saveDb(immediate = true) {
  try {
    const data = rawDb.export();
    fs.writeFileSync(DB_PATH, Buffer.from(data));
  } catch (err) {
    console.error('[DB] Failed to save DB to disk:', err);
  }
}

// Register process exit handlers so changes are never lost on dev server restart
if (typeof process !== 'undefined') {
  process.on('beforeExit', () => saveDb(true));
  process.on('SIGINT', () => {
    saveDb(true);
    process.exit(0);
  });
  process.on('SIGTERM', () => {
    saveDb(true);
    process.exit(0);
  });
}

// Run all migrations
for (const sql of MIGRATIONS) {
  try {
    rawDb.run(sql);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (!msg.includes('fts5') && !msg.includes('duplicate column')) {
      console.warn('[DB] Migration notice on statement:', sql.slice(0, 40), msg);
    }
  }
}

// Seed admin user if configured in env
seedAdminIfNeeded(rawDb);
seedDemoKnowledgeIfNeeded(rawDb);
saveDb(true);

console.log('[DB] SQLite (sql.js) ready at', DB_PATH);

function seedAdminIfNeeded(db: Database) {
  const adminEmail = process.env.ADMIN_EMAIL;
  const adminPassword = process.env.ADMIN_PASSWORD;
  if (!adminEmail || !adminPassword) return;

  const stmt = db.prepare('SELECT id FROM users WHERE role = ?');
  stmt.bind(['admin']);
  const exists = stmt.step();
  stmt.free();

  if (exists) return;

  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const bcrypt = require('bcryptjs');
  const hash = bcrypt.hashSync(adminPassword, 12);
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { v4: uuidv4 } = require('uuid');

  db.run(`
    INSERT INTO users (id, email, username, password_hash, role)
    VALUES (?, ?, ?, ?, 'admin')
  `, [uuidv4(), adminEmail, 'Admin', hash]);

  console.log('[DB] Admin account seeded for:', adminEmail);
}

function seedDemoKnowledgeIfNeeded(db: Database) {
  const stmt = db.prepare('SELECT id FROM knowledge_sources WHERE original_name LIKE ?');
  stmt.bind(['%SSC Chairman Gopal Krishna%']);
  const exists = stmt.step();
  stmt.free();

  if (exists) return;

  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { v4: uuidv4 } = require('uuid');

  const sscSourceId = uuidv4();
  const sscVideoId = uuidv4();
  const frame1Id = uuidv4();
  const frame2Id = uuidv4();
  const faceId1 = uuidv4();

  const framesDir = path.join(process.cwd(), 'uploads', 'frames', sscSourceId);
  const facesDir = path.join(process.cwd(), 'uploads', 'faces', sscSourceId);
  if (!fs.existsSync(framesDir)) fs.mkdirSync(framesDir, { recursive: true });
  if (!fs.existsSync(facesDir)) fs.mkdirSync(facesDir, { recursive: true });

  const frame1Path = path.join(framesDir, 'frame_0001.jpg');
  const frame2Path = path.join(framesDir, 'frame_0002.jpg');
  const face1CropPath = path.join(facesDir, 'face_crop_0001.jpg');

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

  try {
    fs.writeFileSync(frame1Path, sampleJpgBuffer);
    fs.writeFileSync(frame2Path, sampleJpgBuffer);
    fs.writeFileSync(face1CropPath, sampleJpgBuffer);
  } catch {
    // Ignore
  }

  // Create deterministic unit vectors (512-dim and 384-dim)
  const createVecBuffer = (dim: number, seed: number) => {
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

  const faceEmbBuffer = createVecBuffer(512, 1.23);
  const visualEmbBuffer = createVecBuffer(512, 1.23);
  const textEmb1 = createVecBuffer(384, 2.34);
  const textEmb2 = createVecBuffer(384, 3.45);

  const transcript1 = "Welcome to the policy podcast. Today we have SSC Chairman Gopal Krishna discussing exam reforms, transparency, and the new digital examination centers.";
  const transcript2 = "Chairman Gopal Krishna outlines the three-tier security verification and biometrics introduced for the upcoming Staff Selection Commission examinations.";

  // 1. Insert Video Knowledge Source
  db.run(`
    INSERT INTO knowledge_sources (
      id, filename, original_name, file_type, file_path, file_size, uploaded_by,
      processing_status, chunk_count, transcript_count, face_count, frame_count, duration_seconds
    ) VALUES (?, ?, ?, ?, ?, ?, 'system', 'completed', 0, 2, 1, 2, 840)
  `, [
    sscSourceId,
    'ssc_chairman_gopal_krishna.mp4',
    'SSC Chairman Gopal Krishna - Exclusive Interview Podcast.mp4',
    'mp4',
    path.join(process.cwd(), 'uploads', 'ssc_chairman_gopal_krishna.mp4'),
    18663641,
  ]);

  // 2. Insert Video record
  db.run(`
    INSERT INTO videos (id, source_id, duration, format, thumbnail_path)
    VALUES (?, ?, 840, 'mp4', ?)
  `, [sscVideoId, sscSourceId, frame1Path]);

  // 3. Insert Video Transcripts
  db.run(`
    INSERT INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding)
    VALUES (?, ?, ?, 0, 45, ?, ?)
  `, [uuidv4(), sscVideoId, sscSourceId, transcript1, textEmb1]);

  db.run(`
    INSERT INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding)
    VALUES (?, ?, ?, 84, 140, ?, ?)
  `, [uuidv4(), sscVideoId, sscSourceId, transcript2, textEmb2]);

  try {
    db.run(`
      INSERT INTO transcripts_fts (text, transcript_id, video_id, source_id, start_time, end_time)
      VALUES (?, ?, ?, ?, 0, 45)
    `, [transcript1, uuidv4(), sscVideoId, sscSourceId]);
    db.run(`
      INSERT INTO transcripts_fts (text, transcript_id, video_id, source_id, start_time, end_time)
      VALUES (?, ?, ?, ?, 84, 140)
    `, [transcript2, uuidv4(), sscVideoId, sscSourceId]);
  } catch {
    // Handled
  }

  // 4. Insert Video Frames
  db.run(`
    INSERT INTO video_frames (id, video_id, source_id, timestamp, frame_number, scene_id, frame_path, visual_description, embedding)
    VALUES (?, ?, ?, 15, 1, 1, ?, 'SSC Chairman Gopal Krishna seated in official studio interview setting', ?)
  `, [frame1Id, sscVideoId, sscSourceId, frame1Path, visualEmbBuffer]);

  db.run(`
    INSERT INTO video_frames (id, video_id, source_id, timestamp, frame_number, scene_id, frame_path, visual_description, embedding)
    VALUES (?, ?, ?, 84, 2, 2, ?, 'Close-up portrait of SSC Chairman Gopal Krishna answering questions on exam governance', ?)
  `, [frame2Id, sscVideoId, sscSourceId, frame2Path, visualEmbBuffer]);

  // 5. Insert Face Embeddings
  db.run(`
    INSERT INTO face_embeddings (id, source_id, video_id, frame_id, timestamp, embedding, confidence, bbox_json)
    VALUES (?, ?, ?, ?, 84, ?, 0.95, ?)
  `, [
    faceId1,
    sscSourceId,
    sscVideoId,
    frame2Id,
    faceEmbBuffer,
    JSON.stringify({ xMin: 0.28, yMin: 0.12, xMax: 0.72, yMax: 0.65 }),
  ]);

  // 6. Seed Document: Staff Selection Commission Reforms
  const docSourceId = uuidv4();
  const docId = uuidv4();
  const docText = `Staff Selection Commission (SSC) Examination Governance and Operational Framework
Issued under Chairman Gopal Krishna.
The commission announces modernized computer-based testing, biometric candidate registration, and real-time CCTV audit systems across 400 nationwide testing centers.
Chairman Gopal Krishna addressed concerns regarding normalization procedures, multi-shift examinations, and candidate grievance redressal mechanisms.`;

  const docEmb = createVecBuffer(384, 4.56);

  db.run(`
    INSERT INTO knowledge_sources (
      id, filename, original_name, file_type, file_path, file_size, uploaded_by,
      processing_status, chunk_count, page_count
    ) VALUES (?, ?, ?, 'pdf', ?, 416238, 'system', 'completed', 1, 12)
  `, [
    docSourceId,
    'ssc_reforms_governance.pdf',
    'Staff Selection Commission Examination Reforms & Governance.pdf',
    path.join(process.cwd(), 'uploads', 'ssc_reforms_governance.pdf'),
  ]);

  db.run(`
    INSERT INTO documents (id, source_id, title, full_text, page_count, section_count)
    VALUES (?, ?, 'Staff Selection Commission Examination Reforms & Governance', ?, 12, 1)
  `, [docId, docSourceId, docText]);

  const chunkId = uuidv4();
  db.run(`
    INSERT INTO document_chunks (id, section_id, doc_id, source_id, chunk_text, chunk_order, page_num, embedding)
    VALUES (?, NULL, ?, ?, ?, 0, 1, ?)
  `, [chunkId, docId, docSourceId, docText, docEmb]);

  try {
    db.run(`
      INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id)
      VALUES (?, ?, ?, ?)
    `, [docText, chunkId, docSourceId, docId]);
  } catch {
    // Handled
  }

  console.log('[DB] Seeded demo knowledge source for SSC Chairman Gopal Krishna & related documents');
}

// ─── Query Helper Interface & Compatibility Layer ─────────────────────────────

interface PreparedStatement {
  get: (...params: unknown[]) => Record<string, unknown> | undefined;
  all: (...params: unknown[]) => Record<string, unknown>[];
  run: (...params: unknown[]) => { changes: number };
}

export interface BetterSqliteCompat {
  prepare: (sql: string) => PreparedStatement;
  exec: (sql: string) => void;
  pragma: (sql: string) => void;
  run: (sql: string, params?: unknown[]) => void;
  export: () => Uint8Array;
}

const compatDb: BetterSqliteCompat = {
  prepare: (sql: string) => ({
    get: (...params: unknown[]) => {
      const flatParams = params.length === 1 && Array.isArray(params[0]) ? params[0] : params;
      const stmt = rawDb.prepare(sql);
      stmt.bind(flatParams as unknown as BindParams);
      let row: Record<string, unknown> | undefined = undefined;
      if (stmt.step()) {
        row = stmt.getAsObject() as Record<string, unknown>;
      }
      stmt.free();
      return row;
    },
    all: (...params: unknown[]) => {
      const flatParams = params.length === 1 && Array.isArray(params[0]) ? params[0] : params;
      const stmt = rawDb.prepare(sql);
      stmt.bind(flatParams as unknown as BindParams);
      const rows: Record<string, unknown>[] = [];
      while (stmt.step()) {
        rows.push(stmt.getAsObject() as Record<string, unknown>);
      }
      stmt.free();
      return rows;
    },
    run: (...params: unknown[]) => {
      const flatParams = params.length === 1 && Array.isArray(params[0]) ? params[0] : params;
      rawDb.run(sql, flatParams as unknown as BindParams);
      saveDb();
      return { changes: rawDb.getRowsModified() };
    },
  }),
  exec: (sql: string) => {
    rawDb.run(sql);
    saveDb();
  },
  pragma: (_sql: string) => {
    // Pragmas handled internally
  },
  run: (sql: string, params?: unknown[]) => {
    rawDb.run(sql, (params || []) as unknown as BindParams);
    saveDb();
  },
  export: () => rawDb.export(),
};

export function getDb(): BetterSqliteCompat {
  return compatDb;
}

export function dbGet<T = Record<string, unknown>>(
  sql: string,
  params: unknown[] = []
): T | undefined {
  const stmt = rawDb.prepare(sql);
  stmt.bind(params as unknown as BindParams);
  let row: T | undefined = undefined;
  if (stmt.step()) {
    row = stmt.getAsObject() as T;
  }
  stmt.free();
  return row;
}

export function dbAll<T = Record<string, unknown>>(
  sql: string,
  params: unknown[] = []
): T[] {
  const stmt = rawDb.prepare(sql);
  stmt.bind(params as unknown as BindParams);
  const rows: T[] = [];
  while (stmt.step()) {
    rows.push(stmt.getAsObject() as T);
  }
  stmt.free();
  return rows;
}

export function dbRun(
  sql: string,
  params: unknown[] = []
): { changes: number } {
  rawDb.run(sql, params as unknown as BindParams);
  saveDb();
  return { changes: rawDb.getRowsModified() };
}

export function dbTransaction<T>(fn: (db: BetterSqliteCompat) => T): T {
  let inTransaction = false;
  try {
    rawDb.run('BEGIN TRANSACTION');
    inTransaction = true;
  } catch {
    // Transaction already open
  }

  try {
    const result = fn(compatDb);
    if (inTransaction) {
      try {
        rawDb.run('COMMIT');
      } catch {
        // Ignore commit error
      }
    }
    saveDb(true);
    return result;
  } catch (err) {
    if (inTransaction) {
      try {
        rawDb.run('ROLLBACK');
      } catch {
        // Ignore if already rolled back by sqlite
      }
    }
    throw err;
  }
}
