// src/lib/retrieval/query-understanding.ts
// Multimodal Query Understanding & Context Enrichment Engine
// Extracts faces, OCR text, speech transcripts, visual embeddings, and entity signals from uploaded reference material,
// then enriches internet queries using discovered local knowledge.

import fs from 'fs';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import { execFile } from 'child_process';
import { promisify } from 'util';
import Groq from 'groq-sdk';
import {
  getImageEmbedding,
  getTextEmbedding,
  getMultimodalTextEmbedding,
} from '@/lib/embeddings/multimodal-embeddings';
import {
  detectFacesInImage,
  DetectedFace,
  FaceDetectionResult,
} from '@/lib/face/face-detector';
import type { MultimodalSearchResultItem } from './multimodal-retrieval';

const execFileAsync = promisify(execFile);
const groq = new Groq({ apiKey: process.env.GROQ_API_KEY || '' });

export interface MultimodalQueryInput {
  textQuery?: string;
  fileBuffer?: Buffer;
  filePath?: string;
  fileName?: string;
  mimeType?: string;
  fileCategory?: 'image' | 'video' | 'audio' | 'document' | 'clipping' | 'text';
  previewUrl?: string;
}

export interface ParsedQuerySignals {
  queryType: 'text' | 'image' | 'video' | 'audio' | 'document' | 'clipping';
  originalQueryText?: string;
  fileName?: string;
  previewUrl?: string;
  // Extracted signals
  hasFace: boolean;
  faces: DetectedFace[];
  primaryFace?: DetectedFace;
  faceEmbeddings: number[][];
  visualEmbedding?: number[];
  textEmbedding?: number[];
  clipTextEmbedding?: number[];
  ocrText?: string;
  visualDescription?: string;
  speechTranscript?: string;
  documentText?: string;
  extractedEntities: string[];
  derivedSearchKeywords: string;
}

export interface EnhancedQueryOutput {
  primaryQuery: string;
  queryVariants: string[];
  discoveredEntities: string[];
  contextSummary: string;
  lineage: Array<{
    step: number;
    title: string;
    description: string;
    badge?: string;
    type: 'upload' | 'vision_face' | 'local_match' | 'context_extraction' | 'internet_query' | 'internet_results';
  }>;
}

const DOCUMENT_EXTENSIONS = new Set(['pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx', 'xls', 'json', 'xml', 'html']);
const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'avif']);
const VIDEO_EXTENSIONS = new Set(['mp4', 'avi', 'mov', 'mkv', 'webm']);
const AUDIO_EXTENSIONS = new Set(['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac']);

/**
 * Determines file category from filename and mimetype
 */
export function detectFileCategory(fileName?: string, mimeType?: string): 'image' | 'video' | 'audio' | 'document' | 'text' {
  if (mimeType) {
    if (mimeType.startsWith('image/')) return 'image';
    if (mimeType.startsWith('video/')) return 'video';
    if (mimeType.startsWith('audio/')) return 'audio';
    if (mimeType.includes('pdf') || mimeType.includes('document') || mimeType.includes('text') || mimeType.includes('csv')) return 'document';
  }

  if (fileName) {
    const ext = fileName.split('.').pop()?.toLowerCase() || '';
    if (IMAGE_EXTENSIONS.has(ext)) return 'image';
    if (VIDEO_EXTENSIONS.has(ext)) return 'video';
    if (AUDIO_EXTENSIONS.has(ext)) return 'audio';
    if (DOCUMENT_EXTENSIONS.has(ext)) return 'document';
  }

  return 'text';
}

/**
 * Transcribes audio buffer or file using Groq Whisper API
 */
async function transcribeAudio(filePathOrBuffer: string | Buffer, filename = 'query_audio.mp3'): Promise<string> {
  if (!process.env.GROQ_API_KEY) return '';

  let tempPath: string | null = null;
  let audioPath = '';

  if (Buffer.isBuffer(filePathOrBuffer)) {
    const tempDir = path.join(process.cwd(), 'uploads', 'temp');
    if (!fs.existsSync(tempDir)) fs.mkdirSync(tempDir, { recursive: true });
    tempPath = path.join(tempDir, `audio_query_${uuidv4()}.mp3`);
    fs.writeFileSync(tempPath, filePathOrBuffer);
    audioPath = tempPath;
  } else {
    audioPath = filePathOrBuffer;
  }

  try {
    const fileStream = fs.createReadStream(audioPath);
    const response = await groq.audio.transcriptions.create({
      file: fileStream,
      model: 'whisper-large-v3',
      response_format: 'verbose_json',
      temperature: 0.0,
    });

    if (tempPath && fs.existsSync(tempPath)) fs.unlinkSync(tempPath);
    return response.text?.trim() || '';
  } catch (err) {
    console.warn('[QueryUnderstanding] Whisper transcription error:', err);
    if (tempPath && fs.existsSync(tempPath)) {
      try { fs.unlinkSync(tempPath); } catch { /* ignore */ }
    }
    return '';
  }
}

