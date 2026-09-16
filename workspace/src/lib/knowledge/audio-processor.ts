// src/lib/knowledge/audio-processor.ts
// Processes standalone audio files (.mp3, .wav, .m4a, .ogg, .flac, .aac)
// Transcribes speech with Groq Whisper, generates chunk embeddings, and indexes in SQLite

import path from 'path';
import fs from 'fs';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { v4 as uuidv4 } from 'uuid';
import { dbTransaction } from '@/lib/db/client';
import { getTextEmbedding, floatArrayToBuffer } from '@/lib/embeddings/multimodal-embeddings';
import Groq from 'groq-sdk';

const execFileAsync = promisify(execFile);
const groq = new Groq({ apiKey: process.env.GROQ_API_KEY || '' });

export interface ProcessedAudio {
  audioId: string;
  sourceId: string;
  duration?: number;
  format: string;
  transcriptCount: number;
  transcripts: Array<{
    id: string;
    startTime: number;
    endTime: number;
    text: string;
  }>;
}

/**
 * Gets audio duration using ffprobe
 */
async function getAudioDuration(filePath: string): Promise<number> {
  try {
    const { stdout } = await execFileAsync('ffprobe', [
      '-v', 'error',
      '-show_entries', 'format=duration',
      '-of', 'default=noprint_wrappers=1:nokey=1',
      filePath,
    ]);
    const duration = parseFloat(stdout.trim());
    return isNaN(duration) ? 0 : duration;
  } catch (err) {
    console.warn('[AudioProcessor] ffprobe duration check warning:', err);
    return 0;
  }
}

import os from 'os';

/**
 * Transcribes audio file using Groq Whisper API (with automatic chunking for >24MB files)
 */
async function transcribeWithGroq(filePath: string): Promise<Array<{ startTime: number; endTime: number; text: string }>> {
  if (!process.env.GROQ_API_KEY) {
    console.warn('[AudioProcessor] No GROQ_API_KEY found, skipping Whisper transcription');
    return [];
  }

  if (!fs.existsSync(filePath)) return [];

  const stat = fs.statSync(filePath);
  const MAX_GROQ_PAYLOAD = 24 * 1024 * 1024; // 24 MB

  if (stat.size > MAX_GROQ_PAYLOAD) {
    console.log(`[AudioProcessor] Audio is ${(stat.size / 1024 / 1024).toFixed(1)}MB, splitting into 10-minute chunks for Whisper...`);
    const duration = await getAudioDuration(filePath);
    const chunkDuration = 600; // 10 minutes
    const chunks = Math.ceil(duration / chunkDuration);
    const allSegments: Array<{ startTime: number; endTime: number; text: string }> = [];

    for (let c = 0; c < chunks; c++) {
      const startTimeOffset = c * chunkDuration;
      const chunkPath = path.join(os.tmpdir(), `smartfind_audio_chunk_${uuidv4()}.mp3`);
      try {
        await execFileAsync('ffmpeg', [
          '-y',
          '-ss', String(startTimeOffset),
          '-i', filePath,
          '-t', String(chunkDuration),
          '-acodec', 'copy',
          chunkPath,
        ]);

        if (fs.existsSync(chunkPath) && fs.statSync(chunkPath).size > 0) {
          const chunkSegments = await transcribeSingleAudio(chunkPath);
          for (const seg of chunkSegments) {
            allSegments.push({
              startTime: Number((seg.startTime + startTimeOffset).toFixed(2)),
              endTime: Number((seg.endTime + startTimeOffset).toFixed(2)),
              text: seg.text,
            });
          }
        }
      } catch (chunkErr) {
        console.warn(`[AudioProcessor] Chunk ${c} transcription notice:`, chunkErr);
      } finally {
        if (fs.existsSync(chunkPath)) {
          try { fs.unlinkSync(chunkPath); } catch {}
        }
      }
    }
    return allSegments;
  }

  return transcribeSingleAudio(filePath);
}

/**
 * Transcribes a single audio file (<24MB) with Groq Whisper
 */
