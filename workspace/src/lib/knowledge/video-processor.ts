// src/lib/knowledge/video-processor.ts
// Processes video files:
// 1. Audio Extraction & Groq Whisper timestamped transcript indexing with embeddings
// 2. Scene-Change & Periodic Keyframe Detection (10-20 frames initial fast indexing)
// 3. Multimodal CLIP Visual Embeddings for full frames
// 4. Face Detection, FFmpeg Face Cropping, and 512-dim Face Vector Embeddings

import path from 'path';
import fs from 'fs';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { v4 as uuidv4 } from 'uuid';
import { dbTransaction } from '@/lib/db/client';
import {
  getImageEmbedding,
  getTextEmbedding,
  floatArrayToBuffer,
} from '@/lib/embeddings/multimodal-embeddings';
import { detectFacesInImage, DetectedFace } from '@/lib/face/face-detector';
import Groq from 'groq-sdk';

const execFileAsync = promisify(execFile);
const groq = new Groq({ apiKey: process.env.GROQ_API_KEY || '' });

// Configurable frame sampling count for initial indexing & fast testing
export const DEFAULT_SAMPLE_FRAMES = 15;

export interface ProcessedVideo {
  videoId: string;
  sourceId: string;
  duration?: number;
  format: string;
  transcriptCount: number;
  frameCount: number;
  faceCount: number;
  transcripts: Array<{
    id: string;
    startTime: number;
    endTime: number;
    text: string;
  }>;
  frames: Array<{
    id: string;
    timestamp: number;
    frameNumber: number;
    sceneId: number;
    framePath: string;
    visualDescription?: string;
  }>;
  faces: Array<{
    id: string;
    frameId: string;
    timestamp: number;
    confidence: number;
    cropPath?: string;
  }>;
}

import os from 'os';

/**
 * Gets video duration using ffprobe
 */
async function getVideoDuration(filePath: string): Promise<number> {
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
    console.warn('[VideoProcessor] ffprobe duration error:', err);
    return 0;
  }
}

/**
 * Extracts audio track from video using ffmpeg to compact 32kbps mono mp3
 */
async function extractAudioTrack(videoPath: string, outputAudioPath: string): Promise<boolean> {
  try {
    await execFileAsync('ffmpeg', [
      '-y',
      '-i', videoPath,
      '-vn',
      '-ar', '16000',
      '-ac', '1',
      '-c:a', 'libmp3lame',
      '-b:a', '32k',
      outputAudioPath,
    ]);
    return fs.existsSync(outputAudioPath) && fs.statSync(outputAudioPath).size > 0;
  } catch (err) {
    console.warn('[VideoProcessor] ffmpeg audio extraction notice:', err instanceof Error ? err.message : err);
    return false;
  }
}

/**
 * Transcribes audio track using Groq Whisper API (with automatic chunking for >24MB files)
 */
async function transcribeWithGroq(filePath: string): Promise<Array<{ startTime: number; endTime: number; text: string }>> {
  if (!process.env.GROQ_API_KEY) {
    console.warn('[VideoProcessor] No GROQ_API_KEY found, skipping Whisper transcription');
    return [];
  }

  if (!fs.existsSync(filePath)) {
    return [];
  }

  const stat = fs.statSync(filePath);
  const MAX_GROQ_PAYLOAD = 24 * 1024 * 1024; // 24 MB safe threshold

  if (stat.size > MAX_GROQ_PAYLOAD) {
    // If it's a raw video file > 24MB, we cannot send it directly
    if (!filePath.endsWith('.mp3') && !filePath.endsWith('.wav') && !filePath.endsWith('.m4a')) {
      console.warn(`[VideoProcessor] File too large for direct Whisper (${(stat.size / 1024 / 1024).toFixed(1)}MB > 24MB) and not audio.`);
      return [];
    }

    // If audio is > 24MB, slice into 10-minute chunks
    console.log(`[VideoProcessor] Audio is ${(stat.size / 1024 / 1024).toFixed(1)}MB, splitting into 10-minute chunks for Whisper...`);
    const duration = await getVideoDuration(filePath);
    const chunkDuration = 600; // 10 minutes
    const chunks = Math.ceil(duration / chunkDuration);
    const allSegments: Array<{ startTime: number; endTime: number; text: string }> = [];

    for (let c = 0; c < chunks; c++) {
      const startTimeOffset = c * chunkDuration;
      const chunkPath = path.join(os.tmpdir(), `smartfind_whisper_chunk_${uuidv4()}.mp3`);
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
          const chunkSegments = await transcribeSingleAudioFile(chunkPath);
          for (const seg of chunkSegments) {
            allSegments.push({
              startTime: Number((seg.startTime + startTimeOffset).toFixed(2)),
              endTime: Number((seg.endTime + startTimeOffset).toFixed(2)),
              text: seg.text,
            });
          }
        }
      } catch (chunkErr) {
        console.warn(`[VideoProcessor] Chunk ${c} transcription notice:`, chunkErr);
      } finally {
        if (fs.existsSync(chunkPath)) {
          try { fs.unlinkSync(chunkPath); } catch {}
        }
      }
    }
    return allSegments;
  }

  return transcribeSingleAudioFile(filePath);
}

