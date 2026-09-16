// src/lib/groq/json.ts
// Robust JSON Extraction and Schema Validation for Groq AI Responses

import { type ZodType, ZodError } from 'zod';

/**
 * Cleans markdown code fences, backticks, and whitespace.
 * Rejects content containing reasoning tags (<think>).
 */
export function extractJSONText(raw: string): string {
  if (!raw) return '';
  let cleaned = raw.trim();

  // Safety check: Never allow <think> or reasoning tags to proceed to JSON.parse
  if (cleaned.includes('<think>') || cleaned.includes('</think>')) {
    console.error('[JSON Extraction] Model returned reasoning tags (<think>).');
    // Try to strip out <think>...</think> block if present before JSON
    cleaned = cleaned.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
  }

  // Remove markdown json fences
  if (cleaned.startsWith('```json')) {
    cleaned = cleaned.replace(/^```json\s*/i, '');
  } else if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```\s*/, '');
  }
  if (cleaned.endsWith('```')) {
    cleaned = cleaned.replace(/```$/, '');
  }

  // Find first { or [ and last } or ]
  const firstBrace = cleaned.indexOf('{');
  const firstBracket = cleaned.indexOf('[');
  let startIdx = 0;
  if (firstBrace !== -1 && (firstBracket === -1 || firstBrace < firstBracket)) {
    startIdx = firstBrace;
  } else if (firstBracket !== -1) {
    startIdx = firstBracket;
  } else {
    return ''; // No JSON start found
  }

  const lastBrace = cleaned.lastIndexOf('}');
  const lastBracket = cleaned.lastIndexOf(']');
  let endIdx = cleaned.length;
  if (lastBrace !== -1 && (lastBracket === -1 || lastBrace > lastBracket)) {
    endIdx = lastBrace + 1;
  } else if (lastBracket !== -1) {
    endIdx = lastBracket + 1;
  } else {
    return ''; // No JSON end found
  }

  return cleaned.slice(startIdx, endIdx).trim();
}

/**
 * Safely parses raw text into a typed object validated by a Zod schema.
 */
export function parseAndValidateJSON<T>(
  raw: string,
  schema: ZodType<T>,
  fallback?: T
): { data: T; success: boolean; error?: string } {
  const jsonStr = extractJSONText(raw);

  if (!jsonStr || (!jsonStr.startsWith('{') && !jsonStr.startsWith('['))) {
    console.error('[JSON Parse Error] Raw text does not contain a valid JSON object:', raw.slice(0, 300));
    if (fallback !== undefined) {
      return { data: fallback, success: false, error: 'Model output did not contain JSON' };
    }
    throw new Error('AI generated invalid non-JSON output. Please retry.');
  }

  try {
    const parsed = JSON.parse(jsonStr);
    const validated = schema.parse(parsed);
    return { data: validated, success: true };
  } catch (err) {
    if (fallback !== undefined) {
      return { data: fallback, success: false, error: err instanceof Error ? err.message : 'Validation failed' };
    }
    if (err instanceof ZodError) {
      const issueDetails = err.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; ');
      console.error('[JSON Validation Error]', issueDetails);
      throw new Error(`AI response did not match expected structure: ${issueDetails}`);
    }
    console.error('[JSON Parse Error]', err);
    throw new Error('AI generated malformed JSON. Please retry.');
  }
}
