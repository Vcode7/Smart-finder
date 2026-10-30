'use client';
// src/store/searchSources.ts — which library sources (Local, Koha, DSpace) a search uses.
// Internet search is separate (useChatStore.enableInternetSources).
//
// The viewer's choice is kept as the sources they switched OFF, so a source an admin sets up
// later is searched by default. Only the sources the server reports as available are used.

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { apiErrorMessage, readJson } from '@/lib/utils/api';
import type { CatalogSourceId, SearchSourceId } from '@/types/research';

export interface SourceInfo {
  id: SearchSourceId;
  label: string;
  available: boolean;
  /** Its URL is set, so an admin can switch it on from the search page */
  configured?: boolean;
}

const LOCAL_ONLY: SourceInfo[] = [{ id: 'local', label: 'Local Files', available: true, configured: true }];

interface SearchSourcesState {
  sources: SourceInfo[];
  off: SearchSourceId[];
  loaded: boolean;
  load: () => Promise<void>;
  toggle: (id: SearchSourceId) => void;
  /** Use exactly these sources (a search picked from history); unavailable ones are ignored. */
  use: (ids: SearchSourceId[]) => void;
  /** Admin: switch a set-up catalog on or off for everyone. Throws with the server's message. */
  setEnabled: (id: CatalogSourceId, enabled: boolean) => Promise<void>;
}

export const useSearchSourcesStore = create<SearchSourcesState>()(
  persist(
    (set, get) => ({
      sources: LOCAL_ONLY,
      off: [],
      loaded: false,
      load: async () => {
        try {
          const res = await fetch('/api/catalogs/sources');
          if (!res.ok) return;
          const data: { sources?: SourceInfo[] } = await res.json();
          if (data.sources?.length) set({ sources: data.sources, loaded: true });
        } catch {
          // Backend unreachable: local only until it answers
        }
      },
      toggle: (id) => set((s) => ({ off: s.off.includes(id) ? s.off.filter((x) => x !== id) : [...s.off, id] })),
      use: (ids) => set({ off: get().sources.map((s) => s.id).filter((id) => !ids.includes(id)) }),
      setEnabled: async (id, enabled) => {
        const res = await fetch(`/api/catalogs/sources/${id}/enabled`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }),
        });
        if (!res.ok) throw new Error(apiErrorMessage(await readJson(res), 'Could not change it'));
        // Switched on for everyone: also on for this viewer, even if they had left it out before
        if (enabled) set((s) => ({ off: s.off.filter((x) => x !== id) }));
        await get().load();
      },
    }),
    { name: 'sf-search-sources', partialize: (s) => ({ off: s.off }) }
  )
);

/** The sources a search should send: available and not switched off. */
export function selectedSources(s: Pick<SearchSourcesState, 'sources' | 'off'>): SearchSourceId[] {
  return s.sources.filter((x) => x.available && !s.off.includes(x.id)).map((x) => x.id);
}
