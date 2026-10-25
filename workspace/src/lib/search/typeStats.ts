// src/lib/search/typeStats.ts
// Analytics that only make sense for one kind of file (pages of documents, resolution of photos,
// runtime of videos). Pure functions over the dashboard rows that pass the current filters.

import type { DashboardFile } from '@/types/insights';
import type { Bucket } from '@/lib/search/charts';

/** Counts in a fixed order, zero-count bins dropped. Each file lands in the first bin whose test passes. */
function bins(files: DashboardFile[], defs: { label: string; test: (f: DashboardFile) => boolean }[]): Bucket[] {
  const counts = defs.map(() => 0);
  for (const f of files) {
    const i = defs.findIndex((d) => d.test(f));
    if (i >= 0) counts[i] += 1;
  }
  return defs.map((d, i) => ({ key: d.label, label: d.label, count: counts[i] })).filter((b) => b.count > 0);
}

function tallyBy(files: DashboardFile[], keysOf: (f: DashboardFile) => string[]): Bucket[] {
  const map = new Map<string, Bucket>();
  for (const f of files) {
    for (const key of new Set(keysOf(f).filter(Boolean))) {
      const b = map.get(key);
      if (b) b.count += 1;
      else map.set(key, { key, label: key, count: 1 });
    }
  }
  return [...map.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

export const ofKind = (files: DashboardFile[], kind: string) => files.filter((f) => f.category === kind);

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s % 60 ? `${s % 60}s` : ''}`.trim();
  return `${s}s`;
}

/** All kinds: how big the files are. */
export const sizeBins = (files: DashboardFile[]) => bins(files, [
  { label: 'Under 100 KB', test: (f) => f.fileSize < 100 * 1024 },
  { label: '100 KB – 1 MB', test: (f) => f.fileSize < 1024 ** 2 },
  { label: '1 – 10 MB', test: (f) => f.fileSize < 10 * 1024 ** 2 },
  { label: '10 – 100 MB', test: (f) => f.fileSize < 100 * 1024 ** 2 },
  { label: 'Over 100 MB', test: () => true },
]);

// ── documents ────────────────────────────────────────────────────────────────
export const pageBins = (docs: DashboardFile[]) => bins(docs.filter((f) => f.pages), [
  { label: '1 page', test: (f) => (f.pages ?? 0) <= 1 },
  { label: '2 – 5 pages', test: (f) => (f.pages ?? 0) <= 5 },
  { label: '6 – 20 pages', test: (f) => (f.pages ?? 0) <= 20 },
  { label: '21 – 100 pages', test: (f) => (f.pages ?? 0) <= 100 },
  { label: 'Over 100 pages', test: () => true },
]);
export const totalPages = (docs: DashboardFile[]) => docs.reduce((s, f) => s + (f.pages || 0), 0);

// ── images ───────────────────────────────────────────────────────────────────
const megapixels = (f: DashboardFile) => ((f.width || 0) * (f.height || 0)) / 1e6;

export const resolutionBins = (images: DashboardFile[]) => bins(images.filter((f) => f.width && f.height), [
  { label: 'Under 1 MP (thumbnail / web)', test: (f) => megapixels(f) < 1 },
  { label: '1 – 4 MP (screen / social)', test: (f) => megapixels(f) < 4 },
  { label: '4 – 12 MP (phone / camera)', test: (f) => megapixels(f) < 12 },
  { label: '12 – 30 MP (high-res camera)', test: (f) => megapixels(f) < 30 },
  { label: '30 MP and up', test: () => true },
]);

export const orientationBins = (images: DashboardFile[]) => bins(images.filter((f) => f.width && f.height), [
  { label: 'Landscape', test: (f) => (f.width ?? 0) > (f.height ?? 0) * 1.05 },
  { label: 'Portrait', test: (f) => (f.height ?? 0) > (f.width ?? 0) * 1.05 },
  { label: 'Square', test: () => true },
]);

export const cameraBuckets = (images: DashboardFile[]) => tallyBy(images, (f) => (f.camera ? [f.camera] : []));
export const peopleBuckets = (files: DashboardFile[]) => tallyBy(files, (f) => f.people ?? []);
export const withLocation = (images: DashboardFile[]) => images.filter((f) => f.hasLocation).length;

// ── video and audio ──────────────────────────────────────────────────────────
export const durationBins = (media: DashboardFile[]) => bins(media.filter((f) => f.duration), [
  { label: 'Under 1 min', test: (f) => (f.duration ?? 0) < 60 },
  { label: '1 – 5 min', test: (f) => (f.duration ?? 0) < 300 },
  { label: '5 – 30 min', test: (f) => (f.duration ?? 0) < 1800 },
  { label: '30 min – 2 h', test: (f) => (f.duration ?? 0) < 7200 },
  { label: 'Over 2 h', test: () => true },
]);
export const totalRuntime = (media: DashboardFile[]) => media.reduce((s, f) => s + (f.duration || 0), 0);

/** By the shorter side, so a vertical phone video counts the same as a landscape one. */
export const videoQualityBins = (videos: DashboardFile[]) => bins(videos.filter((f) => f.width && f.height), [
  { label: '4K and up', test: (f) => Math.min(f.width ?? 0, f.height ?? 0) >= 2000 },
  { label: 'Full HD (1080p)', test: (f) => Math.min(f.width ?? 0, f.height ?? 0) >= 1000 },
  { label: 'HD (720p)', test: (f) => Math.min(f.width ?? 0, f.height ?? 0) >= 700 },
  { label: 'SD (below 720p)', test: () => true },
]);

/** Spoken content searchable as text: done / still being transcribed / none (silent or not run). */
export const transcriptBins = (media: DashboardFile[]) => bins(media, [
  { label: 'Transcribed', test: (f) => f.transcript === 'done' },
  { label: 'In progress', test: (f) => f.transcript === 'pending' || f.transcript === 'running' },
  { label: 'Failed', test: (f) => f.transcript === 'failed' },
  { label: 'No speech / not transcribed', test: () => true },
]);
