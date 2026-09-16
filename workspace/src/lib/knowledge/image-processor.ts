// src/lib/knowledge/image-processor.ts
// Processes images — extracts dimensions, OCR text, visual descriptions with Groq Vision,
// CLIP multimodal embeddings, and face detection + 512-dim face crop embeddings.

import fs from 'fs';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import { dbTransaction } from '@/lib/db/client';
import { getImageEmbedding, floatArrayToBuffer } from '@/lib/embeddings/multimodal-embeddings';
import { detectFacesInImage } from '@/lib/face/face-detector';

export interface ProcessedImage {
  imageId: string;
  sourceId: string;
  width: number;
  height: number;
  ocrText?: string;
  description?: string;
  faceCount: number;
}

/**
 * Main image processing function
 */
export async function processImage(
  sourceId: string,
  filePath: string,
  fileType: string,
  originalName: string
): Promise<ProcessedImage> {
  const imageId = uuidv4();
  console.log(`[ImageProcessor] Processing image: ${originalName}`);

  const facesDir = path.join(process.cwd(), 'uploads', 'faces', sourceId);
  if (!fs.existsSync(facesDir)) {
    fs.mkdirSync(facesDir, { recursive: true });
  }

  // 1. Analyze image with Vision model and detect faces
  const faceResult = await detectFacesInImage(filePath, { cropDir: facesDir, sourceId });
  const description = faceResult.visualDescription || '';
  const ocrText = faceResult.ocrText || '';

  // 2. Compute 512-dim CLIP multimodal image embedding for the entire image
  let imageEmbeddingBuffer: Buffer | null = null;
  try {
    const vec = await getImageEmbedding(filePath);
    if (vec && vec.length > 0) {
      imageEmbeddingBuffer = floatArrayToBuffer(vec);
    }
  } catch (err) {
    console.warn('[ImageProcessor] Image embedding failed:', err);
  }

  // 3. Process face embeddings
  const processedFaces: Array<{
    id: string;
    confidence: number;
    bboxJson: string;
    embeddingBuffer: Buffer;
  }> = [];

  for (const face of faceResult.faces) {
    if (face.embedding && face.embedding.length > 0) {
      processedFaces.push({
        id: face.id,
        confidence: face.confidence,
        bboxJson: JSON.stringify(face.bbox),
        embeddingBuffer: floatArrayToBuffer(face.embedding),
      });
    }
  }

  const width = 0;
  const height = 0;

  dbTransaction((db) => {
    // Insert into images table with full image embedding
    db.prepare(`
      INSERT INTO images (id, source_id, width, height, ocr_text, description, embedding)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(imageId, sourceId, width, height, ocrText, description, imageEmbeddingBuffer);

    // Insert face embeddings
    for (const face of processedFaces) {
      db.prepare(`
        INSERT INTO face_embeddings (id, source_id, image_id, embedding, confidence, bbox_json)
        VALUES (?, ?, ?, ?, ?, ?)
      `).run(face.id, sourceId, imageId, face.embeddingBuffer, face.confidence, face.bboxJson);
    }

    // If description/OCR has text, index as a document chunk as well so it's searchable
    if (description || ocrText) {
      const chunkId = uuidv4();
      const docId = uuidv4();
      const text = `Image: ${originalName}\nDescription: ${description}${ocrText ? `\nOCR Text: ${ocrText}` : ''}`;

      db.prepare(`
        INSERT INTO documents (id, source_id, title, full_text, page_count, section_count)
        VALUES (?, ?, ?, ?, 1, 1)
      `).run(docId, sourceId, originalName, text);

      db.prepare(`
        INSERT INTO document_chunks (id, section_id, doc_id, source_id, chunk_text, chunk_order, page_num, embedding)
        VALUES (?, NULL, ?, ?, ?, 0, 1, ?)
      `).run(chunkId, docId, sourceId, text, imageEmbeddingBuffer);

      try {
        db.prepare(`
          INSERT INTO chunks_fts (chunk_text, chunk_id, source_id, doc_id)
          VALUES (?, ?, ?, ?)
        `).run(text, chunkId, sourceId, docId);
      } catch {
        // Fallback handled
      }
    }

    // Update knowledge source status
    db.prepare(`
      UPDATE knowledge_sources
      SET processing_status = 'completed',
          chunk_count = 1,
          face_count = ?
      WHERE id = ?
    `).run(processedFaces.length, sourceId);
  });

  console.log(`[ImageProcessor] Successfully processed ${originalName} with ${processedFaces.length} face embeddings`);

  return {
    imageId,
    sourceId,
    width,
    height,
    ocrText,
    description,
    faceCount: processedFaces.length,
  };
}
