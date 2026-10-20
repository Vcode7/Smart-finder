// src/lib/upload/chunked-uploader.ts — resumable uploads of any size through the Next.js proxy
//
// Protocol (backend: app/api/v1/uploads.py):
//   POST   /api/uploads                 → { status: 'exists' | 'started', uploadId, chunkSize, received }
//   PUT    /api/uploads/:id?offset=N    → { received }      (raw chunk body)
//   GET    /api/uploads/:id             → { received, size }
//   POST   /api/uploads/:id/complete    → { status: 'queued' | 'exists' | 'saved', sourceId, relPath }
//   DELETE /api/uploads/:id
//
// Next.js buffers every proxied request body, so files travel in chunks (8 MB by
// default). Sessions are remembered per file (name + size + lastModified) in
// localStorage: re-selecting the same file after a refresh or a dropped connection
// resumes where it stopped. Failed requests are retried with backoff.

import { apiErrorMessage, readJson } from '@/lib/utils/api';

export type UploadState =
  | 'waiting' | 'checking' | 'uploading' | 'paused' | 'finishing'
  | 'done' | 'exists' | 'error' | 'cancelled';

export interface UploadItem {
  id: string;
  file: File;
  relativePath?: string;
  libraryId?: string;
  state: UploadState;
  sent: number;
  total: number;
  speed: number;            // bytes per second (smoothed)
  error?: string;
  result?: { sourceId?: string | null; relPath?: string; libraryName?: string; status?: string };
}

type Listener = (items: UploadItem[]) => void;

const PARALLEL_FILES = 3;
const MAX_RETRIES = 8;
const STORE_KEY = 'smartfind.uploads.v1';

function signature(file: File, relativePath?: string, libraryId?: string): string {
  return [libraryId || 'uploads', relativePath || file.name, file.size, file.lastModified].join('|');
}

function loadSessions(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY) || '{}') as Record<string, string>;
  } catch {
    return {};
  }
}

function saveSession(sig: string, uploadId: string | null) {
  try {
    const all = loadSessions();
    if (uploadId) all[sig] = uploadId;
    else delete all[sig];
    localStorage.setItem(STORE_KEY, JSON.stringify(all));
  } catch {
    // storage unavailable (private mode): uploads still work, just without resume after refresh
  }
}

class HttpError extends Error {
  constructor(public status: number, message: string, public received?: number) {
    super(message);
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function jsonRequest(url: string, init: RequestInit) {
  const res = await fetch(url, init);
  const data = await readJson<Record<string, unknown>>(res);
  if (!res.ok) {
    throw new HttpError(res.status, apiErrorMessage(data, `Request failed (${res.status})`),
      typeof data?.received === 'number' ? (data.received as number) : undefined);
  }
  return data || {};
}

/** Retry transient failures (network errors, 5xx, 499/408/429) with exponential backoff. */
async function withRetry<T>(fn: () => Promise<T>, isCancelled: () => boolean): Promise<T> {
  let attempt = 0;
  for (;;) {
    try {
      return await fn();
    } catch (e) {
      const status = e instanceof HttpError ? e.status : 0;
      const transient = status === 0 || status >= 500 || status === 499 || status === 408 || status === 429;
      if (!transient || attempt >= MAX_RETRIES || isCancelled()) throw e;
      attempt += 1;
      await sleep(Math.min(30000, 500 * 2 ** attempt));
    }
  }
}

export class ChunkedUploader {
  private items: UploadItem[] = [];
  private listeners = new Set<Listener>();
  private active = 0;
  private paused = new Set<string>();
  private cancelled = new Set<string>();
  private uploadIds = new Map<string, string>();

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    fn(this.items);
    return () => this.listeners.delete(fn);
  }

  private emit() {
    const snapshot = this.items.map((i) => ({ ...i }));
    this.listeners.forEach((fn) => fn(snapshot));
  }

  private update(id: string, patch: Partial<UploadItem>) {
    const item = this.items.find((i) => i.id === id);
    if (item) Object.assign(item, patch);
    this.emit();
  }

  /** Queue files; `relativePath` keeps folder structure (webkitRelativePath). */
  add(files: Array<{ file: File; relativePath?: string }>, libraryId?: string) {
    for (const { file, relativePath } of files) {
      this.items.push({
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        file, relativePath, libraryId,
        state: 'waiting', sent: 0, total: file.size, speed: 0,
      });
    }
    this.emit();
    this.pump();
  }

  pause(id: string) {
    this.paused.add(id);
    this.update(id, { state: 'paused', speed: 0 });
  }

  resume(id: string) {
    this.paused.delete(id);
    const item = this.items.find((i) => i.id === id);
    if (item && (item.state === 'paused' || item.state === 'error')) {
      this.update(id, { state: 'waiting', error: undefined });
      this.pump();
    }
  }

  async cancel(id: string) {
    this.cancelled.add(id);
    this.paused.delete(id);
    const item = this.items.find((i) => i.id === id);
    const uploadId = this.uploadIds.get(id);
    if (item) {
      saveSession(signature(item.file, item.relativePath, item.libraryId), null);
      this.update(id, { state: 'cancelled', speed: 0 });
    }
    if (uploadId) {
      try { await fetch(`/api/uploads/${uploadId}`, { method: 'DELETE' }); } catch { /* best effort */ }
    }
  }

  clearFinished() {
    this.items = this.items.filter((i) => !['done', 'exists', 'cancelled'].includes(i.state));
    this.emit();
  }

  get pending(): number {
    return this.items.filter((i) => ['waiting', 'checking', 'uploading', 'finishing'].includes(i.state)).length;
  }

  private pump() {
    while (this.active < PARALLEL_FILES) {
      const next = this.items.find((i) => i.state === 'waiting');
      if (!next) return;
      this.active += 1;
      next.state = 'checking';
      this.emit();
      this.run(next).finally(() => {
        this.active -= 1;
        this.pump();
      });
    }
  }

  private async run(item: UploadItem) {
    const sig = signature(item.file, item.relativePath, item.libraryId);
    const stopped = () => this.cancelled.has(item.id) || this.paused.has(item.id);
    try {
      let uploadId: string | undefined = loadSessions()[sig];
      let received = 0;
      let chunkSize = 8 * 1024 * 1024;

      if (uploadId) {
        try {
          const s = await jsonRequest(`/api/uploads/${uploadId}`, { method: 'GET' });
          received = Number(s.received) || 0;
          chunkSize = Number(s.chunkSize) || chunkSize;
        } catch {
          uploadId = undefined;          // expired or finished elsewhere: start fresh
          saveSession(sig, null);
        }
      }
      if (!uploadId) {
        const start = await withRetry(() => jsonRequest('/api/uploads', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            fileName: item.file.name,
            size: item.file.size,
            lastModified: item.file.lastModified,
            relativePath: item.relativePath,
            libraryId: item.libraryId,
          }),
        }), stopped);
        if (start.status === 'exists') {
          this.update(item.id, {
            state: 'exists', sent: item.total, speed: 0,
            result: { sourceId: start.sourceId as string, relPath: start.relPath as string,
                      libraryName: start.libraryName as string, status: start.processingStatus as string },
          });
          return;
        }
        uploadId = start.uploadId as string;
        chunkSize = Number(start.chunkSize) || chunkSize;
        saveSession(sig, uploadId);
      }
      this.uploadIds.set(item.id, uploadId);
      this.update(item.id, { state: 'uploading', sent: received });