/**
 * Extracts text from PDF buffer
 */
async function extractPdfText(buffer: Buffer): Promise<string> {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const pdfModule = require('pdf-parse');
    if (pdfModule.PDFParse) {
      const parser = new pdfModule.PDFParse({ data: buffer });
      const data = await parser.getText();
      return data.text || '';
    } else if (typeof pdfModule === 'function') {
      const data = await pdfModule(buffer);
      return data.text || '';
    } else if (pdfModule.default && typeof pdfModule.default === 'function') {
      const data = await pdfModule.default(buffer);
      return data.text || '';
    }
  } catch (err) {
    console.warn('[QueryUnderstanding] PDF parse error:', err);
  }
  return '';
}

/**
 * Extracts entities, names, and titles using Groq LLM
 */
async function extractEntitiesWithLLM(text: string): Promise<string[]> {
  if (!process.env.GROQ_API_KEY || !text.trim()) return [];

  try {
    const completion = await groq.chat.completions.create({
      model: 'qwen/qwen3.6-27b',
      messages: [
        {
          role: 'system',
          content: 'Extract key named entities (Person names, Organizations, Roles/Designations, Places, Concepts) from the text. Return ONLY a JSON array of strings: ["Entity 1", "Entity 2"]',
        },
        { role: 'user', content: text.slice(0, 3000) },
      ],
      max_tokens: 300,
      temperature: 0.1,
    });

    const raw = completion.choices[0]?.message?.content || '[]';
    const clean = raw.replace(/```json/gi, '').replace(/```/g, '').trim();
    const parsed = JSON.parse(clean);
    if (Array.isArray(parsed)) {
      return parsed.filter((item): item is string => typeof item === 'string' && item.trim().length > 1);
    }
  } catch (err) {
    console.warn('[QueryUnderstanding] Entity extraction warning:', err);
  }
  return [];
}

/**
 * Universal Multimodal Query Understanding pipeline
 */
