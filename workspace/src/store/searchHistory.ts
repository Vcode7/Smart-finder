'use client';
// src/store/searchHistory.ts — the signed-in user's Smart Finder searches (kept on the server)

import { create } from 'zustand';

export interface SearchHistoryItem {
  id: string;
  query: string;
  internet: boolean;
  /** Library sources it searched; empty for searches saved before sources existed. */
  sources?: string[];
  resultCount: number;
  updatedAt: string;
}

interface SearchHistoryState {
  searches: SearchHistoryItem[];
  /** A search picked in the sidebar; the search page runs it and clears this. */
  pending: SearchHistoryItem | null;

  refresh: () => Promise<void>;
  remove: (id: string) => Promise<void>;
  clear: () => Promise<void>;
  runAgain: (item: SearchHistoryItem) => void;
  clearPending: () => void;
  /** Forget everything about the signed-in user's searches (logout). */
  reset: () => void;
}

export const useSearchHistoryStore = create<SearchHistoryState>()((set) => ({
  searches: [],
  pending: null,

  refresh: async () => {
    try {
      const res = await fetch('/api/search-history');
      if (res.ok) set({ searches: (await res.json()).searches || [] });
    } catch {
      // Backend unreachable: keep the current list
    }
  },
  remove: async (id) => {
    const res = await fetch(`/api/search-history/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete search');
    set((s) => ({ searches: s.searches.filter((x) => x.id !== id) }));
  },
  clear: async () => {
    const res = await fetch('/api/search-history', { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to clear search history');
    set({ searches: [] });
  },
  runAgain: (pending) => set({ pending }),
  clearPending: () => set({ pending: null }),
  reset: () => set({ searches: [], pending: null }),
}));
