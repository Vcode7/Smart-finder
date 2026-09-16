// src/lib/knowledge/document-processor.ts
// Processes PDF, DOCX, TXT, MD, CSV, XLSX into structured chunks with full hierarchy and text vector embeddings

import path from 'path';
import fs from 'fs';
import { v4 as uuidv4 } from 'uuid';
import { dbTransaction } from '@/lib/db/client';
import { getTextEmbedding, floatArrayToBuffer } from '@/lib/embeddings/multimodal-embeddings';

export interface DocumentChunk {
  id: string;
  sectionId: string | null;
  docId: string;
  sourceId: string;
  chunkText: string;
  chunkOrder: number;
  pageNum: number;
}

export interface ProcessedDocument {
  docId: string;
  title: string;
  fullText: string;
  pageCount: number;
  sections: Array<{
    id: string;
    title: string;
    text: string;
    pageNum: number;
    chunks: DocumentChunk[];
  }>;
}

const CHUNK_SIZE = 800; // characters
const CHUNK_OVERLAP = 150;

/** Splits text into overlapping chunks */
function chunkText(text: string, sourceId: string, docId: string, sectionId: string | null, pageNum: number, startOrder: number): DocumentChunk[] {
  const chunks: DocumentChunk[] = [];
  let i = 0;
  let order = startOrder;

  while (i < text.length) {
    const end = Math.min(i + CHUNK_SIZE, text.length);
    const chunkText = text.slice(i, end).trim();
    if (chunkText.length > 30) {
      chunks.push({
        id: uuidv4(),
        sectionId,
        docId,
        sourceId,
        chunkText,
        chunkOrder: order++,
        pageNum,
      });
    }
    if (end === text.length) break;
    i += CHUNK_SIZE - CHUNK_OVERLAP;
  }
  return chunks;
}

/** Extract text from PDF using pdf-parse */
async function extractPDF(filePath: string): Promise<{ text: string; pages: string[]; pageCount: number }> {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const pdfModule = require('pdf-parse');
  const buffer = fs.readFileSync(filePath);

  if (pdfModule.PDFParse) {
    const parser = new pdfModule.PDFParse({ data: buffer });
    const data = await parser.getText();
    const pages: string[] = data.pages && data.pages.length > 0
      ? data.pages.map((p: { text: string }) => p.text)
      : [data.text || ''];
    return {
      text: data.text || pages.join('\n\n'),
      pages,
      pageCount: data.total || pages.length,
    };
  } else if (typeof pdfModule === 'function') {
    const data = await pdfModule(buffer);
    const pages: string[] = data.text.includes('\f')
      ? data.text.split('\f').filter((p: string) => p.trim().length > 0)
      : [data.text];
    return { text: data.text, pages, pageCount: data.numpages || pages.length };
  } else if (pdfModule.default && typeof pdfModule.default === 'function') {
    const data = await pdfModule.default(buffer);
    const pages: string[] = [data.text];
    return { text: data.text, pages, pageCount: data.numpages || 1 };
  }

  return { text: '', pages: [], pageCount: 1 };
}

/** Extract text from DOCX using mammoth */
async function extractDOCX(filePath: string): Promise<{ text: string; pages: string[] }> {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const mammoth = require('mammoth');
  const result = await mammoth.extractRawText({ path: filePath });
  return { text: result.value, pages: [result.value] };
}

/** Extract text from CSV using csv-parse */
async function extractCSV(filePath: string): Promise<{ text: string; pages: string[] }> {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { parse } = require('csv-parse/sync');
  const content = fs.readFileSync(filePath, 'utf-8');
  const records = parse(content, { columns: true, skip_empty_lines: true });
  const text = records.map((row: Record<string, string>) =>
    Object.entries(row).map(([k, v]) => `${k}: ${v}`).join(' | ')
  ).join('\n');
  return { text, pages: [text] };
}

/** Extract text from XLSX */
async function extractXLSX(filePath: string): Promise<{ text: string; pages: string[] }> {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const XLSX = require('xlsx');
  const workbook = XLSX.readFile(filePath);
  const texts: string[] = [];
  for (const sheetName of workbook.SheetNames) {
    const sheet = workbook.Sheets[sheetName];
    const csv = XLSX.utils.sheet_to_csv(sheet);
    texts.push(`## Sheet: ${sheetName}\n${csv}`);
  }
  const text = texts.join('\n\n');
  return { text, pages: texts };
}

/** Extract plain text from TXT/MD */
async function extractText(filePath: string): Promise<{ text: string; pages: string[] }> {
  const text = fs.readFileSync(filePath, 'utf-8');
  return { text, pages: [text] };
}