      let lastTick = performance.now();
      let lastBytes = received;
      while (received < item.file.size) {
        if (this.cancelled.has(item.id)) return;
        if (this.paused.has(item.id)) {
          this.update(item.id, { state: 'paused', speed: 0 });
          return;
        }
        const end = Math.min(item.file.size, received + chunkSize);
        const offset = received;
        const body = item.file.slice(offset, end);
        try {
          const r = await withRetry(() => jsonRequest(`/api/uploads/${uploadId}?offset=${offset}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/octet-stream' },
            body,
          }), () => this.cancelled.has(item.id));
          received = Number(r.received) || end;
        } catch (e) {
          // The server tells us where it actually is (e.g. after a partial chunk)
          if (e instanceof HttpError && e.status === 409 && typeof e.received === 'number') {
            received = e.received;
            continue;
          }
          throw e;
        }
        const now = performance.now();
        const dt = (now - lastTick) / 1000;
        const instant = dt > 0 ? (received - lastBytes) / dt : 0;
        lastTick = now;
        lastBytes = received;
        const prev = this.items.find((i) => i.id === item.id)?.speed || instant;
        this.update(item.id, { sent: received, speed: prev ? prev * 0.6 + instant * 0.4 : instant });
      }

      this.update(item.id, { state: 'finishing', speed: 0 });
      const done = await withRetry(() => jsonRequest(`/api/uploads/${uploadId}/complete`, { method: 'POST' }),
        () => this.cancelled.has(item.id));
      saveSession(sig, null);
      this.update(item.id, {
        state: done.status === 'exists' ? 'exists' : 'done',
        sent: item.total,
        result: { sourceId: done.sourceId as string, relPath: done.relPath as string,
                  libraryName: done.libraryName as string, status: done.status as string },
      });
    } catch (e) {
      if (this.cancelled.has(item.id)) return;
      if (e instanceof HttpError && (e.status === 404 || e.status === 410)) saveSession(sig, null);
      this.update(item.id, { state: 'error', speed: 0, error: e instanceof Error ? e.message : 'Upload failed' });
    }
  }
}

/** Collect files from a drop event, walking dropped folders (keeps their relative paths). */
export async function filesFromDataTransfer(dt: DataTransfer): Promise<Array<{ file: File; relativePath?: string }>> {
  const entries: FileSystemEntry[] = [];
  for (const item of Array.from(dt.items)) {
    const entry = item.webkitGetAsEntry?.();
    if (entry) entries.push(entry);
  }
  if (entries.length === 0) {
    return Array.from(dt.files).map((file) => ({ file }));
  }
  const out: Array<{ file: File; relativePath?: string }> = [];
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject));
      out.push({ file, relativePath: prefix ? `${prefix}/${file.name}` : undefined });
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      const dirPath = prefix ? `${prefix}/${entry.name}` : entry.name;
      // readEntries returns results in batches; keep reading until empty
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
        if (batch.length === 0) break;
        for (const child of batch) await walk(child, dirPath);
      }
    }
  };
  for (const entry of entries) await walk(entry, '');
  return out;
}

let shared: ChunkedUploader | null = null;

/** One uploader per tab, so uploads keep running while you move between pages. */
export function getUploader(): ChunkedUploader {
  if (!shared) shared = new ChunkedUploader();
  return shared;
}
