// scripts/test-folder-sync.js — Tests folder sync functionality
const initSqlJs = require('sql.js');
const fs = require('fs');
const path = require('path');

async function testSync() {
  console.log('Testing Knowledge Base Folder Sync...');
  const kbDir = path.join(__dirname, '..', 'knowledge_base');
  const files = fs.readdirSync(kbDir);
  console.log(`Found ${files.length} files in knowledge_base directory:`);
  for (const f of files) {
    const sz = fs.statSync(path.join(kbDir, f)).size;
    console.log(` - ${f} (${(sz / 1024).toFixed(1)} KB)`);
  }

  const SQL = await initSqlJs();
  const dbPath = path.join(__dirname, '..', 'data', 'smartfind.db');
  const db = new SQL.Database(fs.readFileSync(dbPath));

  const countRes = db.exec('SELECT COUNT(*) as count FROM knowledge_sources');
  console.log('\nCurrent knowledge_sources in smartfind.db:', countRes[0]?.values?.[0]?.[0]);

  const sourcesRes = db.exec('SELECT id, original_name, file_type, processing_status, chunk_count, transcript_count, face_count FROM knowledge_sources');
  console.log('\nIndexed items:');
  for (const row of (sourcesRes[0]?.values || [])) {
    console.log(`  [${row[3]}] ${row[1]} (${row[2]}) — Chunks: ${row[4]}, Transcripts: ${row[5]}, Faces: ${row[6]}`);
  }
}

testSync().catch(console.error);