export async function understandMultimodalQuery(input: MultimodalQueryInput): Promise<ParsedQuerySignals> {
  const category = input.fileCategory || detectFileCategory(input.fileName, input.mimeType);
  const textQuery = input.textQuery?.trim() || '';

  const signals: ParsedQuerySignals = {
    queryType: category,
    originalQueryText: textQuery || undefined,
    fileName: input.fileName,
    previewUrl: input.previewUrl,
    hasFace: false,
    faces: [],
    faceEmbeddings: [],
    extractedEntities: [],
    derivedSearchKeywords: textQuery,
  };

  // 1. If Text Query exists, compute text embeddings & extract entities
  if (textQuery) {
    const [tVec, clipVec] = await Promise.all([
      getTextEmbedding(textQuery),
      getMultimodalTextEmbedding(textQuery),
    ]);
    signals.textEmbedding = tVec;
    signals.clipTextEmbedding = clipVec;
    const textEntities = await extractEntitiesWithLLM(textQuery);
    signals.extractedEntities.push(...textEntities);
  }

  // 2. Handle Image / Newspaper Clipping Query
  if ((category === 'image' || category === 'clipping') && (input.fileBuffer || input.filePath)) {
    const imgData = input.fileBuffer || input.filePath!;
    
    // Face detection & cropping & face embeddings
    const faceResult = await detectFacesInImage(imgData, { sourceId: 'query' });
    signals.hasFace = faceResult.hasFace;
    signals.faces = faceResult.faces;
    signals.primaryFace = faceResult.primaryFace;
    signals.ocrText = faceResult.ocrText;
    signals.visualDescription = faceResult.visualDescription;

    if (faceResult.identifiedNames && faceResult.identifiedNames.length > 0) {
      signals.extractedEntities.push(...faceResult.identifiedNames);
    }

    // Collect face embeddings
    for (const face of faceResult.faces) {
      if (face.embedding) {
        signals.faceEmbeddings.push(face.embedding);
      }
    }

    // Full image visual embedding
    try {
      signals.visualEmbedding = await getImageEmbedding(imgData);
    } catch (err) {
      console.warn('[QueryUnderstanding] Full image embedding error:', err);
    }

    // Derive search keywords from OCR and visual description if no text query was provided
    if (!signals.derivedSearchKeywords) {
      const parts = [
        ...signals.extractedEntities,
        faceResult.ocrText ? faceResult.ocrText.slice(0, 150) : '',
        faceResult.visualDescription ? faceResult.visualDescription.slice(0, 100) : '',
      ].filter(Boolean);
      signals.derivedSearchKeywords = parts.join(' ').trim() || (input.fileName ? input.fileName.replace(/\.[^/.]+$/, '') : 'Visual Query');
    }
  }

  // 3. Handle Video Query
  else if (category === 'video' && (input.fileBuffer || input.filePath)) {
    let videoPath = input.filePath || '';
    let tempVideoPath: string | null = null;

    if (!videoPath && input.fileBuffer) {
      const tempDir = path.join(process.cwd(), 'uploads', 'temp');
      if (!fs.existsSync(tempDir)) fs.mkdirSync(tempDir, { recursive: true });
      tempVideoPath = path.join(tempDir, `query_video_${uuidv4()}.mp4`);
      fs.writeFileSync(tempVideoPath, input.fileBuffer);
      videoPath = tempVideoPath;
    }

    try {
      // Extract audio & transcribe
      const tempAudio = path.join(process.cwd(), 'uploads', 'temp', `audio_${uuidv4()}.mp3`);
      try {
        await execFileAsync('ffmpeg', ['-y', '-i', videoPath, '-vn', '-ar', '16000', '-ac', '1', tempAudio]);
        if (fs.existsSync(tempAudio)) {
          signals.speechTranscript = await transcribeAudio(tempAudio);
          fs.unlinkSync(tempAudio);
        }
      } catch {
        // Fallback
      }

      // Extract 2-3 sample keyframes for face & visual detection
      const tempFramesDir = path.join(process.cwd(), 'uploads', 'temp', `frames_${uuidv4()}`);
      if (!fs.existsSync(tempFramesDir)) fs.mkdirSync(tempFramesDir, { recursive: true });

      try {
        await execFileAsync('ffmpeg', ['-y', '-i', videoPath, '-vf', 'fps=1/3', '-vframes', '3', path.join(tempFramesDir, 'frame_%02d.jpg')]);
        const frameFiles = fs.readdirSync(tempFramesDir).filter((f) => f.endsWith('.jpg'));
        
        for (const ff of frameFiles) {
          const framePath = path.join(tempFramesDir, ff);
          const fRes = await detectFacesInImage(framePath, { sourceId: 'query' });
          if (fRes.hasFace && fRes.faces.length > 0) {
            signals.hasFace = true;
            signals.faces.push(...fRes.faces);
            for (const f of fRes.faces) {
              if (f.embedding) signals.faceEmbeddings.push(f.embedding);
            }
          }
        }
      } catch {
        // Handled
      }

      if (signals.speechTranscript) {
        const entities = await extractEntitiesWithLLM(signals.speechTranscript);
        signals.extractedEntities.push(...entities);
      }

      if (!signals.derivedSearchKeywords) {
        signals.derivedSearchKeywords = signals.speechTranscript?.slice(0, 150) || input.fileName?.replace(/\.[^/.]+$/, '') || 'Video Query';
      }
    } finally {
      if (tempVideoPath && fs.existsSync(tempVideoPath)) {
        try { fs.unlinkSync(tempVideoPath); } catch { /* ignore */ }
      }
    }
  }

  // 4. Handle Audio Query
  else if (category === 'audio' && (input.fileBuffer || input.filePath)) {
    const audioData = input.fileBuffer || input.filePath!;
    signals.speechTranscript = await transcribeAudio(audioData, input.fileName || 'audio.mp3');

    if (signals.speechTranscript) {
      const entities = await extractEntitiesWithLLM(signals.speechTranscript);
      signals.extractedEntities.push(...entities);
      if (!signals.derivedSearchKeywords) {
        signals.derivedSearchKeywords = signals.speechTranscript.slice(0, 150);
      }
    }
  }

  // 5. Handle Document / PDF Query
  else if (category === 'document' && (input.fileBuffer || input.filePath)) {
    let docBuffer = input.fileBuffer;
    if (!docBuffer && input.filePath && fs.existsSync(input.filePath)) {
      docBuffer = fs.readFileSync(input.filePath);
    }

    if (docBuffer) {
      const ext = input.fileName?.split('.').pop()?.toLowerCase() || '';
      if (ext === 'pdf') {
        signals.documentText = await extractPdfText(docBuffer);
      } else {
        signals.documentText = docBuffer.toString('utf-8');
      }

      if (signals.documentText) {
        const entities = await extractEntitiesWithLLM(signals.documentText.slice(0, 2500));
        signals.extractedEntities.push(...entities);
        if (!signals.derivedSearchKeywords) {
          signals.derivedSearchKeywords = signals.extractedEntities.slice(0, 4).join(' ') || signals.documentText.slice(0, 120);
        }
      }
    }
  }

  return signals;
}

