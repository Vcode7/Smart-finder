// src/lib/sources/ranking.ts
// Multi-factor Source Ranking Engine with Total Null/Undefined Safety

import type { Source, SourceType } from '@/types/research';

export interface ScoredSource {
  source: Source;
  score: number;
  isUserSelected: boolean;
  reasons: string[];
}

/**
 * Calculates a comprehensive priority score for a source.
 * Priority order: User Selection > Semantic Similarity > Search Ranking > Source Quality > Content Richness
 */
export function scoreSource(
  source: Source,
  userSelectedIds: Set<string>,
  topic: string
): ScoredSource {
  const isUserSelected = userSelectedIds.has(source.id);
  const reasons: string[] = [];
  let score = 0;

  // 1. User Selection Priority (Highest possible priority)
  if (isUserSelected) {
    score += 10000;
    reasons.push('Manually selected by user');
  }

  // 2. Semantic Relevance Score (Base 0 - 100)
  const rel = source.relevanceScore || 50;
  score += rel;
  reasons.push(`${rel}% topic relevance`);

  // 3. Source Quality Level
  if (source.quality?.level === 'high') {
    score += 25;
    reasons.push('High quality verified publisher');
  } else if (source.quality?.level === 'medium') {
    score += 12;
  }

  // 4. Content Richness & Specific Modality Value
  if (source.type === 'video') {
    if (source.hasTranscript) {
      score += 20;
      reasons.push('Full video transcript available');
    }
    if (source.duration) score += 5;
  } else if (source.type === 'paper') {
    if (source.abstract && source.abstract.length > 100) {
      score += 20;
      reasons.push('Complete academic abstract');
    }
    if (source.citationCount && source.citationCount > 5) {
      score += Math.min(15, Math.floor(source.citationCount / 5));
      reasons.push(`${source.citationCount} academic citations`);
    }
  } else if (source.type === 'report') {
    score += 15; // Policy reports carry high institutional authority
    reasons.push('Institutional policy report');
  } else if (source.type === 'article') {
    if (source.description && source.description.length > 200) {
      score += 10;
    }
  }

  // 5. Official / Government / Reputable Institution keyword bonus in title/provider
  const trustedEntities = ['gov', 'niti aayog', 'pib', 'nature', 'ieee', 'arxiv', 'science', 'reuters', 'bloomberg', 'isro'];
  const providerLower = (source.provider || '').toLowerCase();
  const urlLower = (source.url || '').toLowerCase();
  if (trustedEntities.some((t) => providerLower.includes(t) || urlLower.includes(t))) {
    score += 15;
    reasons.push('Authoritative institutional domain');
  }

  return {
    source,
    score,
    isUserSelected,
    reasons,
  };
}

/**
 * Ranks sources considering quality, relevance, and user priority.
 */
export function rankSources(
  sources: Source[],
  selectedSourceIds: string[] = [],
  topic: string = ''
): ScoredSource[] {
  if (!Array.isArray(sources)) return [];
  const selectedSet = new Set(selectedSourceIds);
  const scored = sources.filter(Boolean).map((s) => scoreSource(s, selectedSet, topic));

  // Sort descending by score
  return scored.sort((a, b) => b.score - a.score);
}
