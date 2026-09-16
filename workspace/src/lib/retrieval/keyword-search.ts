// src/lib/retrieval/keyword-search.ts
// Precision keyword search over document chunks and video transcripts (FTS5 with strict token matching + LIKE fallback)

import { dbAll } from '@/lib/db/client';

export interface KeywordResult {
  id: string;
  text: string;
  sourceId: string;
  docId?: string;
  videoId?: string;
  startTime?: number;
  endTime?: number;
  pageNum?: number;
  type: 'chunk' | 'transcript';
  score: number;
}

const STOPWORDS = new Set([
  'a', 'an', 'the', 'is', 'are', 'was', 'were', 'and', 'or', 'but', 'if', 'in', 'on',
  'at', 'to', 'for', 'with', 'about', 'against', 'between', 'into', 'through', 'during',
  'before', 'after', 'above', 'below', 'from', 'up', 'down', 'of', 'off', 'over', 'under',
  'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how',
  'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
  'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'can', 'will', 'just',
  'don', 'should', 'now', 'this', 'that', 'these', 'those'
]);

function extractQueryTokens(query: string): string[] {
  return query
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((w) => w.length >= 2 && !STOPWORDS.has(w));
}

/** Search document chunks using FTS5 with strict AND matching first, then fallback */
export function searchDocumentChunks(query: string, limit = 20): KeywordResult[] {
  if (!query?.trim()) return [];

  const tokens = extractQueryTokens(query);
  if (tokens.length === 0) return [];

  // 1. Try strict FTS5 AND query first (e.g. "neet"* AND "scam"*)
  if (tokens.length > 1) {
    const strictFtsQuery = tokens.map((t) => `"${t}"*`).join(' AND ');
    try {
      const rows = dbAll<{
        chunk_id: string;
        chunk_text: string;
        source_id: string;
        doc_id: string;
        rank: number;
      }>(
        `SELECT chunk_id, chunk_text, source_id, doc_id, rank
         FROM chunks_fts
         WHERE chunk_text MATCH ?
         ORDER BY rank
         LIMIT ?`,
        [strictFtsQuery, limit]
      );

      if (rows && rows.length > 0) {
        return rows.map((row, i) => ({
          id: row.chunk_id,
          text: row.chunk_text,
          sourceId: row.source_id,
          docId: row.doc_id,
          type: 'chunk' as const,
          score: Math.max(0.7, 1 - i / limit),
        }));
      }
    } catch {
      // ignore
    }
  }

  // 2. Try standard FTS5 query
  try {
    const ftsQuery = tokens.map((t) => `"${t}"*`).join(' OR ');
    const rows = dbAll<{
      chunk_id: string;
      chunk_text: string;
      source_id: string;
      doc_id: string;
      rank: number;
    }>(
      `SELECT chunk_id, chunk_text, source_id, doc_id, rank
       FROM chunks_fts
       WHERE chunk_text MATCH ?
       ORDER BY rank
       LIMIT ?`,
      [ftsQuery, limit]
    );

    if (rows && rows.length > 0) {
      // Score by matching token count
      return rows.map((row, i) => {
        const lowerText = row.chunk_text.toLowerCase();
        const matched = tokens.filter((t) => lowerText.includes(t));
        const tokenRatio = matched.length / tokens.length;
        return {
          id: row.chunk_id,
          text: row.chunk_text,
          sourceId: row.source_id,
          docId: row.doc_id,
          type: 'chunk' as const,
          score: Math.max(0.4, (tokenRatio * 0.8) + (1 - i / limit) * 0.2),
        };
      });
    }
  } catch {
    // ignore
  }

  // 3. Fallback: search document_chunks directly with LIKE
  try {
    const likeConditions = tokens.map(() => 'chunk_text LIKE ?').join(' AND ');
    const params = tokens.map((t) => `%${t}%`);

    let rows = dbAll<{
      id: string;
      chunk_text: string;
      source_id: string;
      doc_id: string;
      page_num: number;
    }>(
      `SELECT id, chunk_text, source_id, doc_id, page_num
       FROM document_chunks
       WHERE ${likeConditions}
       LIMIT ?`,
      [...params, limit]
    );

    if (!rows || rows.length === 0) {
      // Fallback to OR LIKE
      const orConditions = tokens.map(() => 'chunk_text LIKE ?').join(' OR ');
      rows = dbAll<{
        id: string;
        chunk_text: string;
        source_id: string;
        doc_id: string;
        page_num: number;
      }>(
        `SELECT id, chunk_text, source_id, doc_id, page_num
         FROM document_chunks
         WHERE ${orConditions}
         LIMIT ?`,
        [...params, limit]
      );
    }

    return rows.map((row, i) => {
      const lowerText = row.chunk_text.toLowerCase();
      const matched = tokens.filter((t) => lowerText.includes(t));
      const tokenRatio = matched.length / tokens.length;
      return {
        id: row.id,
        text: row.chunk_text,
        sourceId: row.source_id,
        docId: row.doc_id,
        pageNum: row.page_num,
        type: 'chunk' as const,
        score: Math.max(0.4, tokenRatio * 0.9),
      };
    });
  } catch (err) {
    console.error('[KeywordSearch] Document search error:', err);
    return [];
  }
}

