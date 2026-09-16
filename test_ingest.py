import sys, uuid, json
from pathlib import Path
sys.path.insert(0, 'backend')
from app.core.config import settings
from app.database.session import db_run, db_get
from app.processing.processors import process_document

test_txt = settings.resolved_upload_dir / 'sample_doc.txt'
test_txt.write_text('Antigravity Smart Finder Search Engine.\nThis document demonstrates advanced multimodal retrieval with Qwen3 embeddings and FAISS index.\nEach chunk is stored in SQLite and indexed in FAISS vector database.', encoding='utf-8')

sid = str(uuid.uuid4())
db_run(
    'INSERT INTO knowledge_sources (id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
    (sid, 'sample_doc.txt', 'sample_doc.txt', 'txt', str(test_txt), test_txt.stat().st_size, 'system', 'uploaded')
)

print('--- STARTING INGESTION ---')
process_document(sid)
print('--- INGESTION FINISHED ---')

src = db_get('SELECT id, metadata_json, processing_status FROM knowledge_sources WHERE id = ?', (sid,))
meta = json.loads(src['metadata_json'])
pinfo = meta.get('processing_info', {})
print('\n[Captured Processing Info]')
print('Processing Time:', pinfo.get('processing_time_seconds'))
print('Methods:', pinfo.get('methods_used'))
print('Models:', pinfo.get('models_used'))
print('Counts:', pinfo.get('counts'))
print('Storage:', pinfo.get('storage_info'))
print('Log Count:', len(pinfo.get('logs', [])))
for l in pinfo.get('logs', []):
    print(f"  {l['prefix']} {l['message']}")
