// src/lib/search/charts.ts
// Aggregations behind the Dashboard tab's charts. Pure functions over the dashboard's file rows,
// so cross-filtering recomputes instantly in the browser.

import type { DashboardFile } from '@/types/insights';
import type { DateField, DateGrain } from '@/store/searchView';

export interface Bucket {
  key: string;
  label: string;
  count: number;
  hint?: string;
}

export interface Filters {
  category: string | null;
  ext: string | null;
  folder: string | null;       // `${libraryId}:${folder}`
  library: string | null;
  date: string | null;         // bucket key at the current grain
  score: number | null;        // lower edge of a 5% relevance bin
  topic: string | null;        // lower-cased topic
}

export const NO_FILTERS: Filters = { category: null, ext: null, folder: null, library: null, date: null, score: null, topic: null };

export const CATEGORY_LABEL: Record<string, string> = { document: 'Documents', image: 'Images', video: 'Videos', audio: 'Audio' };
export const CATEGORY_ORDER = ['document', 'image', 'video', 'audio'];
/** A kind keeps its colour whatever else is filtered out. */
export const CATEGORY_COLOR: Record<string, string> = {
  document: 'var(--viz-1)', image: 'var(--viz-2)', video: 'var(--viz-3)', audio: 'var(--viz-4)',
};

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const v = bytes / 1024 ** i;
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export const folderKey = (f: DashboardFile) => `${f.libraryId ?? ''}:${f.folder ?? ''}`;
const topicKey = (t: string) => t.trim().toLowerCase();

