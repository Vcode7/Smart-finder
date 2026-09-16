// src/lib/retrieval/multimodal-retrieval.ts
// Multimodal retrieval engine: Face-based video retrieval, Visual search (Image -> Video frames),
// High-precision hybrid text search, Entity verification, Cross-source knowledge discovery, and source-first ranking.

import { dbAll, dbGet } from '@/lib/db/client';
import {
  getImageEmbedding,
  getTextEmbedding,
  getMultimodalTextEmbedding,
  cosineSimilarity,
  blobToFloatArray,
} from '@/lib/embeddings/multimodal-embeddings';
import {
  detectFacesInImage,
  searchFaceEmbeddings,
} from '@/lib/face/face-detector';
import { searchDocumentChunks, searchTranscripts } from './keyword-search';
import { expandDocumentChunk, expandTranscriptSegment } from './context-expander';
import type { ParsedQuerySignals } from './query-understanding';

export interface MatchingFrame {
  id: string;
  frameNumber: number;
  sceneId: number;
  timestamp: number;
  framePath: string;
  similarity: number;
  isFaceMatch?: boolean;
  faceSimilarity?: number;
  visualDescription?: string;
}

export interface CrossSourceItem {
  id: string;
  sourceId: string;
  category: 'document' | 'image' | 'video' | 'audio';
  title: string;
  originalName: string;
  fileType: string;
  fileSize: number;
  uploadDate: string;
  snippet: string;
  relevanceScore: number;
  pageNum?: number;
  timestamp?: number;
}

export interface MultimodalSearchResultItem {
  id: string;
  sourceId: string;
  category: 'document' | 'image' | 'video' | 'audio';
  title: string;
  originalName: string;
  fileType: string;
  fileSize: number;
  uploadDate: string;
  relevanceScore: number;
  snippet: string;
  fullContext?: string;
  isFaceMatch?: boolean;
  faceSimilarity?: number;
  detectedEntity?: string;
  // Document specific
  sectionTitle?: string;
  pageNum?: number;
  pageCount?: number;
  // Video / Audio specific
  startTime?: number;
  endTime?: number;
  duration?: number;
  matchingFrames?: MatchingFrame[];
  primaryFrame?: MatchingFrame;
  // Image specific
  thumbnail?: string;
  description?: string;
  ocrText?: string;
  // Cross-source related documents
  relatedCrossSources?: CrossSourceItem[];
}

export interface MultimodalSearchResponse {
  query: string;
  queryType: 'text' | 'image' | 'video' | 'audio' | 'document' | 'clipping';
  queryImagePreview?: string;
  documents: MultimodalSearchResultItem[];
  videos: MultimodalSearchResultItem[];
  audio: MultimodalSearchResultItem[];
  images: MultimodalSearchResultItem[];
  total: number;
}

const DOCUMENT_EXTENSIONS = new Set(['pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx', 'xls', 'json', 'xml', 'html']);
const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp']);
const VIDEO_EXTENSIONS = new Set(['mp4', 'avi', 'mov', 'mkv', 'webm']);
const AUDIO_EXTENSIONS = new Set(['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac']);

const STOPWORDS = new Set([
  'a', 'an', 'the', 'is', 'are', 'was', 'were', 'and', 'or', 'but', 'if', 'in', 'on',
  'at', 'to', 'for', 'with', 'about', 'against', 'between', 'into', 'through', 'during',
  'before', 'after', 'above', 'below', 'from', 'up', 'down', 'of', 'off', 'over', 'under',
  'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how',
  'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
  'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'can', 'will', 'just',
  'don', 'should', 'now', 'this', 'that', 'these', 'those', 'video', 'image', 'document'
]);

/**
 * Extracts salient search tokens from query or text
 */
function extractQueryTokens(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((w) => w.length >= 2 && !STOPWORDS.has(w));
}

/**
 * Discovers cross-source documents, PDFs, audio, or images with strict multi-word context
 */
