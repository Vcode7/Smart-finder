// src/lib/sources/selection.ts
// Intelligent Source Selection with User Priority, Diversity, and Strict Token Budgeting

import type { Source, SourceType } from '@/types/research';
import { deduplicateSources } from './deduplication';
import { rankSources } from './ranking';
import { buildSourceContext } from './context-builder';
import { estimateTokens } from '@/lib/groq/token-budget';
import {
  GROQ_MAX_SOURCES_PER_REQUEST,
  GROQ_INPUT_BUDGETS,
  type GroqOperation,
} from '@/lib/groq/config';

export interface SourceSelectionResult {
  selectedSources: Source[];
  excludedSources: Source[];
  manuallySelectedCount: number;
  autoSelectedCount: number;
  estimatedInputTokens: number;
  selectionReasons: Record<string, string>;
}

export interface SelectSourcesOptions {
  sources: Source[];
  selectedSourceIds?: string[];
  topic?: string;
  operation: GroqOperation;
  maxTokens?: number;
  maxSources?: number;
}

/**
 * Intelligently selects and budgets sources for an AI operation.
 * 
 * CORE PRINCIPLE: User selection > Semantic similarity > Search ranking > Source quality > Diversity
 */
export function selectSourcesForAI({
  sources,
  selectedSourceIds = [],
  topic = '',
  operation,
  maxTokens,
  maxSources,
}: SelectSourcesOptions): SourceSelectionResult {
  if (!sources || sources.length === 0) {
    return {
      selectedSources: [],
      excludedSources: [],
      manuallySelectedCount: 0,
      autoSelectedCount: 0,
      estimatedInputTokens: 0,
      selectionReasons: {},
    };
  }

  // 1. Deduplicate sources
  const uniqueSources = deduplicateSources(sources);

  // 2. Set hard budget limits for the requested operation
  const targetMaxSources = maxSources || GROQ_MAX_SOURCES_PER_REQUEST;
  const targetMaxTokens = maxTokens || GROQ_INPUT_BUDGETS[operation] || 8000;

  const userSelectedSet = new Set(selectedSourceIds);
  const selectedSources: Source[] = [];
  const selectionReasons: Record<string, string> = {};
  let currentEstimatedTokens = 200; // Base prompt tokens overhead

  // 3. Separate manually selected sources from available pool
  const userSelectedSources = uniqueSources.filter((s) => userSelectedSet.has(s.id));
  const otherSources = uniqueSources.filter((s) => !userSelectedSet.has(s.id));

  // 4. STEP 1: Add ALL user-selected sources first (Highest Priority)
  for (const source of userSelectedSources) {
    if (selectedSources.length >= targetMaxSources) break;

    const context = buildSourceContext(source);
    const sourceTokens = estimateTokens(context) + 30; // + separator overhead

    if (currentEstimatedTokens + sourceTokens <= targetMaxTokens || selectedSources.length === 0) {
      selectedSources.push(source);
      currentEstimatedTokens += sourceTokens;
      selectionReasons[source.id] = 'Manually selected by user (Priority)';
    }
  }

  const manuallySelectedCount = selectedSources.length;

  // 5. STEP 2: If capacity remains, rank other sources and fill with diversity
  if (selectedSources.length < targetMaxSources && currentEstimatedTokens < targetMaxTokens) {
    const scoredOthers = rankSources(otherSources, [], topic);
    
    // Track categories already included for diversity weighting
    const categoryCount: Record<SourceType, number> = {
      video: selectedSources.filter((s) => s.type === 'video').length,
      paper: selectedSources.filter((s) => s.type === 'paper').length,
      article: selectedSources.filter((s) => s.type === 'article').length,
      report: selectedSources.filter((s) => s.type === 'report').length,
      web: selectedSources.filter((s) => s.type === 'web').length,
    };

    // First pass: Prioritize under-represented top categories (Diversity)
    for (const scored of scoredOthers) {
      if (selectedSources.length >= targetMaxSources) break;
      if (selectedSources.some((s) => s.id === scored.source.id)) continue;

      const type = scored.source.type;
      // If we don't have this category yet and it's high quality
      if (categoryCount[type] === 0 && scored.score >= 50) {
        const context = buildSourceContext(scored.source);
        const sourceTokens = estimateTokens(context) + 30;

        if (currentEstimatedTokens + sourceTokens <= targetMaxTokens) {
          selectedSources.push(scored.source);
          categoryCount[type]++;
          currentEstimatedTokens += sourceTokens;
          selectionReasons[scored.source.id] = `Top ${type} source (${scored.score}% quality/relevance score)`;
        }
      }
    }

    // Second pass: Fill any remaining capacity by pure highest score
    for (const scored of scoredOthers) {
      if (selectedSources.length >= targetMaxSources) break;
      if (selectedSources.some((s) => s.id === scored.source.id)) continue;

      const context = buildSourceContext(scored.source);
      const sourceTokens = estimateTokens(context) + 30;

      if (currentEstimatedTokens + sourceTokens <= targetMaxTokens) {
        selectedSources.push(scored.source);
        currentEstimatedTokens += sourceTokens;
        selectionReasons[scored.source.id] = `High relevance recommendation (${scored.score}% score)`;
      }
    }
  }

  const autoSelectedCount = selectedSources.length - manuallySelectedCount;
  const selectedIdsSet = new Set(selectedSources.map((s) => s.id));
  const excludedSources = uniqueSources.filter((s) => !selectedIdsSet.has(s.id));

  return {
    selectedSources,
    excludedSources,
    manuallySelectedCount,
    autoSelectedCount,
    estimatedInputTokens: currentEstimatedTokens,
    selectionReasons,
  };
}