/**
 * Builds enhanced, entity-rich internet search queries using discovered local knowledge
 */
export async function generateEnhancedInternetQuery(
  signals: ParsedQuerySignals,
  localMatches: MultimodalSearchResultItem[]
): Promise<EnhancedQueryOutput> {
  const topLocal = localMatches[0];
  const discoveredEntities = new Set<string>(signals.extractedEntities);

  // Extract candidate entities & context from local matches
  const localContextSnippets: string[] = [];
  for (const match of localMatches.slice(0, 4)) {
    localContextSnippets.push(`[${match.category.toUpperCase()}] "${match.title}": ${match.snippet}`);
    
    // Extract title words as candidate entities
    const cleanTitle = match.title.replace(/\.[^/.]+$/, '').replace(/[-_]/g, ' ');
    const titleWords = cleanTitle.split(/\s+/).filter((w) => w.length >= 3);
    if (titleWords.length >= 2) {
      discoveredEntities.add(cleanTitle);
    }
  }

  let primaryQuery = signals.originalQueryText || signals.derivedSearchKeywords || 'AI Research Intelligence';
  let queryVariants: string[] = [primaryQuery];
  let contextSummary = 'Direct multimodal search execution across internet and indexed local knowledge base.';

  // If local match was found, use Groq LLM to synthesize high-precision enriched internet queries
  if (topLocal && process.env.GROQ_API_KEY) {
    try {
      const prompt = `You are an AI intelligence query specialist.
A user uploaded an input of type: ${signals.queryType} ${signals.fileName ? `(${signals.fileName})` : ''}.
${signals.hasFace ? `A face was detected with ${signals.faces.length} occurrences.` : ''}
${signals.ocrText ? `Extracted OCR text: "${signals.ocrText.slice(0, 200)}"` : ''}
${signals.speechTranscript ? `Speech transcript: "${signals.speechTranscript.slice(0, 200)}"` : ''}

The local knowledge search found these high-relevance local matches:
${localContextSnippets.join('\n')}

Top Local Match: "${topLocal.title}" (${topLocal.category}${topLocal.startTime !== undefined ? ` at ${Math.round(topLocal.startTime)}s` : ''})

Based on the discovered local context (such as person names, designations, organizations, or topic keywords in the local matches):
1. Extract the authoritative entity names and designations (e.g. "SSC Chairman Gopal Krishna" or "Gopal Krishna").
2. Generate an ENHANCED INTERNET SEARCH QUERY that will find the most relevant current news, articles, web pages, and research.
3. Generate 3 search query variants.
4. Write a 1-2 sentence context summary explaining how the local match enriched the internet query.

Return ONLY valid JSON (no markdown formatting, no backticks):
{
  "primaryQuery": "string (the enriched internet query)",
  "queryVariants": ["query 1", "query 2", "query 3"],
  "discoveredEntities": ["Entity 1", "Entity 2"],
  "contextSummary": "string explanation"
}`;

      const completion = await groq.chat.completions.create({
        model: 'qwen/qwen3.6-27b',
        messages: [{ role: 'user', content: prompt }],
        max_tokens: 500,
        temperature: 0.1,
      });

      const raw = completion.choices[0]?.message?.content || '{}';
      const clean = raw.replace(/```json/gi, '').replace(/```/g, '').trim();
      const parsed = JSON.parse(clean);

      if (parsed.primaryQuery) primaryQuery = parsed.primaryQuery;
      if (Array.isArray(parsed.queryVariants) && parsed.queryVariants.length > 0) {
        queryVariants = parsed.queryVariants;
      }
      if (Array.isArray(parsed.discoveredEntities)) {
        parsed.discoveredEntities.forEach((e: string) => discoveredEntities.add(e));
      }
      if (parsed.contextSummary) contextSummary = parsed.contextSummary;
    } catch (err) {
      console.warn('[QueryUnderstanding] Enhanced query synthesis fallback:', err);
      // Heuristic fallback: use top local title
      const cleanTitle = topLocal.title.replace(/\.[^/.]+$/, '').replace(/[-_]/g, ' ');
      primaryQuery = cleanTitle;
      queryVariants = [cleanTitle, `${cleanTitle} news updates`, `${cleanTitle} analysis`];
      contextSummary = `Identified local match "${topLocal.title}". Local metadata provided entity context to execute targeted internet search.`;
    }
  } else if (topLocal) {
    const cleanTitle = topLocal.title.replace(/\.[^/.]+$/, '').replace(/[-_]/g, ' ');
    primaryQuery = cleanTitle;
    queryVariants = [cleanTitle, `${cleanTitle} news updates`, `${cleanTitle} analysis`];
    contextSummary = `Identified local match "${topLocal.title}". Local metadata provided entity context to execute targeted internet search.`;
  }

  // Build step-by-step Discovery Trace Lineage
  const lineage: EnhancedQueryOutput['lineage'] = [];
  let stepIdx = 1;

  // Step 1: Upload
  lineage.push({
    step: stepIdx++,
    type: 'upload',
    title: `Uploaded Reference Material: ${signals.queryType.toUpperCase()}`,
    description: signals.fileName ? `Loaded file "${signals.fileName}"` : `Analyzed ${signals.queryType} query input`,
    badge: signals.queryType,
  });

  // Step 2: Signal extraction
  if (signals.hasFace) {
    lineage.push({
      step: stepIdx++,
      type: 'vision_face',
      title: `Face Detection & Visual Isolation`,
      description: `Detected ${signals.faces.length} face(s), cropped bounding boxes, and computed 512-dim face vector embeddings`,
      badge: `${signals.faces.length} Face(s)`,
    });
  } else if (signals.ocrText) {
    lineage.push({
      step: stepIdx++,
      type: 'vision_face',
      title: `OCR & Visual Text Recognition`,
      description: `Extracted visual text snippet: "${signals.ocrText.slice(0, 100)}..."`,
      badge: 'OCR',
    });
  } else if (signals.speechTranscript) {
    lineage.push({
      step: stepIdx++,
      type: 'vision_face',
      title: `Speech Transcription (Whisper)`,
      description: `Transcribed audio content: "${signals.speechTranscript.slice(0, 100)}..."`,
      badge: 'Speech',
    });
  }

  // Step 3: Local match
  if (topLocal) {
    const timeStr = topLocal.startTime !== undefined ? ` at timestamp ${Math.floor(topLocal.startTime / 60)}:${String(Math.floor(topLocal.startTime % 60)).padStart(2, '0')}` : '';
    lineage.push({
      step: stepIdx++,
      type: 'local_match',
      title: `Local Knowledge Match: ${topLocal.title}`,
      description: `Matched indexed ${topLocal.category}${timeStr} with ${Math.round(topLocal.relevanceScore * 100)}% similarity score`,
      badge: `${Math.round(topLocal.relevanceScore * 100)}% Match`,
    });
  }

  // Step 4: Discovered Entity
  const entityList = Array.from(discoveredEntities).slice(0, 4);
  if (entityList.length > 0) {
    lineage.push({
      step: stepIdx++,
      type: 'context_extraction',
      title: `Context & Entity Extraction`,
      description: `Discovered key entities from local metadata: ${entityList.join(', ')}`,
      badge: `${entityList.length} Entities`,
    });
  }

  // Step 5: Enhanced query
  lineage.push({
    step: stepIdx++,
    type: 'internet_query',
    title: `Enhanced Internet Search Query`,
    description: `Constructed enriched search query: "${primaryQuery}"`,
    badge: 'Query Refined',
  });

  // Step 6: Internet results
  lineage.push({
    step: stepIdx++,
    type: 'internet_results',
    title: `Live Internet Intelligence Retrieved`,
    description: `Fetched live Web, News, Research Papers, Videos, and Images matching "${primaryQuery}"`,
    badge: 'Live Results',
  });

  return {
    primaryQuery,
    queryVariants,
    discoveredEntities: Array.from(discoveredEntities),
    contextSummary,
    lineage,
  };
}
