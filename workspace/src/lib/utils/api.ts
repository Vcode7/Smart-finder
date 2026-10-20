// src/lib/utils/api.ts — helpers for talking to the FastAPI backend

type ValidationIssue = { msg?: string; loc?: (string | number)[] };

/** Human-readable message from a FastAPI error body ({detail: string | ValidationIssue[]}). */
export function apiErrorMessage(data: unknown, fallback: string): string {
  if (!data || typeof data !== 'object') return fallback;
  const body = data as { detail?: unknown; error?: unknown; message?: unknown };
  if (typeof body.detail === 'string' && body.detail.trim()) return body.detail;
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    const issue = body.detail[0] as ValidationIssue;
    const field = issue.loc?.filter((p) => p !== 'body').join('.');
    if (issue.msg) return field ? `${field}: ${issue.msg}` : issue.msg;
  }
  if (typeof body.error === 'string' && body.error.trim()) return body.error;
  if (typeof body.message === 'string' && body.message.trim()) return body.message;
  return fallback;
}

/** Parse a JSON response body without throwing on empty/non-JSON bodies. */
export async function readJson<T = unknown>(res: Response): Promise<T | null> {
  try {
    return (await res.json()) as T;
  } catch {
    return null;
  }
}
