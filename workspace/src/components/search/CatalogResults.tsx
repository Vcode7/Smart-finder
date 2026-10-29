'use client';
// Library Catalogs section of the search page: Koha records and DSpace items, ranked on the same
// relevance scale as local files, each linked to its exact record. Files are linked where they
// live (DSpace asks for a login when a file needs one); SmartFinder never serves them itself.

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle, BookMarked, CheckCircle2, ChevronDown, ChevronUp, Clock, Download, ExternalLink, FileText,
  Library, Loader2, Lock, ScanText, Square,
} from 'lucide-react';
import TopicChips from '@/components/search/TopicChips';
import type { CatalogFile, CatalogRecord, CatalogSourceId, SourceStatus } from '@/types/research';

export const CATALOG_META: Record<CatalogSourceId, { label: string; short: string; color: string; bg: string }> = {
  koha: { label: 'Koha Catalog', short: 'Koha', color: 'var(--viz-5)', bg: 'color-mix(in srgb, var(--viz-5) 14%, transparent)' },
  dspace: { label: 'DSpace Repository', short: 'DSpace', color: 'var(--viz-3)', bg: 'color-mix(in srgb, var(--viz-3) 14%, transparent)' },
};

const ORIGIN_LABEL: Record<string, string> = {
  ocr: 'text read from the image', document: 'the attached document', speech: 'what the recording says',
};

interface Props {
  records: CatalogRecord[];
  statuses: SourceStatus[];
  only: CatalogSourceId | null;            // a domain tab showing one catalog
  searching: boolean;
  query?: string | null;                   // what the catalogs were asked
  queryOrigin?: string | null;             // typed | ocr | document | speech
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
}

