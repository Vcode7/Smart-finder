// src/hooks/useFetchMore.ts
// Hook to fetch additional results for a specific source type only

'use client';

import { useState, useCallback } from 'react';
import { useResearchStore } from '@/store/research';
import { toast } from 'sonner';
import type { SourceType, Source } from '@/types/research';

const TYPE_LABELS: Record<SourceType, string> = {
  video: 'videos',
  paper: 'academic papers',
  article: 'articles & news',
  report: 'policy reports',
  web: 'web references',
};

export function useFetchMore(sessionId: string) {
  const { sessions, addSources, setProviderStatuses } = useResearchStore();
  const [loadingType, setLoadingType] = useState<SourceType | null>(null);

  const session = sessions.find((s) => s.id === sessionId);

  const fetchMore = useCallback(
    async (type: SourceType) => {
      if (!session) {
        toast.error('Active research session not found');
        return;
      }

      if (loadingType) return;

      const typeLabel = TYPE_LABELS[type] || type;
      setLoadingType(type);

      const existingTypeSources = session.sources.filter((s) => s.type === type);
      const existingUrls = session.sources.map((s) => s.url);
      const existingTitles = session.sources.map((s) => s.title);
      const currentCount = existingTypeSources.length;
      // Progressive Limit: 8 (initial) -> 12 (1st fetch more) -> 16 (2nd fetch more) -> 20, etc.
      const targetLimit = Math.max(12, currentCount + 4);
      const currentPage = Math.floor(currentCount / 4) + 1;

      try {
        toast.loading(`Fetching more ${typeLabel} (increasing to ${targetLimit} results)...`, {
          id: `fetch-more-${type}`,
        });

        const res = await fetch('/api/search/fetch-more', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sessionId,
            topic: session.topic,
            type,
            currentCount,
            targetLimit,
            offset: currentCount,
            page: currentPage,
            existingUrls,
            existingTitles,
          }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.message || `Failed to fetch more ${typeLabel}`);
        }

        const data = await res.json();
        const newSources: Source[] = data.sources || [];

        if (newSources.length > 0) {
          addSources(sessionId, newSources);

          // Update provider statuses if available
          if (data.providerStatus) {
            const providerKey = type === 'report' ? 'reports' : type;
            const updatedStatuses = {
              ...(session.providerStatuses || {}),
              [providerKey]: {
                ...data.providerStatus,
                count: existingTypeSources.length + newSources.length,
              },
            };
            setProviderStatuses(sessionId, updatedStatuses);
          }

          toast.success(`Discovered ${newSources.length} more ${typeLabel}!`, {
            id: `fetch-more-${type}`,
          });
        } else {
          toast.info(`No additional unique ${typeLabel} found for "${session.topic}".`, {
            id: `fetch-more-${type}`,
          });
        }
      } catch (err: unknown) {
        const errorMsg = err instanceof Error ? err.message : `Failed to fetch more ${typeLabel}`;
        console.error('[useFetchMore] Error:', err);
        toast.error(errorMsg, { id: `fetch-more-${type}` });
      } finally {
        setLoadingType(null);
      }
    },
    [session, sessionId, loadingType, addSources, setProviderStatuses]
  );

  return {
    fetchMore,
    loadingType,
    isFetching: loadingType !== null,
  };
}
