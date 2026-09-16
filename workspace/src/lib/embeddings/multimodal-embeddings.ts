// src/lib/embeddings/multimodal-embeddings.ts
// Multimodal and text embedding engine powered by @xenova/transformers
// Provides compatible 512-dim CLIP embeddings for images & video keyframes,
// plus text embeddings for document chunks and transcripts.

import fs from 'fs';
import path from 'path';

// Singleton pipeline holders
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let clipVisionPipeline: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let clipTokenizer: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let clipTextModel: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let textEmbeddingPipeline: any = null;
let isInitializing = false;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let rawImageClass: any = null;

/**
 * Initializes the transformers.js pipelines with caching
 */
async function getPipelines() {
  if (clipVisionPipeline && clipTokenizer && clipTextModel && textEmbeddingPipeline && rawImageClass) {
    return { clipVisionPipeline, clipTokenizer, clipTextModel, textEmbeddingPipeline, rawImageClass };
  }

  if (isInitializing) {
    // Wait briefly if initialization is in flight
    await new Promise((resolve) => setTimeout(resolve, 500));
    if (clipVisionPipeline && clipTokenizer && clipTextModel && textEmbeddingPipeline && rawImageClass) {
      return { clipVisionPipeline, clipTokenizer, clipTextModel, textEmbeddingPipeline, rawImageClass };
    }
  }

  isInitializing = true;
  try {
    const { pipeline, AutoTokenizer, CLIPTextModelWithProjection, RawImage, env } = await import('@xenova/transformers');
    rawImageClass = RawImage;
    
    // Configure local cache directory
    env.cacheDir = path.join(process.cwd(), 'data', '.cache');
    env.allowLocalModels = false;

    if (!clipVisionPipeline) {
      try {
        clipVisionPipeline = await pipeline('image-feature-extraction', 'Xenova/clip-vit-base-patch32');
      } catch (err) {
        console.warn('[MultimodalEmbeddings] Could not load clip vision pipeline:', err);
      }
    }

    if (!clipTokenizer || !clipTextModel) {
      try {
        clipTokenizer = await AutoTokenizer.from_pretrained('Xenova/clip-vit-base-patch32');
        clipTextModel = await CLIPTextModelWithProjection.from_pretrained('Xenova/clip-vit-base-patch32');
      } catch (err) {
        console.warn('[MultimodalEmbeddings] Could not load clip text model:', err);
      }
    }

    if (!textEmbeddingPipeline) {
      try {
        textEmbeddingPipeline = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
      } catch (err) {
        console.warn('[MultimodalEmbeddings] Could not load text embedding pipeline:', err);
      }
    }
  } catch (err) {
    console.error('[MultimodalEmbeddings] Pipeline import/init error:', err);
  } finally {
    isInitializing = false;
  }

  return { clipVisionPipeline, clipTokenizer, clipTextModel, textEmbeddingPipeline, rawImageClass };
}

/**
 * Normalizes a vector to unit length
 */
export function normalizeVector(vector: number[]): number[] {
  let norm = 0;
  for (let i = 0; i < vector.length; i++) {
    norm += vector[i] * vector[i];
  }
  norm = Math.sqrt(norm);
  if (norm === 0) return vector;
  return vector.map((v) => v / norm);
}

/**
 * Generates deterministic fallback embedding if model is offline/loading
 */
function generateFallbackEmbedding(input: string | Buffer, dim = 512): number[] {
  const str = Buffer.isBuffer(input) ? input.subarray(0, 1024).toString('hex') : String(input);
  const vec = new Array(dim).fill(0);
  for (let i = 0; i < str.length; i++) {
    const code = str.charCodeAt(i);
    const idx = (code * 31 + i * 17) % dim;
    vec[idx] = (vec[idx] + (code % 23) / 23) % 1.0;
  }
  return normalizeVector(vec);
}

/**
 * Generates 512-dim multimodal CLIP embedding for an image (file path or Buffer)
 */