export default function CatalogResults({ records, statuses, only, searching, query, queryOrigin, selectedIds, onToggle }: Props) {
  const shownStatuses = statuses.filter((s) => !only || s.source === only);
  const [sub, setSub] = useState<CatalogSourceId | 'all'>('all');
  const pick = only ?? (sub === 'all' ? null : sub);
  const shown = pick ? records.filter((r) => r.source === pick) : records;
  const count = (s: CatalogSourceId) => records.filter((r) => r.source === s).length;
  const title = only ? CATALOG_META[only].label : 'Library Catalogs';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0"
            style={{ background: only ? CATALOG_META[only].bg : 'var(--accent-muted)', color: only ? CATALOG_META[only].color : 'var(--accent)' }}>
            <Library className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
              {title} ({searching ? 'Searching...' : shown.length})
            </h2>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Catalog records and repository items, ranked by meaning and linked to the original
            </p>
          </div>
        </div>
        {!only && statuses.length > 1 && (
          <div className="flex flex-wrap items-center gap-1">
            {(['all', ...statuses.map((s) => s.source)] as const).map((id) => {
              const on = sub === id;
              return (
                <button key={id} type="button" aria-pressed={on} onClick={() => setSub(id)}
                  className="px-2.5 py-1 rounded-xl text-xs font-semibold transition-all"
                  style={{
                    background: on ? 'var(--accent-muted)' : 'transparent',
                    color: on ? 'var(--accent)' : 'var(--text-muted)',
                    border: on ? '1px solid var(--accent)' : '1px solid transparent',
                  }}>
                  {id === 'all' ? 'All' : CATALOG_META[id].short} ({searching ? '...' : id === 'all' ? records.length : count(id)})
                </button>
              );
            })}
          </div>
        )}
      </div>

      {!searching && (shownStatuses.length > 0 || (query && queryOrigin && queryOrigin !== 'typed')) && (
        <div className="flex flex-wrap items-center gap-2 text-[11px]" aria-live="polite">
          {shownStatuses.map((s) => <StatusChip key={s.source} status={s} />)}
          {query && queryOrigin && queryOrigin !== 'typed' && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full max-w-full"
              style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
              title={query}>
              <ScanText className="w-3 h-3 flex-shrink-0" style={{ color: 'var(--accent)' }} aria-hidden />
              <span className="truncate">Searched with {ORIGIN_LABEL[queryOrigin] ?? 'the upload'}: “{query}”</span>
            </span>
          )}
        </div>
      )}

      {searching ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[1, 2].map((i) => (
            <div key={i} className="p-4 rounded-2xl border animate-pulse space-y-3" style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}>
              <div className="h-4 w-24 bg-zinc-800 rounded" />
              <div className="h-5 w-3/4 bg-zinc-800 rounded" />
              <div className="h-3 w-full bg-zinc-800/70 rounded" />
            </div>
          ))}
        </div>
      ) : shown.length === 0 ? (
        <div className="p-8 rounded-3xl text-center" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
          <BookMarked className="w-8 h-8 mx-auto mb-2 opacity-30" style={{ color: 'var(--text-muted)' }} />
          <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>No matching catalog records</p>
          <p className="text-[11px] mt-1" style={{ color: 'var(--text-muted)' }}>
            {shownStatuses.some((s) => s.status !== 'ok') ? 'A catalog could not be searched: see the notice above.' : 'Try other words or a wider relevance threshold.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {shown.map((rec, idx) => (
            <CatalogCard key={rec.id} record={rec} rank={idx} selected={selectedIds.has(rec.id)} onToggle={() => onToggle(rec.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

function StatusChip({ status }: { status: SourceStatus }) {
  const meta = CATALOG_META[status.source];
  const ok = status.status === 'ok';
  const Icon = ok ? CheckCircle2 : status.status === 'timeout' ? Clock : AlertTriangle;
  const more = ok && status.total && status.total > status.count ? ` of ${status.total.toLocaleString()}` : '';
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full max-w-full"
      style={{
        background: ok ? meta.bg : 'color-mix(in srgb, var(--warning) 14%, transparent)',
        color: ok ? meta.color : 'var(--warning)',
      }}
      title={status.message ?? undefined}>
      <Icon className="w-3 h-3 flex-shrink-0" aria-hidden />
      <span className="font-semibold">{meta.short}</span>
      <span className="truncate" style={{ color: 'var(--text-secondary)' }}>
        {ok ? `${status.count}${more} fetched · ${(status.ms / 1000).toFixed(1)} s` : status.message || status.status}
      </span>
    </span>
  );
}

function CatalogCard({ record: rec, rank, selected, onToggle }: { record: CatalogRecord; rank: number; selected: boolean; onToggle: () => void }) {
  const meta = CATALOG_META[rec.source];
  const [open, setOpen] = useState(false);
  const [thumbOk, setThumbOk] = useState(Boolean(rec.thumbnail));
  const score = Math.round((rec.relevanceScore || 0) * 100);
  const byline = [rec.authors.slice(0, 3).join('; ') + (rec.authors.length > 3 ? ' et al.' : ''), rec.year, rec.publisher]
    .filter(Boolean).join(' · ');

  return (
    <motion.div
      whileHover={{ scale: 1.005 }}
      className="p-4 rounded-2xl transition-all relative group flex flex-col gap-3"
      style={{
        background: 'var(--bg-elevated)',
        border: selected ? `1.5px solid ${meta.color}` : '1px solid var(--border)',
      }}
    >
      <div className="flex items-start gap-3">
        <button type="button" className="mt-0.5 flex-shrink-0" onClick={onToggle}
          aria-pressed={selected} aria-label={selected ? 'Deselect for AI' : 'Select for AI'}>
          {selected ? <CheckCircle2 className="w-5 h-5" style={{ color: meta.color }} /> : <Square className="w-5 h-5 text-zinc-500 hover:text-zinc-300" />}
        </button>
        {thumbOk && rec.thumbnail && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={rec.thumbnail} alt="" onError={() => setThumbOk(false)}
            className="w-12 h-16 rounded-md object-cover flex-shrink-0" style={{ border: '1px solid var(--border)' }} />
        )}
        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: meta.bg, color: meta.color }}>
              {meta.short}
            </span>
            {rank === 0 && (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40">Top match</span>
            )}
            {rec.itemType && (
              <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full truncate max-w-[9rem]"
                style={{ background: 'var(--bg-active)', color: 'var(--text-secondary)' }}>
                {rec.itemType}
              </span>
            )}
            <span className="ml-auto font-mono text-[11px] font-bold" style={{ color: meta.color }}>{score}% Match</span>
          </div>
          <a href={rec.recordUrl} target="_blank" rel="noopener noreferrer"
            className="block text-xs font-bold line-clamp-2 hover:underline" style={{ color: 'var(--text-primary)' }}>
            {rec.title}
          </a>
          {byline && <p className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }} title={byline}>{byline}</p>}
          {rec.snippet && (
            <p className="text-xs leading-relaxed line-clamp-3 select-text" style={{ color: 'var(--text-secondary)' }}>{rec.snippet}</p>
          )}
          <TopicChips topics={rec.subjects} />

          {rec.alsoIn.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>
              <span>Also in:</span>
              {rec.alsoIn.map((a) => (
                <a key={a.id} href={a.recordUrl} target="_blank" rel="noopener noreferrer"
                  className="px-1.5 py-0.5 rounded-full font-semibold hover:underline"
                  style={{ background: 'var(--bg-active)', color: 'var(--text-secondary)' }} title={a.title}>
                  {a.source === 'local' ? 'Your Files' : CATALOG_META[a.source as CatalogSourceId]?.short ?? a.source}
                </a>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <a href={rec.recordUrl} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1 px-2 py-1 rounded-xl text-[11px] font-semibold transition-colors"
              style={{ background: meta.bg, color: meta.color }}
              title={`Open this ${rec.source === 'koha' ? 'record in Koha' : 'item in DSpace'}`}>
              Open record <ExternalLink className="w-3 h-3" />
            </a>
            <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
              className="flex items-center gap-1 px-2 py-1 rounded-xl text-[11px] font-semibold hover:bg-[var(--bg-hover)]"
              style={{ color: 'var(--text-secondary)' }}>
              {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {rec.filesDeferred || rec.files.length ? 'Details & files' : 'Details'}
              {!rec.filesDeferred && rec.files.length > 0 && <span>({rec.files.length})</span>}
            </button>
          </div>

          {open && <RecordDetails record={rec} />}
        </div>
      </div>
    </motion.div>
  );
}

function RecordDetails({ record: rec }: { record: CatalogRecord }) {
  const ids = [
    ...rec.isbn.map((v) => ({ label: 'ISBN', value: v, href: null as string | null })),
    ...(rec.doi ? [{ label: 'DOI', value: rec.doi, href: `https://doi.org/${rec.doi}` }] : []),
    ...(rec.handle ? [{ label: 'Handle', value: rec.handle, href: `https://hdl.handle.net/${rec.handle}` }] : []),
  ];
  return (
    <div className="mt-1 p-3 rounded-xl space-y-2 text-[11px]" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
      {rec.abstract && <p className="leading-relaxed select-text" style={{ color: 'var(--text-secondary)' }}>{rec.abstract}</p>}
      {rec.authors.length > 3 && <p style={{ color: 'var(--text-muted)' }}><b>Authors:</b> {rec.authors.join('; ')}</p>}
      {rec.subjects.length > 0 && <p style={{ color: 'var(--text-muted)' }}><b>Subjects:</b> {rec.subjects.join(' · ')}</p>}
      {ids.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1" style={{ color: 'var(--text-muted)' }}>
          {ids.map((i) => (
            <span key={`${i.label}:${i.value}`}>
              <b>{i.label}</b>{' '}
              {i.href ? <a href={i.href} target="_blank" rel="noopener noreferrer" className="underline">{i.value}</a> : i.value}
            </span>
          ))}
        </div>
      )}
      {rec.filesDeferred ? <DSpaceFiles uuid={rec.nativeId} /> : <FileList files={rec.files} empty="No digital files are linked to this record." />}
    </div>
  );
}

function DSpaceFiles({ uuid }: { uuid: string }) {
  const [state, setState] = useState<{ files: CatalogFile[]; message: string | null } | null>(null);
  useEffect(() => {
    let live = true;
    fetch(`/api/catalogs/dspace/items/${uuid}/files`)
      .then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (live) setState({ files: data.files ?? [], message: r.ok ? data.message ?? null : data.detail ?? 'The files could not be listed.' });
      })
      .catch(() => live && setState({ files: [], message: 'The files could not be listed. Check the connection.' }));
    return () => { live = false; };
  }, [uuid]);
  if (!state) {
    return <p className="flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}><Loader2 className="w-3 h-3 animate-spin" /> Listing files…</p>;
  }
  return <FileList files={state.files} empty={state.message ?? 'This item has no files.'} />;
}

