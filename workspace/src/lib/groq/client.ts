// src/lib/groq/client.ts
// Server-side Groq client with multi-key fallback support across primary and 3 fallback keys

import Groq from 'groq-sdk';

export interface GroqKeyEntry {
  label: string;
  key: string;
}

let _clients: Map<string, Groq> = new Map();
let _currentIndex: number = 0;
let _exhaustedUntil: Map<number, number> = new Map();
const COOLDOWN_MS = 60 * 1000;

export function getGroqKeys(): GroqKeyEntry[] {
  const candidates: [string, string | undefined][] = [
    ['Primary key', process.env.GROQ_API_KEY],
    ['Fallback key 1', process.env.GROQ_API_KEY_FALLBACK1],
    ['Fallback key 2', process.env.GROQ_API_KEY_FALLBACK2],
    ['Fallback key 3', process.env.GROQ_API_KEY_FALLBACK3],
  ];

  return candidates
    .filter(([, val]) => typeof val === 'string' && val.trim().length > 0)
    .map(([label, val]) => ({ label, key: val!.trim() }));
}

export function hasGroqKey(): boolean {
  return getGroqKeys().length > 0;
}

export function getActiveKeyIndex(): number {
  const keys = getGroqKeys();
  if (keys.length === 0) return 0;

  const now = Date.now();
  // If current key is still on cooldown, find the first available key
  if ((_exhaustedUntil.get(_currentIndex) || 0) > now) {
    for (let offset = 0; offset < keys.length; offset++) {
      const idx = (_currentIndex + offset) % keys.length;
      if ((_exhaustedUntil.get(idx) || 0) <= now) {
        _currentIndex = idx;
        break;
      }
    }
  }
  return _currentIndex;
}

export function markKeyRateLimited(idx: number, reason: string): number {
  const keys = getGroqKeys();
  const total = keys.length;
  if (total <= 1) return idx;

  _exhaustedUntil.set(idx, Date.now() + COOLDOWN_MS);
  const currentLabel = keys[idx]?.label || `Key ${idx + 1}`;
  const nextIdx = (idx + 1) % total;
  const nextLabel = keys[nextIdx]?.label || `Key ${nextIdx + 1}`;
  _currentIndex = nextIdx;

  console.log(`[GROQ] ${currentLabel} rate limited (${reason}) → switching to ${nextLabel}`);
  return nextIdx;
}

export function markKeySuccess(idx: number): void {
  const keys = getGroqKeys();
  _currentIndex = idx;
  _exhaustedUntil.delete(idx);
  if (idx > 0 && keys[idx]) {
    console.log(`[GROQ] Request succeeded using ${keys[idx].label}`);
  }
}

export function isGroqRateLimitError(err: unknown): { isRateLimit: boolean; reason: string } {
  if (err instanceof Error) {
    const msg = err.message.toLowerCase();
    const status = (err as any).status || (err as any).statusCode || (err as any).status_code;

    if (status === 429) {
      return { isRateLimit: true, reason: `HTTP 429 Too Many Requests (${err.message.slice(0, 100)})` };
    }
    if (status === 503 || status === 504) {
      return { isRateLimit: true, reason: `HTTP ${status} Service Unavailable` };
    }

    const ratePatterns = [
      'rate limit',
      'rate_limit',
      'too many requests',
      'quota exceeded',
      'insufficient_quota',
      'resource_exhausted',
      'tokens per minute',
      'tpm',
      'requests per minute',
      'rpm',
      'requests per day',
      'rpd',
      '429',
      'exceeded your current quota',
    ];

    for (const p of ratePatterns) {
      if (msg.includes(p)) {
        return { isRateLimit: true, reason: `Quota / Rate limit signal detected ('${p}')` };
      }
    }
    return { isRateLimit: false, reason: err.message };
  }
  return { isRateLimit: false, reason: String(err) };
}

export function getGroqClient(keyIndex?: number): Groq {
  const keys = getGroqKeys();
  if (keys.length === 0) {
    throw new Error('No GROQ_API_KEY configured in environment.');
  }

  const chosenIdx = keyIndex !== undefined ? keyIndex % keys.length : getActiveKeyIndex();
  const apiKey = keys[chosenIdx].key;

  if (!_clients.has(apiKey)) {
    _clients.set(apiKey, new Groq({ apiKey }));
  }
  return _clients.get(apiKey)!;
}

// Qwen 3.6 27B model on Groq
export const GROQ_MODEL = 'qwen/qwen3.6-27b';
export const GROQ_FAST_MODEL = 'qwen/qwen3.6-27b';