/** Parse sections from text using heading patterns */
function parseSections(text: string): Array<{ title: string; text: string; pageNum: number }> {
  const lines = text.split('\n');
  const sections: Array<{ title: string; text: string; pageNum: number }> = [];
  let currentTitle = 'Introduction';
  let currentLines: string[] = [];

  for (const line of lines) {
    if (/^#{1,3}\s+.+/.test(line) || /^[A-Z][A-Z\s]{5,}$/.test(line.trim())) {
      if (currentLines.join('\n').trim().length > 50) {
        sections.push({ title: currentTitle, text: currentLines.join('\n').trim(), pageNum: 1 });
      }
      currentTitle = line.replace(/^#+\s+/, '').trim();
      currentLines = [];
    } else {
      currentLines.push(line);
    }
  }

  if (currentLines.join('\n').trim().length > 50) {
    sections.push({ title: currentTitle, text: currentLines.join('\n').trim(), pageNum: 1 });
  }

  if (sections.length === 0) {
    sections.push({ title: 'Content', text: text, pageNum: 1 });
  }

  return sections;
}

/** Main document processing function */
export async function processDocument(
  sourceId: string,
  filePath: string,
  fileType: string,
  originalName: string
): Promise<ProcessedDocument> {
  let extracted: { text: string; pages: string[]; pageCount?: number };

  const ext = fileType.toLowerCase();
  if (ext === 'pdf') {
    extracted = await extractPDF(filePath);
  } else if (ext === 'docx' || ext === 'doc') {
    extracted = await extractDOCX(filePath);
  } else if (ext === 'csv') {
    extracted = await extractCSV(filePath);
  } else if (ext === 'xlsx' || ext === 'xls') {
    extracted = await extractXLSX(filePath);
  } else {
    extracted = await extractText(filePath);
  }

  const title = path.basename(originalName, path.extname(originalName));
  const docId = uuidv4();
  const sections = parseSections(extracted.text);
  const pageCount = extracted.pageCount || extracted.pages.length;

  const result: ProcessedDocument = {
    docId,
    title,
    fullText: extracted.text,
    pageCount,
    sections: [],
  };

  // Collect all chunks and compute embeddings
  const allChunkInserts: Array<{
    chunk: DocumentChunk;
    embeddingBuffer: Buffer | null;
  }> = [];

  for (let si = 0; si < sections.length; si++) {
    const sec = sections[si];
    const sectionId = uuidv4();
    const chunks = chunkText(sec.text, sourceId, docId, sectionId, sec.pageNum, allChunkInserts.length);
    result.sections.push({ id: sectionId, title: sec.title, text: sec.text, pageNum: sec.pageNum, chunks });

    for (const chunk of chunks) {
      let embeddingBuffer: Buffer | null = null;
      try {
        const vec = await getTextEmbedding(chunk.chunkText);
        if (vec && vec.length > 0) {
          embeddingBuffer = floatArrayToBuffer(vec);
        }
      } catch (err) {
        console.warn('[DocumentProcessor] Chunk embedding warning:', err);
      }
      allChunkInserts.push({ chunk, embeddingBuffer });
    }
  }

  // Store in DB in a transaction
  dbTransaction((db) => {
    // Clear any previous records for this sourceId
    try {
      db.prepare('DELETE FROM documents WHERE source_id = ?').run(sourceId);
      db.prepare('DELETE FROM document_sections WHERE source_id = ?').run(sourceId);
      db.prepare('DELETE FROM document_chunks WHERE source_id = ?').run(sourceId);
      db.prepare('DELETE FROM chunks_fts WHERE source_id = ?').run(sourceId);
    } catch {
      // Ignore
    }

    // Insert document
    db.prepare(`
      INSERT OR REPLACE INTO documents (id, source_id, title, full_text, page_count, section_count)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run(docId, sourceId, title, extracted.text, pageCount, sections.length);

    for (let si = 0; si < result.sections.length; si++) {
      const sec = result.sections[si];
      db.prepare(`
        INSERT OR REPLACE INTO document_sections (id, doc_id, source_id, section_title, section_text, page_num, order_idx)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      `).run(sec.id, docId, sourceId, sec.title, sec.text, sec.pageNum, si);
    }

    for (const item of allChunkInserts) {
      db.prepare(`
        INSERT INTO document_chunks (id, section_id, doc_id, source_id, chunk_text, chunk_order, page_num, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      `).run(
        item.chunk.id,
        item.chunk.sectionId,
        item.chunk.docId,
        item.chunk.sourceId,
        item.chunk.chunkText,
        item.chunk.chunkOrder,
        item.chunk.pageNum,
        item.embeddingBuffer
      );

      // Insert into FTS index if available
      try {
        db.prepare(`
          INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id)
          VALUES (?, ?, ?, ?)
        `).run(item.chunk.chunkText, item.chunk.id, item.chunk.sourceId, item.chunk.docId);
      } catch {
        // Handled
      }
    }

    // Update source status and chunk count
    db.prepare(`
      UPDATE knowledge_sources SET processing_status = 'completed', chunk_count = ?, page_count = ? WHERE id = ?
    `).run(allChunkInserts.length, pageCount, sourceId);
  });

  console.log(`[DocumentProcessor] Processed ${title}: ${sections.length} sections, ${allChunkInserts.length} chunks indexed with embeddings`);
  return result;
}
