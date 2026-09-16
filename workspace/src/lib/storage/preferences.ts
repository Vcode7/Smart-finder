// src/lib/storage/preferences.ts
// localStorage UI preferences

export interface UIPreferences {
  theme: 'dark' | 'light' | 'system';
  sidebarOpen: boolean;
  workspaceLayout: '1' | '2' | '3' | '4';
  sortBy: 'relevance' | 'date';
}

const DEFAULT: UIPreferences = {
  theme: 'dark',
  sidebarOpen: true,
  workspaceLayout: '2',
  sortBy: 'relevance',
};

const KEY = 'ai-research-prefs';

export function getPreferences(): UIPreferences {
  if (typeof window === 'undefined') return DEFAULT;
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT;
    return { ...DEFAULT, ...JSON.parse(raw) };
  } catch {
    return DEFAULT;
  }
}

export function savePreferences(prefs: Partial<UIPreferences>): void {
  if (typeof window === 'undefined') return;
  try {
    const current = getPreferences();
    localStorage.setItem(KEY, JSON.stringify({ ...current, ...prefs }));
  } catch {
    // ignore
  }
}
