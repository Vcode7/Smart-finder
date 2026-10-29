'use client';
// "Search in" toggles of the search page: Local Files, Koha Catalog, DSpace Repository, each on or
// off independently. Everything switched on is searched together. Live Internet is a separate switch.

import { useEffect } from 'react';
import { Check, Database, Library, Settings } from 'lucide-react';
import { selectedSources, useSearchSourcesStore } from '@/store/searchSources';
import { useAuthStore } from '@/store/auth';
import { useUIStore } from '@/store/ui';
import type { SearchSourceId } from '@/types/research';

const ICON: Record<SearchSourceId, typeof Database> = { local: Database, koha: Library, dspace: Library };
const COLOR: Record<SearchSourceId, string> = { local: 'var(--accent)', koha: 'var(--viz-5)', dspace: 'var(--viz-3)' };

export default function SourceToggles({ disabled }: { disabled?: boolean }) {
  const { sources, off, loaded, load, toggle } = useSearchSourcesStore();
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin');
  const openSettings = useUIStore((s) => s.setSettingsModalOpen);
  useEffect(() => { load(); }, [load]);

  const on = selectedSources({ sources, off });
  const unconfigured = loaded ? sources.filter((s) => !s.available) : [];
  const offered = sources.filter((s) => s.available);

  return (
    <div className="flex flex-wrap items-center gap-2 px-4 py-3 rounded-2xl shadow-sm sm:col-span-2"
      style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
      <span className="text-xs font-bold mr-1" style={{ color: 'var(--text-primary)' }} id="search-in-label">Search in</span>
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-labelledby="search-in-label">
        {offered.map((s) => {
          const active = on.includes(s.id);
          const Icon = ICON[s.id];
          return (
            <button key={s.id} type="button" disabled={disabled} aria-pressed={active} onClick={() => toggle(s.id)}
              className="flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                background: active ? `color-mix(in srgb, ${COLOR[s.id]} 16%, transparent)` : 'transparent',
                color: active ? COLOR[s.id] : 'var(--text-muted)',
                border: `1px solid ${active ? COLOR[s.id] : 'var(--border)'}`,
              }}
              title={active ? `Searching ${s.label}: click to leave it out` : `Not searching ${s.label}: click to include it`}>
              {active ? <Check className="w-3 h-3" aria-hidden /> : <Icon className="w-3 h-3" aria-hidden />}
              {s.label}
            </button>
          );
        })}
      </div>
      <span className="text-[11px] ml-auto" style={{ color: on.length ? 'var(--text-muted)' : 'var(--warning)' }}>
        {on.length === 0 ? 'No library source on: only the internet can be searched' : on.length > 1 ? 'Searched together, ranked by relevance' : ''}
      </span>
      {isAdmin && unconfigured.length > 0 && (
        <button type="button" onClick={() => openSettings(true)}
          className="flex items-center gap-1 text-[11px] underline" style={{ color: 'var(--text-muted)' }}
          title="Connect Koha or DSpace in Settings">
          <Settings className="w-3 h-3" aria-hidden /> Connect {unconfigured.map((s) => s.label.split(' ')[0]).join(' or ')}
        </button>
      )}
    </div>
  );
}