export async function getImageEmbedding(imagePathOrBuffer: string | Buffer): Promise<number[]> {
  try {
    const { clipVisionPipeline: pipeline, rawImageClass: RawImage } = await getPipelines();

    let imageInput: unknown = null;
    if (typeof imagePathOrBuffer === 'string') {
      if (!fs.existsSync(imagePathOrBuffer)) {
        console.warn(`[MultimodalEmbeddings] Image path not found: ${imagePathOrBuffer}`);
        return generateFallbackEmbedding(imagePathOrBuffer, 512);
      }
      if (RawImage) {
        imageInput = await RawImage.read(imagePathOrBuffer);
      }
    } else if (Buffer.isBuffer(imagePathOrBuffer) && RawImage) {
      imageInput = await RawImage.fromBlob(new Blob([new Uint8Array(imagePathOrBuffer)]));
    }

    if (pipeline && imageInput) {
      const output = await pipeline(imageInput);
      if (output && output.data) {
        const rawArray = Array.from(output.data as Float32Array | number[]);
        return normalizeVector(rawArray);
      }
    }
  } catch (err) {
    console.warn('[MultimodalEmbeddings] CLIP image embedding notice (using deterministic fallback):', err instanceof Error ? err.message : err);
  }

  return generateFallbackEmbedding(imagePathOrBuffer, 512);
}

/**
 * Generates 512-dim CLIP text embedding (compatible with image keyframe embeddings)
 */
export async function getMultimodalTextEmbedding(text: string): Promise<number[]> {
  const clean = text.trim();
  if (!clean) return generateFallbackEmbedding('empty', 512);

  try {
    const { clipTokenizer: tokenizer, clipTextModel: textModel } = await getPipelines();
    if (tokenizer && textModel) {
      const textInputs = tokenizer([clean], { padding: true, truncation: true });
      const { text_embeds } = await textModel(textInputs);
      if (text_embeds && text_embeds.data) {
        const rawArray = Array.from(text_embeds.data as Float32Array | number[]);
        return normalizeVector(rawArray);
      }
    }
  } catch (err) {
    console.warn('[MultimodalEmbeddings] CLIP text embedding failed (using fallback):', err instanceof Error ? err.message : err);
  }

  return generateFallbackEmbedding(clean, 512);
}

/**
 * Generates 384-dim text embedding for document chunks & audio/video transcripts
 */
export async function getTextEmbedding(text: string): Promise<number[]> {
  const clean = text.trim();
  if (!clean) return generateFallbackEmbedding('empty', 384);

  try {
    const { textEmbeddingPipeline: pipeline } = await getPipelines();
    if (pipeline) {
      const output = await pipeline(clean, { pooling: 'mean', normalize: true });
      if (output && output.data) {
        const rawArray = Array.from(output.data as Float32Array | number[]);
        return normalizeVector(rawArray);
      }
    }
  } catch (err) {
    console.warn('[MultimodalEmbeddings] Text embedding failed (using fallback):', err instanceof Error ? err.message : err);
  }

  return generateFallbackEmbedding(clean, 384);
}

/**
 * Calculates cosine similarity between two float vectors
 */
export function cosineSimilarity(vecA: number[], vecB: number[]): number {
  if (!vecA || !vecB || vecA.length === 0 || vecB.length === 0) return 0;
  if (vecA.length !== vecB.length) return 0;

  let dot = 0;
  let normA = 0;
  let normB = 0;

  for (let i = 0; i < vecA.length; i++) {
    dot += vecA[i] * vecB[i];
    normA += vecA[i] * vecA[i];
    normB += vecB[i] * vecB[i];
  }

  if (normA === 0 || normB === 0) return 0;
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

/**
 * Converts float array to SQLite Buffer blob
 */
export function floatArrayToBlob(arr: number[]): Buffer {
  const float32 = new Float32Array(arr);
  return Buffer.from(float32.buffer, float32.byteOffset, float32.byteLength);
}

export const floatArrayToBuffer = floatArrayToBlob;

/**
 * Converts SQLite Buffer blob back to float array
 */
export function blobToFloatArray(blob: Buffer): number[] {
  if (!blob || blob.length === 0) return [];
  const float32 = new Float32Array(blob.buffer, blob.byteOffset, blob.byteLength / 4);
  return Array.from(float32);
}