function discoverCrossSourceDocuments(
  contextText: string,
  excludeSourceIds: Set<string>,
  limit = 3
): CrossSourceItem[] {
  if (!contextText?.trim()) return [];

  const tokens = extractQueryTokens(contextText);
  if (tokens.length < 2) return [];

  const queryPhrase = tokens.slice(0, 4).join(' ');
  const chunkMatches = searchDocumentChunks(queryPhrase, limit * 2);
  const crossResults: CrossSourceItem[] = [];
  const seenIds = new Set<string>();

  for (const chunk of chunkMatches) {
    if (excludeSourceIds.has(chunk.sourceId) || seenIds.has(chunk.sourceId)) continue;
    seenIds.add(chunk.sourceId);

    const src = dbGet<{
      id: string;
      original_name: string;
      file_type: string;
      file_size: number;
      upload_date: string;
    }>('SELECT * FROM knowledge_sources WHERE id = ?', [chunk.sourceId]);

    if (src) {
      crossResults.push({
        id: chunk.id,
        sourceId: src.id,
        category: 'document',
        title: src.original_name,
        originalName: src.original_name,
        fileType: src.file_type,
        fileSize: src.file_size,
        uploadDate: src.upload_date,
        snippet: chunk.text.slice(0, 200),
        relevanceScore: Math.round((chunk.score * 0.85) * 100) / 100,
        pageNum: chunk.pageNum,
      });
    }
    if (crossResults.length >= limit) break;
  }

  return crossResults;
}

/**
 * Universal Multimodal Search using parsed query signals (Faces, Visual Embeddings, OCR, Transcripts, Text)
 */
