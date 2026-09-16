// scripts/reset-knowledge-base.js — Clears all derived Smart Finder indexes and embeddings
const initSqlJs = require('sql.js');
const fs = require('fs');
const path = require('path');

async function resetKnowledgeBase() {
  console.log('═══════════════════════════════════════════════════════════════');
  console.log('🧹 RESETTING SMART FINDER KNOWLEDGE BASE & DERIVED INDEXES');
  console.log('═══════════════════════════════════════════════════════════════');

  const dbPath = path.join(__dirname, '..', 'data', 'smartfind.db');
  if (!fs.existsSync(dbPath)) {
    console.log('Database not found, nothing to reset.');
    return;
  }

  const SQL = await initSqlJs();
  const db = new SQL.Database(fs.readFileSync(dbPath));

  // 1. Delete all derived records from SQLite
  console.log('\n1. Clearing SQLite tables...');
  const tables = [
    'face_embeddings',
    'video_frames',
    'video_transcripts',
    'transcripts_fts',
    'videos',
    'chunks_fts',
    'document_chunks',
    'document_sections',
    'documents',
    'knowledge_sources',
  ];

  for (const table of tables) {
    try {
      db.run(`DELETE FROM ${table};`);
      console.log(`   ✓ Cleared table: ${table}`);
    } catch (err) {
      console.log(`   - Notice clearing ${table}:`, err.message);
    }
  }

  try {
    db.run('VACUUM;');
    console.log('   ✓ Database vacuumed successfully');
  } catch {}

  // Write cleared database to disk
  fs.writeFileSync(dbPath, Buffer.from(db.export()));
  console.log('   ✓ Saved clean database to data/smartfind.db');

  // 2. Clear derived file artifacts in uploads/frames, uploads/faces, uploads/temp, data/.cache
  console.log('\n2. Cleaning derived file caches and artifacts...');
  const dirsToClean = [
    path.join(__dirname, '..', 'uploads', 'frames'),
    path.join(__dirname, '..', 'uploads', 'faces'),
    path.join(__dirname, '..', 'uploads', 'temp'),
    path.join(__dirname, '..', 'data', '.cache'),
  ];

  for (const dir of dirsToClean) {
    if (fs.existsSync(dir)) {
      try {
        const files = fs.readdirSync(dir);
        for (const file of files) {
          const fp = path.join(dir, file);
          try {
            if (fs.lstatSync(fp).isDirectory()) {
              fs.rmSync(fp, { recursive: true, force: true });
            } else {
              fs.unlinkSync(fp);
            }
          } catch {}
        }
        console.log(`   ✓ Cleaned directory: ${path.relative(path.join(__dirname, '..'), dir)} (${files.length} items removed)`);
      } catch (err) {
        console.warn(`   - Notice cleaning ${dir}:`, err.message);
      }
    }
  }

  // Verify
  const verifyDb = new SQL.Database(fs.readFileSync(dbPath));
  const counts = {
    sources: verifyDb.exec('SELECT COUNT(*) FROM knowledge_sources')[0]?.values?.[0]?.[0] || 0,
    documents: verifyDb.exec('SELECT COUNT(*) FROM documents')[0]?.values?.[0]?.[0] || 0,
    chunks: verifyDb.exec('SELECT COUNT(*) FROM document_chunks')[0]?.values?.[0]?.[0] || 0,
    videos: verifyDb.exec('SELECT COUNT(*) FROM videos')[0]?.values?.[0]?.[0] || 0,
    transcripts: verifyDb.exec('SELECT COUNT(*) FROM video_transcripts')[0]?.values?.[0]?.[0] || 0,
    frames: verifyDb.exec('SELECT COUNT(*) FROM video_frames')[0]?.values?.[0]?.[0] || 0,
    faces: verifyDb.exec('SELECT COUNT(*) FROM face_embeddings')[0]?.values?.[0]?.[0] || 0,
  };

  console.log('\n3. Verification of Clean State:');
  console.log('   - knowledge_sources count:', counts.sources);
  console.log('   - documents count:        ', counts.documents);
  console.log('   - document_chunks count:  ', counts.chunks);
  console.log('   - videos count:           ', counts.videos);
  console.log('   - video_transcripts count:', counts.transcripts);
  console.log('   - video_frames count:     ', counts.frames);
  console.log('   - face_embeddings count:  ', counts.faces);

  const isClean = Object.values(counts).every((c) => c === 0);
  if (isClean) {
    console.log('\n🎉 KNOWLEDGE BASE IS COMPLETELY CLEAN AND READY FOR FRESH UPLOADS!');
  } else {
    console.warn('\n⚠️ Some tables still contain records.');
  }
}

resetKnowledgeBase().catch(console.error);