/** Search video transcripts using FTS5 with strict token matching + LIKE fallback */
export function searchTranscripts(query: string, limit = 20): KeywordResult[] {
  if (!query?.trim()) return [];

  const tokens = extractQueryTokens(query);
  if (tokens.length === 0) return [];

  // 1. Try strict FTS5 AND query first
  if (tokens.length > 1) {
    const strictFtsQuery = tokens.map((t) => `"${t}"*`).join(' AND ');
    try {
      const rows = dbAll<{
        transcript_id: string;
        text: string;
        video_id: string;
        source_id: string;
        start_time: number;
        end_time: number;
        rank: number;
      }>(
        `SELECT transcript_id, text, video_id, source_id, start_time, end_time, rank
         FROM transcripts_fts
         WHERE text MATCH ?
         ORDER BY rank
         LIMIT ?`,
        [strictFtsQuery, limit]
      );

      if (rows && rows.length > 0) {
        return rows.map((row, i) => ({
          id: row.transcript_id,
          text: row.text,
          sourceId: row.source_id,
          videoId: row.video_id,
          startTime: row.start_time,
          endTime: row.end_time,
          type: 'transcript' as const,
          score: Math.max(0.7, 1 - i / limit),
        }));
      }
    } catch {
      // ignore
    }
  }

  // 2. Try standard FTS5 query
  try {
    const ftsQuery = tokens.map((t) => `"${t}"*`).join(' OR ');
    const rows = dbAll<{
      transcript_id: string;
      text: string;
      video_id: string;
      source_id: string;
      start_time: number;
      end_time: number;
      rank: number;
    }>(
      `SELECT transcript_id, text, video_id, source_id, start_time, end_time, rank
       FROM transcripts_fts
       WHERE text MATCH ?
       ORDER BY rank
       LIMIT ?`,
      [ftsQuery, limit]
    );

    if (rows && rows.length > 0) {
      return rows.map((row, i) => {
        const lowerText = row.text.toLowerCase();
        const matched = tokens.filter((t) => lowerText.includes(t));
        const tokenRatio = matched.length / tokens.length;
        return {
          id: row.transcript_id,
          text: row.text,
          sourceId: row.source_id,
          videoId: row.video_id,
          startTime: row.start_time,
          endTime: row.end_time,
          type: 'transcript' as const,
          score: Math.max(0.4, (tokenRatio * 0.8) + (1 - i / limit) * 0.2),
        };
      });
    }
  } catch {
    // ignore
  }

  // 3. Fallback: search video_transcripts directly with LIKE
  try {
    const likeConditions = tokens.map(() => 'text LIKE ?').join(' AND ');
    const params = tokens.map((t) => `%${t}%`);

    let rows = dbAll<{
      id: string;
      text: string;
      video_id: string;
      source_id: string;
      start_time: number;
      end_time: number;
    }>(
      `SELECT id, text, video_id, source_id, start_time, end_time
       FROM video_transcripts
       WHERE ${likeConditions}
       LIMIT ?`,
      [...params, limit]
    );

    if (!rows || rows.length === 0) {
      const orConditions = tokens.map(() => 'text LIKE ?').join(' OR ');
      rows = dbAll<{
        id: string;
        text: string;
        video_id: string;
        source_id: string;
        start_time: number;
        end_time: number;
      }>(
        `SELECT id, text, video_id, source_id, start_time, end_time
         FROM video_transcripts
         WHERE ${orConditions}
         LIMIT ?`,
        [...params, limit]
      );
    }

    return rows.map((row, i) => {
      const lowerText = row.text.toLowerCase();
      const matched = tokens.filter((t) => lowerText.includes(t));
      const tokenRatio = matched.length / tokens.length;
      return {
        id: row.id,
        text: row.text,
        sourceId: row.source_id,
        videoId: row.video_id,
        startTime: row.start_time,
        endTime: row.end_time,
        type: 'transcript' as const,
        score: Math.max(0.4, tokenRatio * 0.9),
      };
    });
  } catch (err) {
    console.error('[KeywordSearch] Transcript search error:', err);
    return [];
  }
}
