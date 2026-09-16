// src/lib/groq/request.ts
// Centralized Groq Request Handler with Strict JSON Object Mode & Single Retry

import {
  getGroqClient,
  getGroqKeys,
  getActiveKeyIndex,
  markKeyRateLimited,
  markKeySuccess,
  isGroqRateLimitError,
} from './client';
import {
  GROQ_MODEL,
  GROQ_OUTPUT_BUDGETS,
  type GroqOperation,
} from './config';
import { estimateTokens } from './token-budget';

export interface GroqRequestOptions {
  operation: GroqOperation;
  systemPrompt: string;
  userPrompt: string;
  responseFormat?: { type: 'json_object' } | { type: 'text' };
  maxTokens?: number;
  temperature?: number;
  abortSignal?: AbortSignal;
}

export interface GroqRequestResult {
  content: string;
  estimatedInputTokens: number;
  estimatedOutputTokens: number;
  isMock: boolean;
}

/**
 * Standardized user-friendly error mapper.
 */
export function formatGroqError(err: unknown): string {
  if (err instanceof Error) {
    const msg = err.message.toLowerCase();
    if (msg.includes('429') || msg.includes('rate limit') || msg.includes('quota')) {
      return 'AI generation rate limit reached. Please wait a moment and try again.';
    }
    if (msg.includes('context_length') || msg.includes('maximum context')) {
      return 'Research context exceeds model capacity. Sources were automatically reduced.';
    }
    if (msg.includes('timeout') || msg.includes('abort')) {
      return 'Request was interrupted or timed out. Please retry.';
    }
    if (msg.includes('json_validate_failed') || msg.includes('failed to validate json')) {
      return 'AI output failed JSON schema validation. Please retry with a concise prompt.';
    }
    return err.message;
  }
  return 'An unexpected AI service error occurred.';
}

/**
 * Safe, centralized execution of Groq Chat Completion.
 * Consistently enforces JSON Object Mode with exactly one retry on failure.
 * Never drops response_format or falls back to uncontrolled text mode.
 */
export async function executeGroqRequest({
  operation,
  systemPrompt,
  userPrompt,
  responseFormat = { type: 'json_object' },
  maxTokens,
  temperature = 0.1,
  abortSignal,
}: GroqRequestOptions): Promise<GroqRequestResult> {
  const inputEstimate = estimateTokens(systemPrompt) + estimateTokens(userPrompt);
  const targetOutputBudget = maxTokens || GROQ_OUTPUT_BUDGETS[operation] || 1500;

  const keys = getGroqKeys();
  if (keys.length === 0) {
    throw new Error('Groq API key (GROQ_API_KEY) is not configured in .env.local.');
  }

  // ─── VERBOSE TERMINAL LOGGING: INPUT METADATA ─────────────────────────────
  console.log('\n' + '='.repeat(80));
  console.log(`🚀 [GROQ REQUEST] Operation: ${operation.toUpperCase()} | Model: ${GROQ_MODEL} | Available Keys: ${keys.length}`);
  console.log(`📊 Estimated Input Tokens: ~${inputEstimate} | Max Output Tokens: ${targetOutputBudget}`);
  console.log(`🔒 Enforcement: response_format = { type: "${responseFormat.type}" }`);
  console.log('-'.repeat(80));
  console.log('📝 [SYSTEM PROMPT]:');
  console.log(systemPrompt);
  console.log('-'.repeat(80));
  console.log('📦 [USER PROMPT (Truncated for clean log)]:\n' + userPrompt.slice(0, 800) + (userPrompt.length > 800 ? '...' : ''));
  console.log('='.repeat(80) + '\n');

  const totalKeys = keys.length;
  const startIdx = getActiveKeyIndex();
  let lastError: unknown = null;

  for (let attempt = 0; attempt < totalKeys; attempt++) {
    if (abortSignal?.aborted) {
      throw new Error('Request was cancelled by user');
    }

    const currentKeyIdx = (startIdx + attempt) % totalKeys;
    const groq = getGroqClient(currentKeyIdx);

    try {
      const completion = await (groq.chat.completions.create as any)({
        model: GROQ_MODEL,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: userPrompt },
        ],
        response_format: responseFormat, // Always keep strict JSON enforcement
        reasoning_format: 'hidden',      // Hide/suppress reasoning output
        reasoning_effort: 'none',        // Disable reasoning tokens on Qwen models
        max_tokens: targetOutputBudget,
        temperature: attempt === 0 ? temperature : 0.05,
      });

      const content = completion.choices[0]?.message?.content || '';
      const outputEstimate = estimateTokens(content);

      // ─── VERBOSE TERMINAL LOGGING: RAW RESPONSE ─────────────────────────────
      console.log('\n' + '='.repeat(80));
      console.log(`✅ [GROQ RAW RESPONSE] Operation: ${operation.toUpperCase()} (Using ${keys[currentKeyIdx].label})`);
      console.log(`📊 Output Tokens Received: ~${outputEstimate}`);
      console.log('-'.repeat(80));
      console.log(content);
      console.log('='.repeat(80) + '\n');

      if (!content || content.trim().length === 0) {
        throw new Error('Groq returned an empty response.');
      }

      markKeySuccess(currentKeyIdx);

      return {
        content,
        estimatedInputTokens: inputEstimate,
        estimatedOutputTokens: outputEstimate,
        isMock: false,
      };
    } catch (err: unknown) {
      lastError = err;
      const { isRateLimit, reason } = isGroqRateLimitError(err);
      console.warn(`[Groq Attempt ${attempt + 1}/${totalKeys} Failed] Operation: ${operation.toUpperCase()} (${keys[currentKeyIdx].label}):`, reason);

      if (isRateLimit && attempt < totalKeys - 1) {
        markKeyRateLimited(currentKeyIdx, reason);
        continue;
      } else if (isRateLimit) {
        console.error(`[GROQ] All ${totalKeys} Groq keys exhausted. Last error: ${reason}`);
        throw new Error(formatGroqError(lastError));
      } else {
        // Non-rate-limit error (e.g. invalid parameter)
        throw new Error(formatGroqError(lastError));
      }
    }
  }

  throw new Error(formatGroqError(lastError));
}