function parseDate(raw: string | null | undefined): Date | null {
  if (!raw) return null;
  const d = new Date(raw);
  return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * 'best' adapts per file: when it was taken (EXIF) if the file says so, otherwise when it was
 * modified, otherwise when it was indexed. Copying a file resets its modified date but not its EXIF.
 */
export function dateOf(f: DashboardFile, field: DateField): Date | null {
  if (field === 'best') return parseDate(f.takenAt) ?? parseDate(f.modifiedAt) ?? parseDate(f.indexedAt);
  return parseDate(f[field]);
}

export function dateKey(d: Date, grain: DateGrain): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return grain === 'year' ? `${y}` : grain === 'month' ? `${y}-${m}` : `${y}-${m}-${day}`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function dateLabel(key: string): string {
  const [y, m, d] = key.split('-');
  if (!m) return y;
  return d ? `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}` : `${MONTHS[Number(m) - 1]} ${y}`;
}

export function scoreBin(score: number): number {
  return Math.floor(Math.min(0.9999, Math.max(0, score)) * 20) / 20;   // 5% bins
}

export function matches(f: DashboardFile, flt: Filters, field: DateField, grain: DateGrain): boolean {
  if (flt.category && f.category !== flt.category) return false;
  if (flt.ext && (f.fileType || '').toLowerCase() !== flt.ext) return false;
  if (flt.folder && folderKey(f) !== flt.folder) return false;
  if (flt.library && (f.libraryId ?? '') !== flt.library) return false;
  if (flt.score !== null && Math.abs(scoreBin(f.relevanceScore) - flt.score) > 1e-9) return false;
  if (flt.topic && !f.topics.some((t) => topicKey(t) === flt.topic)) return false;
  if (flt.date) {
    const d = dateOf(f, field);
    if (!d || dateKey(d, grain) !== flt.date) return false;
  }
  return true;
}

/**
 * Filter the files for one chart: every filter applies except the chart's own dimension, so a
 * chart keeps showing the alternatives to its current selection (the usual cross-filter).
 */
export function filterExcept(files: DashboardFile[], flt: Filters, skip: keyof Filters | null,
                             field: DateField, grain: DateGrain): DashboardFile[] {
  const f = skip ? { ...flt, [skip]: null } : flt;
  return files.filter((x) => matches(x, f, field, grain));
}

function tally(files: DashboardFile[], keyOf: (f: DashboardFile) => string | null, labelOf: (key: string, f: DashboardFile) => string): Bucket[] {
  const map = new Map<string, Bucket>();
  for (const f of files) {
    const key = keyOf(f);
    if (key === null) continue;
    const b = map.get(key);
    if (b) b.count += 1;
    else map.set(key, { key, label: labelOf(key, f), count: 1 });
  }
  return [...map.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

export const byCategory = (files: DashboardFile[]): Bucket[] =>
  tally(files, (f) => f.category || 'document', (k) => CATEGORY_LABEL[k] ?? k)
    .sort((a, b) => CATEGORY_ORDER.indexOf(a.key) - CATEGORY_ORDER.indexOf(b.key));

export const byExtension = (files: DashboardFile[]): Bucket[] =>
  tally(files, (f) => (f.fileType || 'none').toLowerCase(), (k) => (k === 'none' ? 'no extension' : k.toUpperCase()));

export const byLibrary = (files: DashboardFile[]): Bucket[] =>
  tally(files, (f) => f.libraryId ?? '', (_k, f) => f.libraryName || 'Legacy index');

export function byFolder(files: DashboardFile[], withLibrary: boolean): Bucket[] {
  return tally(files, folderKey, (_k, f) => {
    const path = f.folder || '(top level)';
    return withLibrary && f.libraryName ? `${f.libraryName} › ${path}` : path;
  });
}

export function byTopic(files: DashboardFile[]): Bucket[] {
  const map = new Map<string, Bucket>();
  for (const f of files) {
    const seen = new Set<string>();
    for (const t of f.topics) {
      const key = topicKey(t);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      const b = map.get(key);
      if (b) b.count += 1;
      else map.set(key, { key, label: t.trim(), count: 1 });
    }
  }
  const sorted = [...map.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  // Across many files a topic only one file has is noise (OCR slips, one-off words), not a theme
  const shared = sorted.filter((b) => b.count >= 2);
  return files.length >= MIN_FILES_FOR_SHARED_TOPICS && shared.length > 0 ? shared : sorted;
}

const MIN_FILES_FOR_SHARED_TOPICS = 10;
const MAX_FILLED_BUCKETS = 240;

/** Files per period, in time order; empty years and months between the first and last are kept. */
export function byDate(files: DashboardFile[], field: DateField, grain: DateGrain): { buckets: Bucket[]; undated: number } {
  const counts = new Map<string, number>();
  let undated = 0;
  let min: Date | null = null;
  let max: Date | null = null;
  for (const f of files) {
    const d = dateOf(f, field);
    if (!d) { undated += 1; continue; }
    const k = dateKey(d, grain);
    counts.set(k, (counts.get(k) ?? 0) + 1);
    if (!min || d < min) min = d;
    if (!max || d > max) max = d;
  }
  if (!min || !max) return { buckets: [], undated };

  const keys: string[] = [];
  if (grain !== 'day') {
    const cur = new Date(Date.UTC(min.getUTCFullYear(), grain === 'year' ? 0 : min.getUTCMonth(), 1));
    const last = dateKey(max, grain);
    while (dateKey(cur, grain) <= last && keys.length <= MAX_FILLED_BUCKETS) {
      keys.push(dateKey(cur, grain));
      if (grain === 'year') cur.setUTCFullYear(cur.getUTCFullYear() + 1);
      else cur.setUTCMonth(cur.getUTCMonth() + 1);
    }
  }
  const ordered = keys.length && keys.length <= MAX_FILLED_BUCKETS ? keys : [...counts.keys()].sort();
  return { buckets: ordered.map((key) => ({ key, label: dateLabel(key), count: counts.get(key) ?? 0 })), undated };
}

/** Files per 5% relevance bin, lowest first, from the lowest occupied bin to the highest. */
export function byScore(files: DashboardFile[]): Bucket[] {
  if (!files.length) return [];
  const counts = new Map<number, number>();
  for (const f of files) {
    const b = scoreBin(f.relevanceScore);
    counts.set(b, (counts.get(b) ?? 0) + 1);
  }
  const lo = Math.min(...counts.keys());
  const hi = Math.max(...counts.keys());
  const out: Bucket[] = [];
  for (let i = Math.round(lo * 20); i <= Math.round(hi * 20); i++) {
    const edge = i / 20;
    out.push({ key: String(edge), label: `${Math.round(edge * 100)}%`, count: counts.get(edge) ?? 0,
               hint: `${Math.round(edge * 100)}–${Math.round(edge * 100) + 5}% relevance` });
  }
  return out;
}
