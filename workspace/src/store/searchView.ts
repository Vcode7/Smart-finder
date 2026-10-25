// src/store/searchView.ts
// Per-viewer preferences of the search page's Dashboard tab, kept in localStorage.

'use client';

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export const DASHBOARD_CHARTS = [
  { id: 'types', label: 'File types' },
  { id: 'folders', label: 'Folders' },
  { id: 'dates', label: 'Dates' },
  { id: 'scores', label: 'Relevance' },
  { id: 'libraries', label: 'Libraries' },
  { id: 'topics', label: 'Topics' },
  { id: 'kinds', label: 'By file type' },
] as const;

export type ChartId = (typeof DASHBOARD_CHARTS)[number]['id'];
/** 'best' = the earliest date the file really has: taken (EXIF) if present, else modified, else indexed. */
export type DateField = 'best' | 'modifiedAt' | 'takenAt' | 'indexedAt';
export type DateGrain = 'year' | 'month' | 'day';

interface SearchViewState {
  dashboardThreshold: number;           // percent: files within this much of the best score
  visibleCharts: ChartId[];
  dateField: DateField;
  dateGrain: DateGrain;
  setDashboardThreshold: (pct: number) => void;
  toggleChart: (id: ChartId) => void;
  setDateField: (f: DateField) => void;
  setDateGrain: (g: DateGrain) => void;
}

export const DEFAULT_DASHBOARD_THRESHOLD = 30;

export const useSearchViewStore = create<SearchViewState>()(
  persist(
    (set) => ({
      dashboardThreshold: DEFAULT_DASHBOARD_THRESHOLD,
      visibleCharts: DASHBOARD_CHARTS.map((c) => c.id),
      dateField: 'best',
      dateGrain: 'month',
      setDashboardThreshold: (pct) =>
        set({ dashboardThreshold: Math.min(100, Math.max(1, Math.round(pct) || DEFAULT_DASHBOARD_THRESHOLD)) }),
      toggleChart: (id) =>
        set((s) => ({
          visibleCharts: s.visibleCharts.includes(id)
            ? s.visibleCharts.filter((c) => c !== id)
            : DASHBOARD_CHARTS.map((c) => c.id).filter((c) => c === id || s.visibleCharts.includes(c)),
        })),
      setDateField: (dateField) => set({ dateField }),
      setDateGrain: (dateGrain) => set({ dateGrain }),
    }),
    {
      name: 'sf-search-view',
      version: 2,
      // v1 defaulted to the modified date; the adaptive "best" date replaces it
      migrate: (persisted) => {
        const s = (persisted ?? {}) as Partial<SearchViewState>;
        // the per-file-type section is new, so a saved chart choice should not hide it
        const charts = (s.visibleCharts ?? []).includes('kinds') ? s.visibleCharts : [...(s.visibleCharts ?? []), 'kinds'];
        return {
          ...s, visibleCharts: charts,
          dateField: s.dateField && s.dateField !== 'modifiedAt' ? s.dateField : 'best',
        } as SearchViewState;
      },
    }
  )
);
