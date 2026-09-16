// src/lib/groq/config.ts
// Centralized Groq model limits, conservative free-tier token budgets, and operational defaults

export const GROQ_MODEL = 'qwen/qwen3.6-27b';
export const GROQ_FAST_MODEL = 'qwen/qwen3.6-27b';

// Hard Model Limits for Qwen 3.6 27B on Groq
export const GROQ_MAX_CONTEXT_TOKENS = 131072; // Hard context window
export const GROQ_MAX_OUTPUT_TOKENS = 16384;  // Hard max output tokens

// Conservative Free-Tier Defaults (To protect rate limits and prevent excessive usage)
export const GROQ_TARGET_INPUT_TOKENS = 8000;
export const GROQ_MAX_SOURCES_PER_REQUEST = 8;
export const GROQ_MAX_SOURCE_CHARS = 3500;
export const GROQ_MAX_RETRIES = 1;

// Operation-specific Output Token Budgets (Conservative, tailored per task)
export const GROQ_OUTPUT_BUDGETS = {
  summary: 1000,
  insights: 800,
  brief: 1800,
  compare: 2500,
  chat: 1000,
  entities: 1200,
  timeline: 3000,
  report: 3500, // Only allocated when generating a full publication report
} as const;

export type GroqOperation = keyof typeof GROQ_OUTPUT_BUDGETS;

// Operation-specific Maximum Input Token Allowances
export const GROQ_INPUT_BUDGETS: Record<GroqOperation, number> = {
  summary: 3000,
  insights: 2500,
  brief: 12000,
  compare: 14000,
  chat: 4000,
  entities: 7000,
  timeline: 12000,
  report: 14000,
};