/**
 * Transcribes a single audio file (<24MB) with Groq Whisper
 */
async function transcribeSingleAudioFile(filePath: string): Promise<Array<{ startTime: number; endTime: number; text: string }>> {
  try {
    const fileStream = fs.createReadStream(filePath);
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
    console.error('[VideoProcessor] Whisper transcription error:', err instanceof Error ? err.message : err);
    return [];
  }
}

/**
 * Extracts keyframes using scene change detection and configurable target frame count (10-20 frames)
 */
async function extractKeyframes(
  videoPath: string,
  framesDir: string,
  videoDuration: number,
  targetFrameCount = DEFAULT_SAMPLE_FRAMES
): Promise<Array<{ frameNumber: number; sceneId: number; framePath: string; timestamp: number }>> {
  if (!fs.existsSync(framesDir)) {
    fs.mkdirSync(framesDir, { recursive: true });
  }

  const outputPattern = path.join(framesDir, 'frame_%04d.jpg');

  try {
    // 1. Scene detection filter: captures frames where scene change > 30%
    await execFileAsync('ffmpeg', [
      '-y',
      '-i', videoPath,
      '-vf', "select='gt(scene,0.30)+isnan(prev_selected_t)+gte(t-prev_selected_t,1.5)'",
      '-vsync', 'vfr',
      '-q:v', '2',
      outputPattern,
    ]);
  } catch (err) {
    console.warn('[VideoProcessor] Scene detection ffmpeg warning:', err);
  }

  // Check how many frames were extracted
  let frameFiles = fs.readdirSync(framesDir).filter((f) => f.startsWith('frame_') && f.endsWith('.jpg')).sort();

  // If scene detection yielded fewer than targetFrameCount frames, sample at regular intervals
  if (frameFiles.length < Math.min(targetFrameCount, 8) && videoDuration > 1) {
    console.log(`[VideoProcessor] Applying periodic frame sampling to ensure ~${targetFrameCount} sample frames...`);
    const interval = Math.max(1, videoDuration / targetFrameCount);
    try {
      await execFileAsync('ffmpeg', [
        '-y',
        '-i', videoPath,
        '-vf', `fps=1/${interval.toFixed(3)}`,
        '-q:v', '2',
        outputPattern,
      ]);
      frameFiles = fs.readdirSync(framesDir).filter((f) => f.startsWith('frame_') && f.endsWith('.jpg')).sort();
    } catch (fallbackErr) {
      console.warn('[VideoProcessor] Periodic frame sampling error:', fallbackErr);
    }
  }

  // Cap to target frame count if too many
  if (frameFiles.length > targetFrameCount * 2) {
    const step = Math.ceil(frameFiles.length / targetFrameCount);
    const selectedFiles: string[] = [];
    for (let i = 0; i < frameFiles.length; i += step) {
      selectedFiles.push(frameFiles[i]);
    }
    frameFiles = selectedFiles;
  }

  const result: Array<{ frameNumber: number; sceneId: number; framePath: string; timestamp: number }> = [];
  const totalFrames = frameFiles.length;

  for (let idx = 0; idx < totalFrames; idx++) {
    const filename = frameFiles[idx];
    const fullPath = path.join(framesDir, filename);

    // Approximate timestamp proportional to duration
    const timestamp = totalFrames > 1
      ? Number(((idx / (totalFrames - 1)) * Math.max(videoDuration - 0.5, 0.5)).toFixed(2))
      : 0;

    result.push({
      frameNumber: idx + 1,
      sceneId: idx + 1,
      framePath: fullPath,
      timestamp,
    });
  }

  return result;
}

