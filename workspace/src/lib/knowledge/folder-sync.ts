// src/lib/knowledge/folder-sync.ts
// Automatic Knowledge Base Folder Ingestion & Sync Engine
// Automatically scans the `knowledge_base` folder on server start & on demand,
// ensuring all reference materials (PDF, DOCX, Video, Audio, Image) are permanently preserved and indexed in SQLite.

import fs from 'fs';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import { dbGet, dbAll, dbRun, saveDb, dbTransaction } from '@/lib/db/client';
import { processDocument } from './document-processor';
import { processImage } from './image-processor';
import { processVideo } from './video-processor';
import { processAudio } from './audio-processor';

export const KB_DIR = path.join(process.cwd(), 'knowledge_base');
export const UPLOAD_DIR = path.join(process.cwd(), 'uploads');

const SUPPORTED_EXTENSIONS = new Set([
  // Documents
  'pdf', 'docx', 'doc', 'txt', 'md', 'markdown', 'csv', 'xlsx', 'xls', 'json', 'xml', 'html', 'pptx',
  // Images
  'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp',
  // Videos
  'mp4', 'avi', 'mov', 'mkv', 'webm',
  // Audio
  'mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac',
]);

let isSyncing = false;

/**
 * Ensures the `knowledge_base` and `uploads` directories exist.
 */
export function ensureKnowledgeFoldersExist() {
  if (!fs.existsSync(KB_DIR)) {
    fs.mkdirSync(KB_DIR, { recursive: true });
  }
  if (!fs.existsSync(UPLOAD_DIR)) {
    fs.mkdirSync(UPLOAD_DIR, { recursive: true });
  }
}

/**
 * Automatically scans the `knowledge_base/` folder and indexes any new or changed files into SQLite.
 */
export async function syncKnowledgeFolder(): Promise<{
  totalFiles: number;
  newlyIndexed: number;
  alreadyIndexed: number;
  errors: number;
  syncedFiles: string[];
}> {
  ensureKnowledgeFoldersExist();

  if (isSyncing) {
    console.log('[FolderSync] Sync already in progress, skipping concurrent run.');
    return { totalFiles: 0, newlyIndexed: 0, alreadyIndexed: 0, errors: 0, syncedFiles: [] };
  }

  isSyncing = true;
  console.log('[FolderSync] Starting knowledge_base folder scan at:', KB_DIR);

  let newlyIndexed = 0;
  let alreadyIndexed = 0;
  let errors = 0;
  const syncedFiles: string[] = [];

  try {
    const files = fs.readdirSync(KB_DIR);
    const validFiles = files.filter((f) => {
      const ext = path.extname(f).slice(1).toLowerCase();
      const stat = fs.statSync(path.join(KB_DIR, f));
      return stat.isFile() && SUPPORTED_EXTENSIONS.has(ext);
    });

    // Get system/admin user ID
    const adminUser = dbGet<{ id: string }>('SELECT id FROM users LIMIT 1');
    const uploaderId = adminUser?.id || 'admin-system';

    for (const fileName of validFiles) {
      const filePath = path.join(KB_DIR, fileName);
      const stat = fs.statSync(filePath);
      const ext = path.extname(fileName).slice(1).toLowerCase();

      // Check if already indexed in database with completed status
      const existing = dbGet<{
        id: string;
        processing_status: string;
        chunk_count: number;
        transcript_count: number;
        face_count: number;
        file_size: number;
      }>('SELECT id, processing_status, chunk_count, transcript_count, face_count, file_size FROM knowledge_sources WHERE original_name = ?', [fileName]);

      const isFullyProcessed =
        existing &&
        existing.processing_status === 'completed' &&
        (existing.chunk_count > 0 || existing.transcript_count > 0 || existing.face_count > 0 || ['jpg', 'png', 'jpeg', 'webp'].includes(ext));

      if (isFullyProcessed) {
        alreadyIndexed++;
        syncedFiles.push(fileName);
        continue;
      }

      console.log(`[FolderSync] Indexing new knowledge asset: "${fileName}" (${(stat.size / 1024).toFixed(1)} KB)...`);

      const sourceId = existing ? existing.id : uuidv4();
      const safeFilename = `${sourceId}.${ext}`;
      const destUploadPath = path.join(UPLOAD_DIR, safeFilename);

      // Copy to uploads folder for web streaming/viewing
      try {
        if (!fs.existsSync(destUploadPath) || fs.statSync(destUploadPath).size !== stat.size) {
          fs.copyFileSync(filePath, destUploadPath);
        }
      } catch (err) {
        console.warn(`[FolderSync] Notice copying to uploads:`, err);
      }

      if (!existing) {
        dbRun(`
          INSERT INTO knowledge_sources (
            id, filename, original_name, file_type, file_path, file_size, uploaded_by, processing_status
          ) VALUES (?, ?, ?, ?, ?, ?, ?, 'indexing')
        `, [sourceId, safeFilename, fileName, ext, destUploadPath, stat.size, uploaderId]);
      } else {
        dbRun('UPDATE knowledge_sources SET processing_status = ? WHERE id = ?', ['indexing', sourceId]);
      }

      saveDb(true);

      // Process and index based on media type
      try {
        const isDocument = ['pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx', 'xls', 'json', 'xml', 'html', 'markdown', 'pptx'].includes(ext);
        const isImage = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'].includes(ext);
        const isVideo = ['mp4', 'avi', 'mov', 'mkv', 'webm'].includes(ext);
        const isAudio = ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac'].includes(ext);

        if (isDocument) {
          await processDocument(sourceId, destUploadPath, ext, fileName);
        } else if (isImage) {
          await processImage(sourceId, destUploadPath, ext, fileName);
        } else if (isVideo) {
          await processVideo(sourceId, destUploadPath, ext, fileName);
        } else if (isAudio) {
          await processAudio(sourceId, destUploadPath, ext, fileName);
        }

        dbRun("UPDATE knowledge_sources SET processing_status = 'completed' WHERE id = ?", [sourceId]);
        saveDb(true);
        newlyIndexed++;
        syncedFiles.push(fileName);
        console.log(`[FolderSync] Successfully indexed: "${fileName}"`);
      } catch (err) {
        errors++;
        const msg = err instanceof Error ? err.message : String(err);
        console.error(`[FolderSync] Error indexing "${fileName}":`, err);
        dbRun("UPDATE knowledge_sources SET processing_status = 'failed', error_message = ? WHERE id = ?", [msg, sourceId]);
        saveDb(true);
      }
    }

    console.log(`[FolderSync] Sync complete. Total: ${validFiles.length} files (New: ${newlyIndexed}, Already Indexed: ${alreadyIndexed}, Errors: ${errors})`);
    return {
      totalFiles: validFiles.length,
      newlyIndexed,
      alreadyIndexed,
      errors,
      syncedFiles,
    };
  } finally {
    isSyncing = false;
  }
}
