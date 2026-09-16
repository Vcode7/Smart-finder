// src/lib/sources/deduplication.ts
// Intelligent Source Deduplication: URL normalization, Video IDs, Paper DOIs, and Title Similarity

import type { Source } from '@/types/research';

/**
 * Normalizes a URL by stripping tracking parameters, hashes, and trailing slashes.
 */
export function normalizeUrl(url?: string): string {
  if (!url || typeof url !== 'string') return '';
  try {
    const parsed = new URL(url.trim());
    // Strip common tracking parameters
    const searchParams = new URLSearchParams(parsed.search);
    const trackingKeys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'ref', 'source', 'fbclid', 'gclid'];
    trackingKeys.forEach((key) => searchParams.delete(key));

    // Handle YouTube canonical links
    if (parsed.hostname.includes('youtube.com') || parsed.hostname.includes('youtu.be')) {
      let videoId = searchParams.get('v');
      if (!videoId && parsed.pathname.startsWith('/watch')) {
        videoId = searchParams.get('v');
      } else if (!videoId && parsed.hostname === 'youtu.be') {
        videoId = parsed.pathname.slice(1);
      }
      if (videoId) {
        return `https://www.youtube.com/watch?v=${videoId}`;
      }
    }

    parsed.search = searchParams.toString();
    parsed.hash = '';
    let normalized = parsed.toString();
    if (normalized.endsWith('/')) {
      normalized = normalized.slice(0, -1);
    }
    return normalized.toLowerCase();
  } catch {
    return url.trim().toLowerCase();
  }
}

/**
 * Simplifies and normalizes titles for fuzzy collision checking.
 */
export function normalizeTitle(title?: string): string {
  if (!title || typeof title !== 'string') return '';
  return title
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Computes Jaccard word-level similarity between two strings (0.0 to 1.0).
 */
export function wordSimilarity(a?: string, b?: string): number {
  if (!a || !b) return 0;
  const setA = new Set(normalizeTitle(a).split(' ').filter(Boolean));
  const setB = new Set(normalizeTitle(b).split(' ').filter(Boolean));
  if (setA.size === 0 || setB.size === 0) return 0;

  const intersection = new Set([...setA].filter((x) => setB.has(x)));
  const union = new Set([...setA, ...setB]);
  return intersection.size / union.size;
}

/**
 * Deduplicates a list of sources before AI processing.
 * Preserves the source with richer content when duplicates are found.
 */
export function deduplicateSources(sources: Source[]): Source[] {
  if (!Array.isArray(sources)) return [];
  const seenUrls = new Set<string>();
  const seenDois = new Set<string>();
  const seenTitles: { title: string; source: Source }[] = [];
  const uniqueSources: Source[] = [];

  for (const source of sources) {
    if (!source) continue;
    const title = source.title || '';
    const normUrl = normalizeUrl(source.url);

    // 1. Check URL collision
    if (normUrl && seenUrls.has(normUrl)) {
      continue;
    }

    // 2. Check DOI collision for research papers
    if (source.doi) {
      const cleanDoi = String(source.doi).toLowerCase().trim();
      if (seenDois.has(cleanDoi)) continue;
      seenDois.add(cleanDoi);
    }

    // 3. Check near-duplicate titles (>85% word similarity)
    if (title) {
      const isNearDuplicate = seenTitles.some(
        (entry) => wordSimilarity(entry.title, title) >= 0.85
      );

      if (isNearDuplicate) {
        continue;
      }
    }

    if (normUrl) seenUrls.add(normUrl);
    if (title) seenTitles.push({ title, source });
    uniqueSources.push(source);
  }

  return uniqueSources;
}