function formatSize(bytes?: number | null): string {
  if (!bytes) return '';
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileList({ files, empty }: { files: CatalogFile[]; empty: string }) {
  if (files.length === 0) return <p style={{ color: 'var(--text-muted)' }}>{empty}</p>;
  return (
    <ul className="space-y-1">
      {files.map((f) => {
        const locked = f.access === 'restricted';
        return (
          <li key={f.url} className="flex items-center gap-2 min-w-0">
            {locked ? <Lock className="w-3 h-3 flex-shrink-0" style={{ color: 'var(--warning)' }} aria-label="Restricted" />
              : <FileText className="w-3 h-3 flex-shrink-0" style={{ color: 'var(--text-muted)' }} aria-hidden />}
            <a href={f.url} target="_blank" rel="noopener noreferrer" className="truncate hover:underline min-w-0"
              style={{ color: 'var(--text-primary)' }} title={f.name}>
              {f.name}
            </a>
            <span className="flex-shrink-0" style={{ color: 'var(--text-muted)' }}>
              {[f.mimeType?.split('/').pop()?.toUpperCase(), formatSize(f.size)].filter(Boolean).join(' · ')}
            </span>
            <span className="ml-auto flex-shrink-0 flex items-center gap-1" style={{ color: locked ? 'var(--warning)' : 'var(--text-muted)' }}>
              {locked ? 'Sign in to the repository to open' : <><Download className="w-3 h-3" aria-hidden />{f.access === 'open' ? 'Open access' : 'Open'}</>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
