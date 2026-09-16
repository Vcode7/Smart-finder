// src/lib/knowledge/ingestion-pipeline.ts
// Background job queue for file processing — updates status as pipeline progresses

import { dbRun, dbGet } from '@/lib/db/client';
import { processDocument } from './document-processor';
import { processImage } from './image-processor';
import { processVideo } from './video-processor';
import { processAudio } from './audio-processor';
import path from 'path';

type JobStatus = 'pending' | 'running' | 'done' | 'failed';

interface Job {
  sourceId: string;
  filePath: string;
  fileType: string;
  originalName: string;
  mimeType: string;
  status: JobStatus;
}

// In-memory queue
const jobQueue: Job[] = [];
let isProcessing = false;

export function enqueueFile(job: Omit<Job, 'status'>) {
  jobQueue.push({ ...job, status: 'pending' });
  processNext();
}

async function processNext() {
  if (isProcessing || jobQueue.length === 0) return;

  const job = jobQueue.find((j) => j.status === 'pending');
  if (!job) return;

  isProcessing = true;
  job.status = 'running';

  try {
    updateStatus(job.sourceId, 'processing');

    const ext = job.fileType.toLowerCase();
    const isDocument = ['pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx', 'xls', 'json', 'xml', 'html', 'markdown', 'pptx'].includes(ext);
    const isImage = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'].includes(ext);
    const isVideo = ['mp4', 'avi', 'mov', 'mkv', 'webm'].includes(ext);
    const isAudio = ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac'].includes(ext);

    updateStatus(job.sourceId, 'indexing');

    if (isDocument) {
      await processDocument(job.sourceId, job.filePath, ext, job.originalName);
    } else if (isImage) {
      await processImage(job.sourceId, job.filePath, ext, job.originalName);
    } else if (isVideo) {
      await processVideo(job.sourceId, job.filePath, ext, job.originalName);
    } else if (isAudio) {
      await processAudio(job.sourceId, job.filePath, ext, job.originalName);
    } else {
      updateStatus(job.sourceId, 'completed');
    }

    job.status = 'done';
    updateStatus(job.sourceId, 'completed');
    console.log(`[Pipeline] Completed: ${job.originalName}`);
  } catch (err) {
    job.status = 'failed';
    const errorMsg = err instanceof Error ? err.message : 'Unknown error';
    dbRun(
      "UPDATE knowledge_sources SET processing_status = 'failed', error_message = ? WHERE id = ?",
      [errorMsg, job.sourceId]
    );
    console.error(`[Pipeline] Failed: ${job.originalName}`, err);
  } finally {
    isProcessing = false;
    setImmediate(processNext);
  }
}

function updateStatus(sourceId: string, status: string) {
  dbRun("UPDATE knowledge_sources SET processing_status = ? WHERE id = ?", [status, sourceId]);
}

/** Get queue status for admin UI */
export function getQueueStatus() {
  return {
    pending: jobQueue.filter((j) => j.status === 'pending').length,
    running: jobQueue.filter((j) => j.status === 'running').length,
    done: jobQueue.filter((j) => j.status === 'done').length,
    failed: jobQueue.filter((j) => j.status === 'failed').length,
  };
}
