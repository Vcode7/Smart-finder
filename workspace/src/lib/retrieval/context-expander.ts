// src/lib/retrieval/context-expander.ts
// Stage 2: Given a relevant chunk, retrieve the full meaningful context around it

import { dbGet, dbAll } from '@/lib/db/client';

export interface ExpandedContext {
  chunkId: string;
  sourceId: string;
  docId?: string;
  videoId?: string;
  type: 'document' | 'transcript';
  // For documents
  sectionTitle?: string;
  sectionText?: string;
  neighboringChunks?: string[];
  fullDocTitle?: string;
  pageNum?: number;
  // For transcripts
  transcriptText?: string;
  startTime?: number;
  endTime?: number;
  // Metadata
  sourceName?: string;
  relevanceScore: number;
}

const MAX_SECTION_CHARS = 6000;
const NEIGHBORING_CHUNKS = 2; // chunks before and after

/** Expand a document chunk to its parent section + neighboring chunks */
export function expandDocumentChunk(chunkId: string, relevanceScore: number): ExpandedContext | null {
  const chunk = dbGet<{
    id: string;
    section_id: string;
    doc_id: string;
    source_id: string;
    chunk_text: string;
    chunk_order: number;
    page_num: number;
  }>('SELECT * FROM document_chunks WHERE id = ?', [chunkId]);

  if (!chunk) return null;

  const doc = dbGet<{ title: string }>(
    'SELECT title FROM documents WHERE id = ?', [chunk.doc_id]
  );

  const source = dbGet<{ original_name: string }>(
    'SELECT original_name FROM knowledge_sources WHERE id = ?', [chunk.source_id]
  );

  let sectionTitle = '';
  let sectionText = '';

  if (chunk.section_id) {
    const section = dbGet<{ section_title: string; section_text: string }>(
      'SELECT section_title, section_text FROM document_sections WHERE id = ?',
      [chunk.section_id]
    );
    if (section) {
      sectionTitle = section.section_title;
      // Use section text if not too long, otherwise use neighboring chunks
      if (section.section_text.length <= MAX_SECTION_CHARS) {
        sectionText = section.section_text;
      }
    }
  }

  // Get neighboring chunks if section text is too long or no section
  const neighboringChunks: string[] = [];
  if (!sectionText) {
    const neighbors = dbAll<{ chunk_text: string }>(
      `SELECT chunk_text FROM document_chunks
       WHERE doc_id = ? AND chunk_order BETWEEN ? AND ?
       ORDER BY chunk_order ASC`,
      [chunk.doc_id, chunk.chunk_order - NEIGHBORING_CHUNKS, chunk.chunk_order + NEIGHBORING_CHUNKS]
    );
    neighboringChunks.push(...neighbors.map((n) => n.chunk_text));
  }

  return {
    chunkId,
    sourceId: chunk.source_id,
    docId: chunk.doc_id,
    type: 'document',
    sectionTitle,
    sectionText: sectionText || neighboringChunks.join('\n\n'),
    neighboringChunks,
    fullDocTitle: doc?.title,
    pageNum: chunk.page_num,
    sourceName: source?.original_name,
    relevanceScore,
  };
}

/** Expand a transcript segment to surrounding context */
export function expandTranscriptSegment(transcriptId: string, relevanceScore: number): ExpandedContext | null {
  const segment = dbGet<{
    id: string;
    video_id: string;
    source_id: string;
    text: string;
    start_time: number;
    end_time: number;
  }>('SELECT * FROM video_transcripts WHERE id = ?', [transcriptId]);

  if (!segment) return null;

  const source = dbGet<{ original_name: string }>(
    'SELECT original_name FROM knowledge_sources WHERE id = ?', [segment.source_id]
  );

  // Get surrounding transcript segments (±30 seconds context)
  const surrounding = dbAll<{ text: string; start_time: number }>(
    `SELECT text, start_time FROM video_transcripts
     WHERE video_id = ? AND start_time BETWEEN ? AND ?
     ORDER BY start_time ASC`,
    [segment.video_id, segment.start_time - 30, segment.end_time + 30]
  );

  const contextText = surrounding.map((s) => s.text).join(' ');

  return {
    chunkId: transcriptId,
    sourceId: segment.source_id,
    videoId: segment.video_id,
    type: 'transcript',
    transcriptText: contextText || segment.text,
    startTime: segment.start_time,
    endTime: segment.end_time,
    sourceName: source?.original_name,
    relevanceScore,
  };
}

/** Format expanded context for LLM consumption */
export function buildContextString(contexts: ExpandedContext[], maxChars = 12000): string {
  let result = '';
  let chars = 0;

  for (const ctx of contexts) {
    if (chars >= maxChars) break;

    if (ctx.type === 'document') {
      const header = `### 📄 ${ctx.fullDocTitle || ctx.sourceName || 'Document'}${ctx.sectionTitle ? ` — ${ctx.sectionTitle}` : ''}${ctx.pageNum ? ` (p.${ctx.pageNum})` : ''}\n`;
      const body = ctx.sectionText || ctx.neighboringChunks?.join('\n\n') || '';
      const snippet = body.slice(0, maxChars - chars - header.length);
      result += header + snippet + '\n\n---\n\n';
      chars += header.length + snippet.length;
    } else if (ctx.type === 'transcript') {
      const ts = formatTimestamp(ctx.startTime || 0);
      const header = `### 🎥 ${ctx.sourceName || 'Video'} [${ts}]\n`;
      const body = ctx.transcriptText || '';
      const snippet = body.slice(0, maxChars - chars - header.length);
      result += header + snippet + '\n\n---\n\n';
      chars += header.length + snippet.length;
    }
  }

  return result;
}

function formatTimestamp(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}
