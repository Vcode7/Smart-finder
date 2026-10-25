'use client';
// Tab bar of the search results: Top Results (the ranked files) | Dashboard | Summary.
// Dashboard and Summary load in the background, so their tabs show a spinner, a count or a
// warning while the user looks at the results.

import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { AlertTriangle, BarChart3, FileText, Loader2, Sparkles } from 'lucide-react';

export type ResultTabId = 'top' | 'dashboard' | 'summary';
export type TabStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface ResultTabInfo {
  id: ResultTabId;
  status: TabStatus;
  badge?: string | number | null;       // shown when ready
}

const META: Record<ResultTabId, { label: string; icon: typeof FileText }> = {
  top: { label: 'Top Results', icon: FileText },
  dashboard: { label: 'Dashboard', icon: BarChart3 },
  summary: { label: 'Summary', icon: Sparkles },
};

export const tabId = (id: ResultTabId) => `result-tab-${id}`;
export const panelId = (id: ResultTabId) => `result-panel-${id}`;

interface Props {
  active: ResultTabId;
  onChange: (id: ResultTabId) => void;
  tabs: ResultTabInfo[];
  trailing?: ReactNode;
}

export default function ResultTabs({ active, onChange, tabs, trailing }: Props) {
  const refs = useRef<Partial<Record<ResultTabId, HTMLButtonElement | null>>>({});

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = tabs.findIndex((t) => t.id === active);
    let next = -1;
    if (e.key === 'ArrowRight') next = (i + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next < 0) return;
    e.preventDefault();
    onChange(tabs[next].id);
    refs.current[tabs[next].id]?.focus();
  };

  return (
    <div className="flex items-center justify-between gap-3 flex-wrap">
      <div
        role="tablist"
        aria-label="Search results views"
        onKeyDown={onKeyDown}
        className="flex items-center gap-1 p-1 rounded-2xl overflow-x-auto max-w-full"
        style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
      >
        {tabs.map((t) => {
          const { label, icon: Icon } = META[t.id];
          const selected = t.id === active;
          return (
            <button
              key={t.id}
              ref={(el) => { refs.current[t.id] = el; }}
              id={tabId(t.id)}
              role="tab"
              type="button"
              aria-selected={selected}
              aria-controls={panelId(t.id)}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(t.id)}
              className="flex items-center gap-1.5 sm:gap-2 px-2.5 sm:px-4 py-2 rounded-xl text-xs sm:text-sm font-bold whitespace-nowrap transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
              style={{
                background: selected ? 'var(--accent)' : 'transparent',
                color: selected ? '#fff' : 'var(--text-secondary)',
              }}
            >
              <Icon className="w-4 h-4 hidden sm:block" aria-hidden />
              <span>{label}</span>
              {t.status === 'loading' && (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
                  <span className="sr-only">loading</span>
                </>
              )}
              {t.status === 'error' && (
                <>
                  <AlertTriangle className="w-3.5 h-3.5" style={{ color: selected ? '#fff' : 'var(--warning)' }} aria-hidden />
                  <span className="sr-only">failed</span>
                </>
              )}
              {t.status === 'ready' && t.badge !== undefined && t.badge !== null && (
                <span
                  className="px-1.5 rounded-full text-[10px] font-mono"
                  style={{ background: selected ? 'rgba(255,255,255,0.25)' : 'var(--bg-active)', color: selected ? '#fff' : 'var(--text-muted)' }}
                >
                  {t.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
      {trailing}
    </div>
  );
}
