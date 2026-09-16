// src/lib/sources/context-builder.ts
// Source-Specific Context Builder with Token Optimization & Total Null/Undefined Safety

import type { Source } from '@/types/research';
import { GROQ_MAX_SOURCE_CHARS } from '@/lib/groq/config';

/**
 * Builds tailored, high-density context for a single source.
 * Strips redundant metadata and keeps only high-signal research content.
 */
export function buildSourceContext(source: Source, maxChars: number = GROQ_MAX_SOURCE_CHARS): string {
  if (!source) return '';
  const parts: string[] = [];

  // Header line
  const typeLabel = (source.type || 'source').toUpperCase();
  const titleLabel = source.title || 'Untitled Source';
  const providerLabel = source.provider ? ` | ${source.provider}` : '';
  const dateLabel = source.date ? ` | ${String(source.date).slice(0, 10)}` : '';
  parts.push(`[${typeLabel}] "${titleLabel}"${providerLabel}${dateLabel}`);

  // Author / Creator
  if (source.author) {
    parts.push(`Author(s): ${source.author}`);
  }

  // Modality-specific high-signal data
  if (source.type === 'video') {
    if (source.duration) parts.push(`Duration: ${source.duration}`);
    if (source.transcript) {
      parts.push(`Transcript:\n${source.transcript.slice(0, maxChars)}`);
    } else if (source.description) {
      parts.push(`Key Video Notes:\n${source.description.slice(0, maxChars)}`);
    }
  } else if (source.type === 'paper') {
    if (source.journal) parts.push(`Publication/Venue: ${source.journal}`);
    if (source.citationCount !== undefined) parts.push(`Citations: ${source.citationCount}`);
    if (source.abstract) {
      parts.push(`Abstract:\n${source.abstract.slice(0, maxChars)}`);
    } else if (source.description) {
      parts.push(`Summary:\n${source.description.slice(0, maxChars)}`);
    }
  } else if (source.type === 'report') {
    if (source.description) {
      parts.push(`Report Executive Summary & Directives:\n${source.description.slice(0, maxChars)}`);
    }
  } else {
    // Article / Web
    if (source.description) {
      parts.push(`Content Excerpt:\n${source.description.slice(0, maxChars)}`);
    }
  }

  // AI insights if already available
  if (source.aiInsights?.summary && parts.join('\n').length < maxChars) {
    parts.push(`Key Synthesized Takeaway: ${source.aiInsights.summary.slice(0, 300)}`);
  }

  let fullText = parts.join('\n');
  if (fullText.length > maxChars) {
    fullText = fullText.slice(0, maxChars) + '… [content truncated]';
  }

  return fullText;
}

/**
 * Builds composite multi-source context with numbered dividers and total char capping.
 */
export function buildMultiSourceContext(sources: Source[], maxTotalChars: number = 32000): string {
  if (!Array.isArray(sources)) return '';
  const validSources = sources.filter(Boolean);
  const perSourceLimit = Math.max(1000, Math.floor(maxTotalChars / Math.max(1, validSources.length)));

  return validSources
    .map((source, index) => {
      const sourceText = buildSourceContext(source, perSourceLimit);
      return `--- SOURCE ${index + 1} (ID: ${source.id}) ---\n${sourceText}`;
    })
    .join('\n\n');
}
