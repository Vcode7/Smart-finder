// src/lib/utils/scoring.ts
import type { Source, SourceQuality, SourceType } from '@/types/research';

const HIGH_QUALITY_DOMAINS = [
  'gov', 'edu', 'nature.com', 'science.org', 'pubmed.ncbi.nlm.nih.gov',
  'scholar.google', 'arxiv.org', 'bbc.com', 'reuters.com', 'apnews.com',
  'nytimes.com', 'theguardian.com', 'who.int', 'un.org',
];

const MEDIUM_QUALITY_DOMAINS = [
  'wikipedia.org', 'medium.com', 'forbes.com', 'techcrunch.com',
  'wired.com', 'bloomberg.com', 'ft.com', 'economist.com',
];

export function assessSourceQuality(url: string, type: SourceType): SourceQuality {
  try {
    const domain = new URL(url).hostname.toLowerCase();

    if (type === 'paper') {
      return { level: 'high', reason: 'Peer-reviewed research paper', details: 'Academic source from research database' };
    }
    if (type === 'report') {
      return { level: 'high', reason: 'Official report', details: 'Formal report or government document' };
    }
    if (HIGH_QUALITY_DOMAINS.some(d => domain.includes(d))) {
      const isGov = domain.endsWith('.gov') || domain.includes('.gov.');
      const isEdu = domain.endsWith('.edu') || domain.includes('.edu.');
      const reason = isGov ? 'Government source' : isEdu ? 'Educational institution' : 'Major authoritative publication';
      return { level: 'high', reason, details: domain };
    }
    if (MEDIUM_QUALITY_DOMAINS.some(d => domain.includes(d))) {
      return { level: 'medium', reason: 'Major publication', details: domain };
    }
    return { level: 'medium', reason: 'Online source', details: domain };
  } catch {
    return { level: 'low', reason: 'Unknown source', details: 'Could not assess domain' };
  }
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 11) + Date.now().toString(36);
}

export function sortSources(sources: Source[], by: 'relevance' | 'date'): Source[] {
  if (by === 'relevance') {
    return [...sources].sort((a, b) => b.relevanceScore - a.relevanceScore);
  }
  return [...sources].sort((a, b) => {
    const da = a.date ? new Date(a.date).getTime() : 0;
    const db = b.date ? new Date(b.date).getTime() : 0;
    return db - da;
  });
}
