// src/lib/groq/token-budget.ts
// Smart Token Budget Estimation and Text Truncation Utilities

import {
  GROQ_MAX_CONTEXT_TOKENS,
  GROQ_OUTPUT_BUDGETS,
  GROQ_INPUT_BUDGETS,
  type GroqOperation,
} from './config';

/**
 * Conservative token count estimation based on character and word heuristics.
 * ~3.8 characters per token for English & multilingual text.
 */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  // Account for punctuation, whitespace and subwords
  const charTokens = Math.ceil(text.length / 3.8);
  const wordTokens = Math.ceil(text.trim().split(/\s+/).length * 1.3);
  return Math.max(charTokens, wordTokens);
}

/**
 * Safely truncates a text string so it does not exceed the target token limit.
 * Truncates at the nearest sentence or word boundary to preserve readability.
 */
export function truncateToTokens(text: string, maxTokens: number): string {
  if (!text) return '';
  const currentTokens = estimateTokens(text);
  if (currentTokens <= maxTokens) return text;

  const targetChars = Math.floor(maxTokens * 3.7);
  if (text.length <= targetChars) return text;

  const sliced = text.slice(0, targetChars);
  // Find last sentence or line break
  const lastSentence = Math.max(
    sliced.lastIndexOf('. '),
    sliced.lastIndexOf('.\n'),
    sliced.lastIndexOf('? '),
    sliced.lastIndexOf('! ')
  );

  if (lastSentence > targetChars * 0.7) {
    return sliced.slice(0, lastSentence + 1) + ' [truncated for token budget]';
  }

  // Fallback to last word boundary
  const lastWord = sliced.lastIndexOf(' ');
  if (lastWord > targetChars * 0.7) {
    return sliced.slice(0, lastWord) + '… [truncated for token budget]';
  }

  return sliced + '… [truncated for token budget]';
}

/**
 * Calculates remaining available input tokens for an operation.
 */
export function getRemainingInputTokens(
  operation: GroqOperation,
  usedTokens: number,
  customMaxInput?: number
): number {
  const maxInput = customMaxInput || GROQ_INPUT_BUDGETS[operation];
  const outputBudget = GROQ_OUTPUT_BUDGETS[operation];
  
  // Total hard ceiling check
  const hardCeiling = GROQ_MAX_CONTEXT_TOKENS - outputBudget - 500; // 500 safety margin
  const effectiveMax = Math.min(maxInput, hardCeiling);

  return Math.max(0, effectiveMax - usedTokens);
}