export async function searchByMultimodalSignals(
  signals: ParsedQuerySignals
): Promise<MultimodalSearchResponse> {
  console.log(`[MultimodalRetrieval] Searching with signals: type=${signals.queryType}, hasFace=${signals.hasFace}, faces=${signals.faces.length}`);

  const processedSourceIds = new Set<string>();
  const videoResults: MultimodalSearchResultItem[] = [];
  const imageResults: MultimodalSearchResultItem[] = [];
  const documentResults: MultimodalSearchResultItem[] = [];
  const audioResults: MultimodalSearchResultItem[] = [];

  // ─────────────────────────────────────────────────────────────────────────────
  // 1. FACE-BASED RETRIEVAL (Priority 1 for person / visual identity)
  // ─────────────────────────────────────────────────────────────────────────────
  const faceMatchesByVideo = new Map<string, {
    videoId: string;
    sourceId: string;
    bestSimilarity: number;
    bestTimestamp: number;
    matchingFrames: MatchingFrame[];
  }>();

  if (signals.hasFace && signals.faceEmbeddings.length > 0) {
    for (const faceEmb of signals.faceEmbeddings) {
      const matches = searchFaceEmbeddings(faceEmb, { minSimilarity: 0.50, limit: 20 });
      for (const m of matches) {
        if (m.videoId) {
          const existing = faceMatchesByVideo.get(m.videoId);
          const frameObj: MatchingFrame = {
            id: m.frameId || m.id,
            frameNumber: m.frameNumber || 1,
            sceneId: 1,
            timestamp: m.timestamp || 0,
            framePath: m.framePath || '',
            similarity: m.similarity,
            isFaceMatch: true,
            faceSimilarity: m.similarity,
          };

          if (!existing) {
            faceMatchesByVideo.set(m.videoId, {
              videoId: m.videoId,
              sourceId: m.sourceId,
              bestSimilarity: m.similarity,
              bestTimestamp: m.timestamp || 0,
              matchingFrames: [frameObj],
            });
          } else {
            existing.matchingFrames.push(frameObj);
            if (m.similarity > existing.bestSimilarity) {
              existing.bestSimilarity = m.similarity;
              existing.bestTimestamp = m.timestamp || 0;
            }
          }
        }
      }
    }
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // 2. VIDEO KEYFRAME VISUAL RETRIEVAL (Full-Frame CLIP Embedding)
  // ─────────────────────────────────────────────────────────────────────────────
  const visualFramesByVideo = new Map<string, {
    videoId: string;
    sourceId: string;
    topSimilarity: number;
    frames: MatchingFrame[];
  }>();

  if (signals.visualEmbedding) {
    const frameRows = dbAll<{
      id: string;
      video_id: string;
      source_id: string;
      timestamp: number;
      frame_number: number;
      scene_id: number;
      frame_path: string;
      visual_description: string | null;
      embedding: Buffer | null;
    }>('SELECT * FROM video_frames');

    for (const row of frameRows) {
      if (!row.embedding) continue;
      const storedVec = blobToFloatArray(row.embedding);
      const similarity = cosineSimilarity(signals.visualEmbedding, storedVec);

      if (similarity > 0.40) {
        const existing = visualFramesByVideo.get(row.video_id);
        const fObj: MatchingFrame = {
          id: row.id,
          frameNumber: row.frame_number || 1,
          sceneId: row.scene_id || 1,
          timestamp: row.timestamp,
          framePath: row.frame_path,
          similarity: Number(similarity.toFixed(4)),
          visualDescription: row.visual_description || undefined,
        };

        if (!existing) {
          visualFramesByVideo.set(row.video_id, {
            videoId: row.video_id,
            sourceId: row.source_id,
            topSimilarity: similarity,
            frames: [fObj],
          });
        } else {
          existing.frames.push(fObj);
          if (similarity > existing.topSimilarity) {
            existing.topSimilarity = similarity;
          }
        }
      }
    }
  }

  // Combine Face Matches and Visual Matches for Videos
  const allVideoIds = new Set([...faceMatchesByVideo.keys(), ...visualFramesByVideo.keys()]);

  for (const vId of allVideoIds) {
    const faceGroup = faceMatchesByVideo.get(vId);
    const visualGroup = visualFramesByVideo.get(vId);
    const sourceId = faceGroup?.sourceId || visualGroup?.sourceId;
    if (!sourceId) continue;

    const source = dbGet<{
      id: string;
      original_name: string;
      file_type: string;
      file_size: number;
      upload_date: string;
      duration_seconds?: number;
    }>('SELECT * FROM knowledge_sources WHERE id = ?', [sourceId]);

    if (!source) continue;
    processedSourceIds.add(source.id);

    // Merge frames
    const mergedFrames: MatchingFrame[] = [
      ...(faceGroup?.matchingFrames || []),
      ...(visualGroup?.frames || []),
    ];
    mergedFrames.sort((a, b) => b.similarity - a.similarity);
    const primaryFrame = mergedFrames[0];

    // Compute composite score: face similarity is weighted heavily
    const faceScore = faceGroup?.bestSimilarity || 0;
    const visualScore = visualGroup?.topSimilarity || 0;
    const isFaceMatch = faceScore > 0.50;

    const compositeScore = isFaceMatch
      ? Math.max(faceScore, faceScore * 0.6 + visualScore * 0.4)
      : visualScore;

    const bestTimestamp = primaryFrame ? primaryFrame.timestamp : (faceGroup?.bestTimestamp || 0);

    // Nearby transcripts
    const nearbyTranscripts = dbAll<{
      id: string;
      start_time: number;
      end_time: number;
      text: string;
    }>(
      `SELECT id, start_time, end_time, text FROM video_transcripts
       WHERE video_id = ? AND start_time <= ? AND end_time >= ?
       ORDER BY start_time ASC LIMIT 3`,
      [vId, bestTimestamp + 35, Math.max(0, bestTimestamp - 35)]
    );

    let snippet = '';
    let startTimestamp = Math.max(0, bestTimestamp - 5);
    let endTimestamp = bestTimestamp + 25;

    if (nearbyTranscripts.length > 0) {
      snippet = nearbyTranscripts.map((t) => t.text).join(' ');
      startTimestamp = nearbyTranscripts[0].start_time;
      endTimestamp = nearbyTranscripts[nearbyTranscripts.length - 1].end_time;
    } else {
      snippet = isFaceMatch
        ? `Identified face match at timestamp ${Math.floor(bestTimestamp / 60)}:${String(Math.floor(bestTimestamp % 60)).padStart(2, '0')} (${Math.round(compositeScore * 100)}% facial similarity)`
        : `Visually matching scene at timestamp ${bestTimestamp}s (${Math.round(compositeScore * 100)}% visual match)`;
    }

    const crossSources = discoverCrossSourceDocuments(snippet, new Set([source.id]), 3);

    videoResults.push({
      id: `vid-${vId}-${primaryFrame?.frameNumber || 1}`,
      sourceId: source.id,
      category: 'video',
      title: source.original_name,
      originalName: source.original_name,
      fileType: source.file_type,
      fileSize: source.file_size,
      uploadDate: source.upload_date,
      duration: source.duration_seconds,
      startTime: Math.round(startTimestamp),
      endTime: Math.round(endTimestamp),
      relevanceScore: Number(compositeScore.toFixed(3)),
      snippet: snippet.slice(0, 450),
      fullContext: `Video: ${source.original_name}\nTimestamp: ${bestTimestamp}s\nContext: ${snippet}`,
      isFaceMatch,
      faceSimilarity: isFaceMatch ? faceScore : undefined,
      matchingFrames: mergedFrames.slice(0, 6),
      primaryFrame,
      relatedCrossSources: crossSources,
    });
  }

  videoResults.sort((a, b) => b.relevanceScore - a.relevanceScore);

  // ─────────────────────────────────────────────────────────────────────────────
  // 3. IMAGE MATCHES (Face & Visual)
  // ─────────────────────────────────────────────────────────────────────────────
  const imageRows = dbAll<{
    id: string;
    source_id: string;
    description: string | null;
    ocr_text: string | null;
    embedding: Buffer | null;
  }>('SELECT id, source_id, description, ocr_text, embedding FROM images');

  for (const img of imageRows) {
    let score = 0;
    let isFaceMatch = false;

    // Check full-image visual similarity
    if (signals.visualEmbedding && img.embedding) {
      const storedVec = blobToFloatArray(img.embedding);
      score = cosineSimilarity(signals.visualEmbedding, storedVec);
    }

    // Check face matches on image
    if (signals.hasFace && signals.faceEmbeddings.length > 0) {
      const faceRows = dbAll<{ embedding: Buffer }>(
        'SELECT embedding FROM face_embeddings WHERE image_id = ?',
        [img.id]
      );
      for (const fr of faceRows) {
        if (!fr.embedding) continue;
        const storedFaceVec = blobToFloatArray(fr.embedding);
        for (const qf of signals.faceEmbeddings) {
          const fSim = cosineSimilarity(qf, storedFaceVec);
          if (fSim > score) {
            score = fSim;
            isFaceMatch = true;
          }
        }
      }
    }

    if (score > 0.45) {
      const src = dbGet<{
        id: string;
        original_name: string;
        file_type: string;
        file_size: number;
        upload_date: string;
      }>('SELECT * FROM knowledge_sources WHERE id = ?', [img.source_id]);

      if (src) {
        processedSourceIds.add(src.id);
        const snippet = img.description || img.ocr_text || `Visual Match (${Math.round(score * 100)}%)`;
        imageResults.push({
          id: `img-${img.id}`,
          sourceId: src.id,
          category: 'image',
          title: src.original_name,
          originalName: src.original_name,
          fileType: src.file_type,
          fileSize: src.file_size,
          uploadDate: src.upload_date,
          relevanceScore: Number(score.toFixed(3)),
          snippet,
          thumbnail: `/api/knowledge/${src.id}/file`,
          description: img.description || undefined,
          ocrText: img.ocr_text || undefined,
          isFaceMatch,
          faceSimilarity: isFaceMatch ? score : undefined,
        });
      }
    }
  }

  imageResults.sort((a, b) => b.relevanceScore - a.relevanceScore);

  // ─────────────────────────────────────────────────────────────────────────────
  // 4. DOCUMENT & AUDIO RETRIEVAL (Using Derived Keywords, OCR, or Discovered Context)
  // ─────────────────────────────────────────────────────────────────────────────
  const textQuery = signals.originalQueryText || signals.derivedSearchKeywords || signals.ocrText || '';
  if (textQuery.trim()) {
    const textRes = await searchByText(textQuery);

    for (const doc of textRes.documents) {
      if (!processedSourceIds.has(doc.sourceId)) {
        processedSourceIds.add(doc.sourceId);
        documentResults.push(doc);
      }
    }

    for (const aud of textRes.audio) {
      if (!processedSourceIds.has(aud.sourceId)) {
        processedSourceIds.add(aud.sourceId);
        audioResults.push(aud);
      }
    }

    // Also include any text-matched videos that weren't caught visually
    for (const vid of textRes.videos) {
      if (!processedSourceIds.has(vid.sourceId)) {
        processedSourceIds.add(vid.sourceId);
        videoResults.push(vid);
      }
    }
  }

  const total = documentResults.length + videoResults.length + audioResults.length + imageResults.length;

  return {
    query: signals.originalQueryText || signals.derivedSearchKeywords || 'Multimodal Query',
    queryType: signals.queryType,
    queryImagePreview: signals.previewUrl,
    documents: documentResults,
    videos: videoResults,
    audio: audioResults,
    images: imageResults,
    total,
  };
}

/**
 * Multimodal Visual Search: searches an uploaded image against indexed video keyframes, faces, and image database
 */
export async function searchByImage(
  imageInput: string | Buffer,
  queryPreviewUrl?: string
): Promise<MultimodalSearchResponse> {
  // 1. Detect faces & extract visual signals
  const faceResult = await detectFacesInImage(imageInput, { sourceId: 'query' });
  const visualEmbedding = await getImageEmbedding(imageInput);

  const faceEmbeddings: number[][] = [];
  for (const f of faceResult.faces) {
    if (f.embedding) faceEmbeddings.push(f.embedding);
  }

  const signals: ParsedQuerySignals = {
    queryType: 'image',
    previewUrl: queryPreviewUrl,
    hasFace: faceResult.hasFace,
    faces: faceResult.faces,
    primaryFace: faceResult.primaryFace,
    faceEmbeddings,
    visualEmbedding,
    ocrText: faceResult.ocrText,
    visualDescription: faceResult.visualDescription,
    extractedEntities: faceResult.identifiedNames || [],
    derivedSearchKeywords: (faceResult.identifiedNames || []).join(' ') || faceResult.ocrText?.slice(0, 100) || '',
  };

  return searchByMultimodalSignals(signals);
}

/**
 * High-Precision Hybrid Text Search: searches documents, video/audio transcripts, images, and video frames
 */
export async function searchByText(query: string): Promise<MultimodalSearchResponse> {
  const cleanQuery = query.trim();
  const queryTokens = extractQueryTokens(cleanQuery);
  console.log(`[MultimodalRetrieval] Executing high-precision search for "${cleanQuery}" with tokens: [${queryTokens.join(', ')}]`);

  // 1. Generate text embedding & multimodal text embedding
  const [textVector, clipTextVector] = await Promise.all([
    getTextEmbedding(cleanQuery),
    getMultimodalTextEmbedding(cleanQuery),
  ]);

  const localDocuments: MultimodalSearchResultItem[] = [];
  const localVideos: MultimodalSearchResultItem[] = [];
  const localAudio: MultimodalSearchResultItem[] = [];
  const localImages: MultimodalSearchResultItem[] = [];

  const seenSourceIds = new Set<string>();

  // A. Direct source title matching
  const allSources = dbAll<{
    id: string;
    original_name: string;
    file_type: string;
    file_size: number;
    upload_date: string;
    page_count?: number;
    chunk_count?: number;
    duration_seconds?: number;
  }>('SELECT * FROM knowledge_sources');

  const titleMatchedSourceIds = new Set<string>();
  const titleScores = new Map<string, number>();

  for (const src of allSources) {
    const lowerTitle = (src.original_name || '').toLowerCase();
    const titleTokens = extractQueryTokens(lowerTitle);
    
    const matchedTokens = queryTokens.filter((qt) => lowerTitle.includes(qt) || titleTokens.some((tt) => tt.includes(qt)));
    const matchRatio = queryTokens.length > 0 ? matchedTokens.length / queryTokens.length : 0;

    if (matchRatio > 0) {
      titleMatchedSourceIds.add(src.id);
      const score = matchRatio === 1.0 ? 0.98 : 0.70 + matchRatio * 0.25;
      titleScores.set(src.id, score);
    }
  }

  // B. Document chunks retrieval
  const chunkKeywordResults = searchDocumentChunks(cleanQuery, 50);
  const chunkScores = new Map<string, number>();

  for (const cr of chunkKeywordResults) {
    chunkScores.set(cr.id, cr.score);
  }

  const docChunkRows = dbAll<{
    id: string;
    doc_id: string;
    source_id: string;
    section_id: string | null;
    chunk_text: string;
    page_num: number;
    embedding: Buffer | null;
  }>('SELECT id, doc_id, source_id, section_id, chunk_text, page_num, embedding FROM document_chunks LIMIT 300');

  const scoredChunks: Array<{
    id: string;
    sourceId: string;
    text: string;
    pageNum: number;
    score: number;
  }> = [];

  for (const chunk of docChunkRows) {
    const keywordScore = chunkScores.get(chunk.id) || 0;
    const lowerText = chunk.chunk_text.toLowerCase();
    const chunkTokens = extractQueryTokens(lowerText);

    const matchedTokens = queryTokens.filter((qt) => lowerText.includes(qt) || chunkTokens.some((ct) => ct.includes(qt)));
    const tokenRatio = queryTokens.length > 0 ? matchedTokens.length / queryTokens.length : 0;

    let vectorScore = 0;
    if (chunk.embedding) {
      const storedVec = blobToFloatArray(chunk.embedding);
      vectorScore = cosineSimilarity(textVector, storedVec);
    }

    const titleScore = titleScores.get(chunk.source_id) || 0;

    if (queryTokens.length >= 2 && tokenRatio === 0 && titleScore === 0 && vectorScore < 0.70) {
      continue;
    }

    let entityPenalty = 1.0;
    if (queryTokens.length >= 2 && tokenRatio < 0.5 && titleScore === 0) {
      entityPenalty = 0.4;
    }

    let finalScore = 0;
    if (titleScore > 0) {
      finalScore = Math.max(titleScore, keywordScore * 0.4 + vectorScore * 0.4 + 0.3);
    } else if (tokenRatio === 1.0) {
      finalScore = Math.max(0.85, vectorScore * 0.5 + keywordScore * 0.5);
    } else {
      finalScore = (vectorScore * 0.5 + keywordScore * 0.5) * entityPenalty;
    }

    if (finalScore >= 0.48) {
      scoredChunks.push({
        id: chunk.id,
        sourceId: chunk.source_id,
        text: chunk.chunk_text,
        pageNum: chunk.page_num,
        score: finalScore,
      });
    }
  }

  // Direct title-matched documents
  for (const srcId of titleMatchedSourceIds) {
    const src = allSources.find((s) => s.id === srcId);
    if (src && DOCUMENT_EXTENSIONS.has((src.file_type || '').toLowerCase())) {
      const alreadyScored = scoredChunks.some((sc) => sc.sourceId === srcId);
      if (!alreadyScored) {
        const firstChunk = dbGet<{ id: string; chunk_text: string; page_num: number }>(
          'SELECT id, chunk_text, page_num FROM document_chunks WHERE source_id = ? ORDER BY chunk_order ASC LIMIT 1',
          [srcId]
        );
        scoredChunks.push({
          id: firstChunk?.id || `title-match-${srcId}`,
          sourceId: srcId,
          text: firstChunk?.chunk_text || src.original_name,
          pageNum: firstChunk?.page_num || 1,
          score: titleScores.get(srcId) || 0.95,
        });
      }
    }
  }

  scoredChunks.sort((a, b) => b.score - a.score);

  for (const sc of scoredChunks) {
    if (seenSourceIds.has(sc.sourceId)) continue;
    seenSourceIds.add(sc.sourceId);

    const expanded = expandDocumentChunk(sc.id, sc.score);
    const src = dbGet<{
      id: string;
      original_name: string;
      file_type: string;
      file_size: number;
      upload_date: string;
      page_count?: number;
      chunk_count?: number;
    }>('SELECT * FROM knowledge_sources WHERE id = ?', [sc.sourceId]);

    if (src && DOCUMENT_EXTENSIONS.has((src.file_type || '').toLowerCase())) {
      localDocuments.push({
        id: sc.id,
        sourceId: src.id,
        category: 'document',
        title: expanded?.fullDocTitle || src.original_name,
        originalName: src.original_name,
        fileType: src.file_type,
        fileSize: src.file_size,
        uploadDate: src.upload_date,
        pageCount: src.page_count || 1,
        sectionTitle: expanded?.sectionTitle || 'Document Overview',
        snippet: (expanded?.sectionText || sc.text).slice(0, 450),
        fullContext: expanded?.sectionText || sc.text,
        pageNum: expanded?.pageNum || sc.pageNum || 1,
        relevanceScore: Math.round(sc.score * 100) / 100,
      });
    }
  }

  // C. Video & Audio Transcripts Retrieval
  const transcriptKeywordResults = searchTranscripts(cleanQuery, 40);
  const transcriptScores = new Map<string, number>();

  for (const tr of transcriptKeywordResults) {
    transcriptScores.set(tr.id, tr.score);
  }

  const transcriptRows = dbAll<{
    id: string;
    video_id: string;
    source_id: string;
    start_time: number;
    end_time: number;
    text: string;
    embedding: Buffer | null;
  }>('SELECT id, video_id, source_id, start_time, end_time, text, embedding FROM video_transcripts LIMIT 300');

  const scoredTranscripts: Array<{
    id: string;
    videoId: string;
    sourceId: string;
    startTime: number;
    endTime: number;
    text: string;
    score: number;
  }> = [];

  for (const tr of transcriptRows) {
    const keywordScore = transcriptScores.get(tr.id) || 0;
    const lowerText = tr.text.toLowerCase();
    const chunkTokens = extractQueryTokens(lowerText);
    const matchedTokens = queryTokens.filter((qt) => lowerText.includes(qt) || chunkTokens.some((ct) => ct.includes(qt)));
    const tokenRatio = queryTokens.length > 0 ? matchedTokens.length / queryTokens.length : 0;

    let vectorScore = 0;
    if (tr.embedding) {
      const storedVec = blobToFloatArray(tr.embedding);
      vectorScore = cosineSimilarity(textVector, storedVec);
    }

    const titleScore = titleScores.get(tr.source_id) || 0;

    if (queryTokens.length >= 2 && tokenRatio === 0 && titleScore === 0 && vectorScore < 0.70) {
      continue;
    }

    let entityPenalty = 1.0;
    if (queryTokens.length >= 2 && tokenRatio < 0.5 && titleScore === 0) {
      entityPenalty = 0.4;
    }

    let finalScore = 0;
    if (titleScore > 0) {
      finalScore = Math.max(titleScore, keywordScore * 0.4 + vectorScore * 0.4 + 0.3);
    } else if (tokenRatio === 1.0) {
      finalScore = Math.max(0.85, vectorScore * 0.5 + keywordScore * 0.5);
    } else {
      finalScore = (vectorScore * 0.5 + keywordScore * 0.5) * entityPenalty;
    }

    if (finalScore >= 0.45) {
      scoredTranscripts.push({
        id: tr.id,
        videoId: tr.video_id,
        sourceId: tr.source_id,
        startTime: tr.start_time,
        endTime: tr.end_time,
        text: tr.text,
        score: finalScore,
      });
    }
  }

  scoredTranscripts.sort((a, b) => b.score - a.score);

  for (const str of scoredTranscripts) {
    if (seenSourceIds.has(str.sourceId)) continue;
    seenSourceIds.add(str.sourceId);

    const expanded = expandTranscriptSegment(str.id, str.score);
    const src = dbGet<{
      id: string;
      original_name: string;
      file_type: string;
      file_size: number;
      upload_date: string;
      duration_seconds?: number;
    }>('SELECT * FROM knowledge_sources WHERE id = ?', [str.sourceId]);

    if (!src) continue;

    const ext = (src.file_type || '').toLowerCase();
    const isAudio = AUDIO_EXTENSIONS.has(ext);

    let matchingFrames: MatchingFrame[] = [];
    if (!isAudio) {
      const frames = dbAll<{
        id: string;
        frame_number: number;
        scene_id: number;
        timestamp: number;
        frame_path: string;
        visual_description: string | null;
      }>(
        `SELECT * FROM video_frames
         WHERE video_id = ? AND timestamp BETWEEN ? AND ?
         ORDER BY timestamp ASC LIMIT 4`,
        [str.videoId, Math.max(0, str.startTime - 15), str.endTime + 15]
      );

      matchingFrames = frames.map((f) => ({
        id: f.id,
        frameNumber: f.frame_number || 1,
        sceneId: f.scene_id || 1,
        timestamp: f.timestamp,
        framePath: f.frame_path,
        similarity: Math.round(str.score * 100) / 100,
        visualDescription: f.visual_description || undefined,
      }));
    }

    const item: MultimodalSearchResultItem = {
      id: `tr-${str.id}`,
      sourceId: src.id,
      category: isAudio ? 'audio' : 'video',
      title: src.original_name,
      originalName: src.original_name,
      fileType: src.file_type,
      fileSize: src.file_size,
      uploadDate: src.upload_date,
      duration: src.duration_seconds,
      startTime: str.startTime,
      endTime: str.endTime,
      snippet: (expanded?.transcriptText || str.text).slice(0, 450),
      fullContext: expanded?.transcriptText || str.text,
      relevanceScore: Math.round(str.score * 100) / 100,
      matchingFrames: matchingFrames.length > 0 ? matchingFrames : undefined,
      primaryFrame: matchingFrames[0] || undefined,
    };

    if (isAudio) {
      localAudio.push(item);
    } else {
      localVideos.push(item);
    }
  }

  // D. Image & Video Keyframe Retrieval (CLIP Text Vector -> Visual Match)
  const imageRows = dbAll<{
    id: string;
    source_id: string;
    description: string | null;
    ocr_text: string | null;
    embedding: Buffer | null;
  }>('SELECT id, source_id, description, ocr_text, embedding FROM images');

  for (const img of imageRows) {
    if (seenSourceIds.has(img.source_id)) continue;

    let vectorScore = 0;
    if (img.embedding) {
      const storedVec = blobToFloatArray(img.embedding);
      vectorScore = cosineSimilarity(clipTextVector, storedVec);
    }

    const lowerDesc = (img.description || '').toLowerCase();
    const lowerOcr = (img.ocr_text || '').toLowerCase();
    const tokenMatch = queryTokens.some((qt) => lowerDesc.includes(qt) || lowerOcr.includes(qt));
    const titleScore = titleScores.get(img.source_id) || 0;

    let score = vectorScore;
    if (titleScore > 0) {
      score = Math.max(titleScore, vectorScore);
    } else if (tokenMatch) {
      score = Math.max(vectorScore, 0.85);
    }

    if (score >= 0.48) {
      seenSourceIds.add(img.source_id);
      const src = dbGet<{
        id: string;
        original_name: string;
        file_type: string;
        file_size: number;
        upload_date: string;
      }>('SELECT * FROM knowledge_sources WHERE id = ?', [img.source_id]);

      if (src) {
        const snippet = img.description || img.ocr_text || `Visual Match (${Math.round(score * 100)}%)`;

        localImages.push({
          id: `img-${img.id}`,
          sourceId: src.id,
          category: 'image',
          title: src.original_name,
          originalName: src.original_name,
          fileType: src.file_type,
          fileSize: src.file_size,
          uploadDate: src.upload_date,
          snippet,
          thumbnail: `/api/knowledge/${src.id}/file`,
          description: img.description || undefined,
          ocrText: img.ocr_text || undefined,
          relevanceScore: Math.round(score * 100) / 100,
        });
      }
    }
  }

  localDocuments.sort((a, b) => b.relevanceScore - a.relevanceScore);
  localVideos.sort((a, b) => b.relevanceScore - a.relevanceScore);
  localAudio.sort((a, b) => b.relevanceScore - a.relevanceScore);
  localImages.sort((a, b) => b.relevanceScore - a.relevanceScore);

  const total = localDocuments.length + localVideos.length + localAudio.length + localImages.length;

  return {
    query: cleanQuery,
    queryType: 'text',
    documents: localDocuments,
    videos: localVideos,
    audio: localAudio,
    images: localImages,
    total,
  };
}
