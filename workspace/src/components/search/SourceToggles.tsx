'use client';
// "Search in" toggles of the search page: Local Files, Koha Catalog, DSpace Repository, each on or
// off independently. Everything switched on is searched together. Live Internet is a separate switch.
//
// Koha and DSpace are always shown. One that is not set up yet is dimmed: an admin's click switches
// it on (URL already saved) or opens Settings → Library Integrations; other users see why it is off.

import { useEffect, useState } from 'react';
import { Check, Database, Library, Loader2, Plus } from 'lucide-react';
import { toast } from 'sonner';
import { selectedSources, useSearchSourcesStore, type SourceInfo } from '@/store/searchSources';
import { useAuthStore } from '@/store/auth';
import { useUIStore } from '@/store/ui';
import type { CatalogSourceId, SearchSourceId } from '@/types/research';

const ICON: Record<SearchSourceId, typeof Database> = { local: Database, koha: Library, dspace: Library };
const COLOR: Record<SearchSourceId, string> = { local: 'var(--accent)', koha: 'var(--viz-5)', dspace: 'var(--viz-3)' };
const CATALOGS: SourceInfo[] = [
  { id: 'koha', label: 'Koha Catalog', available: false },
  { id: 'dspace', label: 'DSpace Repository', available: false },
];

export default function SourceToggles({ disabled }: { disabled?: boolean }) {
  const { sources, off, load, toggle, setEnabled } = useSearchSourcesStore();
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin');
  const openSettings = useUIStore((s) => s.setSettingsModalOpen);
  const [busy, setBusy] = useState<SearchSourceId | null>(null);
  useEffect(() => { load(); }, [load]);

  // Before the server answers, still show the catalogs (as not set up) so the row does not jump
  const shown = [...sources, ...CATALOGS.filter((c) => !sources.some((s) => s.id === c.id))];
  const on = selectedSources({ sources, off });

  const switchOn = async (s: SourceInfo) => {
    if (!s.configured) {
      toast.info(`Give the ${s.label.split(' ')[0]} URL in Settings → Library Integrations, then Save.`);
      openSettings(true);
      return;
    }
    setBusy(s.id);
    try {
      await setEnabled(s.id as CatalogSourceId, true);
      toast.success(`${s.label} is now searched with your files`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not switch it on');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 px-4 py-3 rounded-2xl shadow-sm sm:col-span-2"
      style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
      <span className="text-xs font-bold mr-1" style={{ color: 'var(--text-primary)' }} id="search-in-label">Search in</span>
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-labelledby="search-in-label">
        {shown.map((s) => {
          const Icon = ICON[s.id];
          if (!s.available) {
            const name = s.label.split(' ')[0];
            const hint = isAdmin
              ? s.configured ? `${s.label} is switched off: click to search it` : `${s.label} is not connected: click to set it up`
              : `${s.label} is not connected yet: an admin can set it up in Settings`;
            return (
              <button key={s.id} type="button" disabled={disabled || !isAdmin || busy === s.id} aria-pressed={false}
                onClick={() => switchOn(s)} title={hint} aria-label={hint}
                className="flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-semibold border-dashed transition-colors hover:bg-[var(--bg-hover)] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                style={{ color: 'var(--text-muted)', border: '1px dashed var(--border)' }}>
                {busy === s.id ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden />
                  : isAdmin ? <Plus className="w-3 h-3" aria-hidden /> : <Icon className="w-3 h-3" aria-hidden />}
                {s.label}
                <span className="text-[10px] font-normal opacity-80">
                  {isAdmin ? (s.configured ? 'off' : `connect ${name}`) : 'not connected'}
                </span>
              </button>
            );
          }
          const active = on.includes(s.id);
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
    </div>
  );
}
