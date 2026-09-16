// src/store/ui.ts
// UI State Management including AI Source Selection, Full-Screen Workspace, Themes, and Layouts

'use client';

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Source } from '@/types/research';

interface UIState {
  theme: 'dark' | 'light' | 'system';
  sidebarOpen: boolean;
  commandPaletteOpen: boolean;
  workspaceModalOpen: boolean; // Full-screen workspace overlay
  settingsModalOpen: boolean; // LLM & Ollama settings modal
  sortBy: 'relevance' | 'date';
  filterType: string | null;
  searchQuery: string;
  selectedSourceIds: string[]; // General card selection
  aiSelectedSourceIds: string[]; // Explicit "Use for AI" selection
  compareMode: boolean;

  // Source Detail Modal State
  activeSourceModalId: string | null;
  activeSourceModalTab: 'details' | 'chat' | 'insights' | 'open';

  setTheme: (theme: 'dark' | 'light' | 'system') => void;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setWorkspaceModalOpen: (open: boolean) => void;
  toggleWorkspaceModal: () => void;
  setSettingsModalOpen: (open: boolean) => void;
  setSortBy: (sortBy: 'relevance' | 'date') => void;
  setFilterType: (type: string | null) => void;
  setSearchQuery: (query: string) => void;
  toggleSourceSelection: (sourceId: string) => void;
  clearSelection: () => void;
  setCompareMode: (mode: boolean) => void;

  // Source Detail Modal Actions
  openSourceModal: (sourceId: string, initialTab?: 'details' | 'chat' | 'insights' | 'open') => void;
  setSourceModalTab: (tab: 'details' | 'chat' | 'insights' | 'open') => void;
  closeSourceModal: () => void;

  // AI Source Selection Actions (Persistent across tabs)
  toggleAISelection: (sourceId: string) => void;
  selectAllForAI: (sourceIds: string[]) => void;
  clearAllForAI: () => void;
  selectTopRelevantForAI: (sources: Source[], count?: number) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      theme: 'dark',
      sidebarOpen: true,
      commandPaletteOpen: false,
      workspaceModalOpen: false,
      settingsModalOpen: false,
      sortBy: 'relevance',
      filterType: null,
      searchQuery: '',
      selectedSourceIds: [],
      aiSelectedSourceIds: [],
      compareMode: false,
      activeSourceModalId: null,
      activeSourceModalTab: 'details',

      setTheme: (theme) => set({ theme }),
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
      setWorkspaceModalOpen: (open) => set({ workspaceModalOpen: open }),
      toggleWorkspaceModal: () => set((state) => ({ workspaceModalOpen: !state.workspaceModalOpen })),
      setSettingsModalOpen: (open) => set({ settingsModalOpen: open }),
      setSortBy: (sortBy) => set({ sortBy }),
      setFilterType: (filterType) => set({ filterType }),
      setSearchQuery: (searchQuery) => set({ searchQuery }),
      toggleSourceSelection: (sourceId) =>
        set((state) => ({
          selectedSourceIds: state.selectedSourceIds.includes(sourceId)
            ? state.selectedSourceIds.filter((id) => id !== sourceId)
            : [...state.selectedSourceIds, sourceId],
        })),
      clearSelection: () => set({ selectedSourceIds: [], compareMode: false }),
      setCompareMode: (compareMode) => set({ compareMode }),

      // Source Detail Modal Actions
      openSourceModal: (sourceId, initialTab = 'details') =>
        set({ activeSourceModalId: sourceId, activeSourceModalTab: initialTab }),
      setSourceModalTab: (tab) => set({ activeSourceModalTab: tab }),
      closeSourceModal: () => set({ activeSourceModalId: null, activeSourceModalTab: 'details' }),

      // AI Selection Helpers
      toggleAISelection: (sourceId) =>
        set((state) => ({
          aiSelectedSourceIds: state.aiSelectedSourceIds.includes(sourceId)
            ? state.aiSelectedSourceIds.filter((id) => id !== sourceId)
            : [...state.aiSelectedSourceIds, sourceId],
        })),
      selectAllForAI: (sourceIds) =>
        set((state) => ({
          aiSelectedSourceIds: Array.from(new Set([...state.aiSelectedSourceIds, ...sourceIds])),
        })),
      clearAllForAI: () => set({ aiSelectedSourceIds: [] }),
      selectTopRelevantForAI: (sources, count = 5) => {
        const sorted = [...sources].sort((a, b) => (b.relevanceScore || 0) - (a.relevanceScore || 0));
        const topIds = sorted.slice(0, count).map((s) => s.id);
        set({ aiSelectedSourceIds: topIds });
      },
    }),
    {
      name: 'ai-research-ui',
      partialize: (state) => ({
        theme: state.theme,
        sidebarOpen: state.sidebarOpen,
        sortBy: state.sortBy,
        aiSelectedSourceIds: state.aiSelectedSourceIds,
      }),
    }
  )
);