/**
 * Main video processing function with Face-Based indexing and multimodal embeddings
 */
export async function processVideo(
  sourceId: string,
  filePath: string,
  fileType: string,
  originalName: string,
  sampleFrameCount = DEFAULT_SAMPLE_FRAMES
): Promise<ProcessedVideo> {
  const videoId = uuidv4();
  const format = fileType.toLowerCase();

  console.log(`[VideoProcessor] Starting processing for video: ${originalName} (${format})`);

  // 1. Get accurate video duration
  const videoDuration = await getVideoDuration(filePath);

  // 2. Extract audio track to temporary mp3 in OS temp directory (drive C: with ample space)
  const tempAudioPath = path.join(os.tmpdir(), `smartfind_audio_${sourceId}.mp3`);
  const audioExtracted = await extractAudioTrack(filePath, tempAudioPath);
  const audioFileToTranscribe = audioExtracted ? tempAudioPath : filePath;

  // 3. Transcribe audio using Groq Whisper (chunked if >24MB)
  let transcriptSegments: Array<{ startTime: number; endTime: number; text: string }> = [];
  try {
    transcriptSegments = await transcribeWithGroq(audioFileToTranscribe);
  } finally {
    if (fs.existsSync(tempAudioPath)) {
      try {
        fs.unlinkSync(tempAudioPath);
      } catch {
        // Ignore
      }
    }
  }

  // 4. Generate text embeddings for each transcript segment
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
      console.warn('[VideoProcessor] Transcript embedding failed for chunk:', e);
    }

    processedTranscripts.push({
      id: transcriptId,
      startTime: seg.startTime,
      endTime: seg.endTime,
      text: seg.text,
      embeddingBuffer,
    });
  }

  // 5. Extract scene-change keyframes (10-20 frames)
  const framesDir = path.join(process.cwd(), 'uploads', 'frames', sourceId);
  const extractedFrames = await extractKeyframes(filePath, framesDir, videoDuration, sampleFrameCount);

  // 6. Generate multimodal CLIP embeddings and detect & index faces for each extracted keyframe
  const processedFrames: Array<{
    id: string;
    frameNumber: number;
    sceneId: number;
    framePath: string;
    timestamp: number;
    visualDescription?: string;
    ocrText?: string;
    embeddingBuffer: Buffer | null;
  }> = [];

  const processedFaces: Array<{
    id: string;
    frameId: string;
    timestamp: number;
    confidence: number;
    bboxJson: string;
    cropPath?: string;
    embeddingBuffer: Buffer;
  }> = [];

  const facesDir = path.join(process.cwd(), 'uploads', 'faces', sourceId);
  if (!fs.existsSync(facesDir)) {
    fs.mkdirSync(facesDir, { recursive: true });
  }

  console.log(`[VideoProcessor] Analyzing ${extractedFrames.length} keyframes for visual embeddings & faces...`);

  for (const frame of extractedFrames) {
    const frameId = uuidv4();
    let frameEmbeddingBuffer: Buffer | null = null;

    // Full frame CLIP embedding
    try {
      const vec = await getImageEmbedding(frame.framePath);
      if (vec && vec.length > 0) {
        frameEmbeddingBuffer = floatArrayToBuffer(vec);
      }
    } catch (e) {
      console.warn('[VideoProcessor] Keyframe embedding error:', e);
    }

    // Face detection & face crop embedding
    let visualDescription: string | undefined = undefined;
    let ocrText: string | undefined = undefined;

    try {
      const faceResult = await detectFacesInImage(frame.framePath, { cropDir: facesDir, sourceId });
      visualDescription = faceResult.visualDescription;
      ocrText = faceResult.ocrText;

      for (const face of faceResult.faces) {
        if (face.embedding && face.embedding.length > 0) {
          processedFaces.push({
            id: face.id,
            frameId,
            timestamp: frame.timestamp,
            confidence: face.confidence,
            bboxJson: JSON.stringify(face.bbox),
            cropPath: face.cropPath,
            embeddingBuffer: floatArrayToBuffer(face.embedding),
          });
        }
      }
    } catch (faceErr) {
      console.warn(`[VideoProcessor] Face detection error for frame ${frame.frameNumber}:`, faceErr);
    }

    processedFrames.push({
      id: frameId,
      frameNumber: frame.frameNumber,
      sceneId: frame.sceneId,
      framePath: frame.framePath,
      timestamp: frame.timestamp,
      visualDescription,
      ocrText,
      embeddingBuffer: frameEmbeddingBuffer,
    });
  }

  const duration = videoDuration > 0
    ? videoDuration
    : transcriptSegments.length > 0
    ? transcriptSegments[transcriptSegments.length - 1].endTime
    : 0;

  // 7. Save everything to SQLite database in a transaction
  dbTransaction((db) => {
    // Clear any previous records for this sourceId
    try {
      db.prepare('DELETE FROM videos WHERE source_id = ?').run(sourceId);
      db.prepare('DELETE FROM video_transcripts WHERE source_id = ?').run(sourceId);
      db.prepare('DELETE FROM video_frames WHERE source_id = ?').run(sourceId);
      db.prepare('DELETE FROM face_embeddings WHERE source_id = ?').run(sourceId);
      db.prepare('DELETE FROM transcripts_fts WHERE source_id = ?').run(sourceId);
    } catch {
      // Ignore
    }

    // Insert into videos table
    db.prepare(`
      INSERT OR REPLACE INTO videos (id, source_id, duration, format, thumbnail_path)
      VALUES (?, ?, ?, ?, ?)
    `).run(videoId, sourceId, duration, format, processedFrames[0]?.framePath || null);

    // Insert transcript chunks
    for (const item of processedTranscripts) {
      db.prepare(`
        INSERT INTO video_transcripts (id, video_id, source_id, start_time, end_time, text, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      `).run(item.id, videoId, sourceId, item.startTime, item.endTime, item.text, item.embeddingBuffer);

      try {
        db.prepare(`
          INSERT INTO transcripts_fts (text, transcript_id, video_id, source_id, start_time, end_time)
          VALUES (?, ?, ?, ?, ?, ?)
        `).run(item.text, item.id, videoId, sourceId, item.startTime, item.endTime);
      } catch {
        // Handled
      }
    }

    // Insert keyframes with multimodal embeddings
    for (const frame of processedFrames) {
      db.prepare(`
        INSERT INTO video_frames (id, video_id, source_id, timestamp, frame_number, scene_id, frame_path, visual_description, ocr_text, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).run(
        frame.id,
        videoId,
        sourceId,
        frame.timestamp,
        frame.frameNumber,
        frame.sceneId,
        frame.framePath,
        frame.visualDescription || null,
        frame.ocrText || null,
        frame.embeddingBuffer
      );
    }

    // Insert face embeddings
    for (const face of processedFaces) {
      db.prepare(`
        INSERT INTO face_embeddings (id, source_id, video_id, frame_id, timestamp, embedding, confidence, bbox_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      `).run(
        face.id,
        sourceId,
        videoId,
        face.frameId,
        face.timestamp,
        face.embeddingBuffer,
        face.confidence,
        face.bboxJson
      );
    }

    // Update knowledge_sources status, counts, face count, and duration
    db.prepare(`
      UPDATE knowledge_sources
      SET processing_status = 'completed',
          transcript_count = ?,
          frame_count = ?,
          face_count = ?,
          duration_seconds = ?
      WHERE id = ?
    `).run(processedTranscripts.length, processedFrames.length, processedFaces.length, duration, sourceId);
  });

  console.log(
    `[VideoProcessor] Successfully indexed ${processedTranscripts.length} transcripts, ${processedFrames.length} keyframes, and ${processedFaces.length} face embeddings for ${originalName}`
  );

  return {
    videoId,
    sourceId,
    duration,
    format,
    transcriptCount: processedTranscripts.length,
    frameCount: processedFrames.length,
    faceCount: processedFaces.length,
    transcripts: processedTranscripts.map((t) => ({
      id: t.id,
      startTime: t.startTime,
      endTime: t.endTime,
      text: t.text,
    })),
    frames: processedFrames.map((f) => ({
      id: f.id,
      timestamp: f.timestamp,
      frameNumber: f.frameNumber,
      sceneId: f.sceneId,
      framePath: f.framePath,
      visualDescription: f.visualDescription,
    })),
    faces: processedFaces.map((f) => ({
      id: f.id,
      frameId: f.frameId,
      timestamp: f.timestamp,
      confidence: f.confidence,
      cropPath: f.cropPath,
    })),
  };
}
