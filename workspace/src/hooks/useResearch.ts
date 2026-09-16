// src/hooks/useResearch.ts
// Initiates search across real APIs, collects genuine sources and tracks provider diagnostics

'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useResearchStore } from '@/store/research';
import { toast } from 'sonner';
import type { Source } from '@/types/research';

interface SearchProgress {
  stage: string;
  progress: number;
  done: boolean;
}

export function useResearch() {
  const router = useRouter();
  const { createSession, setSources, setProviderStatuses } = useResearchStore();
  const [isSearching, setIsSearching] = useState(false);
  const [progress, setProgress] = useState<SearchProgress>({ stage: '', progress: 0, done: false });

  const startResearch = useCallback(async (topic: string) => {
    if (!topic.trim()) {
      toast.error('Please enter a research topic');
      return;
    }

    setIsSearching(true);
    setProgress({ stage: 'Initializing research workspace...', progress: 10, done: false });

    const sessionId = createSession(topic);

    try {
      setProgress({ stage: 'Querying live source providers (YouTube, Semantic Scholar, NewsAPI, Web)...', progress: 40, done: false });

      const res = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, sessionId }),
      });

      if (!res.ok) throw new Error('Search API request failed');

      const data = await res.json();
      const allSources: Source[] = [
        ...(data.videos || []),
        ...(data.papers || []),
        ...(data.articles || []),
        ...(data.reports || []),
        ...(data.web || []),
      ];

      setProgress({ stage: 'Processing provider responses...', progress: 85, done: false });
      setSources(sessionId, allSources);

      if (data.providerStatuses) {
        setProviderStatuses(sessionId, data.providerStatuses);
      }

      setProgress({ stage: 'Workspace ready!', progress: 100, done: true });

      if (allSources.length > 0) {
        toast.success(`Discovered ${allSources.length} verified sources from live providers`);
      } else {
        toast.warning('No live sources returned. Check API configurations in .env.local.');
      }

      // Immediately navigate to workspace (Wait for user action before calling AI)
      router.push(`/research/${sessionId}`);
    } catch (err) {
      console.error('[useResearch] Discovery error:', err);
      toast.error('Research query failed. Check backend logs for details.');
      setIsSearching(false);
    }
  }, [createSession, setSources, setProviderStatuses, router]);

  return { startResearch, isSearching, progress };
}