async function transcribeSingleAudio(filePath: string): Promise<Array<{ startTime: number; endTime: number; text: string }>> {
  try {
    const fileStream = fs.createReadStream(filePath);
    
    // Groq whisper transcription endpoint
    const response = await groq.audio.transcriptions.create({
      file: fileStream,
      model: 'whisper-large-v3',
      response_format: 'verbose_json',
      temperature: 0.0,
    });

    const segments: Array<{ startTime: number; endTime: number; text: string }> = [];

    if (response && 'segments' in response && Array.isArray((response as { segments?: Array<{ start: number; end: number; text: string }> }).segments)) {
      const rawSegments = (response as { segments: Array<{ start: number; end: number; text: string }> }).segments;
      for (const seg of rawSegments) {
        if (seg.text && seg.text.trim().length > 0) {
          segments.push({
            startTime: Number((seg.start || 0).toFixed(2)),
            endTime: Number((seg.end || seg.start + 5).toFixed(2)),
            text: seg.text.trim(),
          });
        }
      }
    } else if (response && 'text' in response && response.text) {
      const sentences = response.text.match(/[^.!?]+[.!?]+/g) || [response.text];
      let currentTime = 0;
      for (const sentence of sentences) {
        const trimmed = sentence.trim();
        if (trimmed.length > 5) {
          const duration = Math.max(3, Math.min(15, Math.ceil(trimmed.length / 15)));
          segments.push({
            startTime: Number(currentTime.toFixed(2)),
            endTime: Number((currentTime + duration).toFixed(2)),
            text: trimmed,
          });
          currentTime += duration;
        }
      }
    }

    return segments;
  } catch (err) {
    console.error('[AudioProcessor] Whisper transcription error:', err instanceof Error ? err.message : err);
    return [];
  }
}

/**
 * Main audio processing function
 */
export async function processAudio(
  sourceId: string,
  filePath: string,
  fileType: string,
  originalName: string
): Promise<ProcessedAudio> {
  const audioId = uuidv4();
  const format = fileType.toLowerCase();

  console.log(`[AudioProcessor] Starting processing for audio: ${originalName} (${format})`);

  // 1. Get duration via ffprobe
  const ffprobeDuration = await getAudioDuration(filePath);

  // 2. Transcribe audio using Groq Whisper
  const transcriptSegments = await transcribeWithGroq(filePath);

  // 3. Compute text embeddings for each transcript segment
  const processedTranscripts: Array<{
    id: string;
    startTime: number;
    endTime: number;
    text: string;
    embeddingBuffer: Buffer | null;
  }> = [];

  for (const seg of transcriptSegments) {
    const transcriptId = uuidv4();
    let embeddingBuffer: Buffer | null = null;

    try {
      const vec = await getTextEmbedding(seg.text);
      if (vec && vec.length > 0) {
        embeddingBuffer = floatArrayToBuffer(vec);
      }
    } catch (e) {
      console.warn('[AudioProcessor] Transcript embedding failed for chunk:', e);
    }

    processedTranscripts.push({
      id: transcriptId,
      startTime: seg.startTime,
      endTime: seg.endTime,
      text: seg.text,
      embeddingBuffer,
    });
  }

  const duration = transcriptSegments.length > 0
    ? Math.max(ffprobeDuration, transcriptSegments[transcriptSegments.length - 1].endTime)
    : ffprobeDuration;

  // 4. Save into SQLite database in transaction
  dbTransaction((db) => {
    // Clear any previous records for this sourceId
    try {
      db.prepare('DELETE FROM videos WHERE source_id = ?').run(sourceId);
      db.prepare('DELETE FROM video_transcripts WHERE source_id = ?').run(sourceId);
      db.prepare('DELETE FROM transcripts_fts WHERE source_id = ?').run(sourceId);
    } catch {
      // Ignore
    }

    // Insert into videos table (shared media record)
    db.prepare(`
      INSERT OR REPLACE INTO videos (id, source_id, duration, format)
      VALUES (?, ?, ?, ?)
    `).run(audioId, sourceId, duration, format);

    for (const item of processedTranscripts) {
      // Insert into video_transcripts table with embedding BLOB
      db.prepare(`
        INSERT INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      `).run(item.id, audioId, sourceId, item.startTime, item.endTime, item.text, item.embeddingBuffer);

      // Insert into transcripts_fts table for full-text search
      try {
        db.prepare(`
          INSERT INTO transcripts_fts (text, transcript_id, video_id, source_id, start_time, end_time)
          VALUES (?, ?, ?, ?, ?, ?)
        `).run(item.text, item.id, audioId, sourceId, item.startTime, item.endTime);
      } catch {
        // Handled
      }
    }

    // Update knowledge_sources status and counts
    db.prepare(`
      UPDATE knowledge_sources
      SET processing_status = 'completed',
          transcript_count = ?,
          duration_seconds = ?
      WHERE id = ?
    `).run(processedTranscripts.length, duration, sourceId);
  });

  console.log(`[AudioProcessor] Successfully indexed ${processedTranscripts.length} transcript chunks for ${originalName}`);

  return {
    audioId,
    sourceId,
    duration,
    format,
    transcriptCount: processedTranscripts.length,
    transcripts: processedTranscripts.map((t) => ({
      id: t.id,
      startTime: t.startTime,
      endTime: t.endTime,
      text: t.text,
    })),
  };
}
