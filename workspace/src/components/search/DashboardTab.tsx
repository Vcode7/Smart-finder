'use client';
// Dashboard tab: analytics over the files within a relative threshold of the best match
// (default 30%). All charts are computed in the browser from the dashboard rows, so picking a
// bar filters every other chart at once.

import { useMemo, useState, type ReactNode } from 'react';
import { AlertTriangle, ExternalLink, Loader2, RotateCcw, SlidersHorizontal, X } from 'lucide-react';
import BarList from '@/components/search/charts/BarList';
import ColumnChart from '@/components/search/charts/ColumnChart';
import TopicChips from '@/components/search/TopicChips';
import {
  CATEGORY_COLOR, NO_FILTERS, byCategory, byDate, byExtension, byFolder, byLibrary, byScore, byTopic,
  dateLabel, filterExcept, folderKey, formatBytes, type Filters,
} from '@/lib/search/charts';
import {
  DASHBOARD_CHARTS, DEFAULT_DASHBOARD_THRESHOLD, useSearchViewStore, type ChartId, type DateField, type DateGrain,
} from '@/store/searchView';
import type { AsyncData, DashboardData } from '@/types/insights';
import { withBase } from '@/lib/base-path';

const PRESETS = [10, 20, 30, 50, 75];
const DATE_FIELDS: { id: DateField; label: string }[] = [
  { id: 'modifiedAt', label: 'Modified' }, { id: 'takenAt', label: 'Taken' }, { id: 'indexedAt', label: 'Indexed' },
];
const DATE_GRAINS: { id: DateGrain; label: string }[] = [{ id: 'year', label: 'Year' }, { id: 'month', label: 'Month' }, { id: 'day', label: 'Day' }];
const FILE_LIST_SIZE = 20;

interface Props {
  state: AsyncData<DashboardData>;
  onRetry: () => void;
}

export default function DashboardTab({ state, onRetry }: Props) {
  const { dashboardThreshold, visibleCharts, dateField, dateGrain, setDashboardThreshold, toggleChart, setDateField, setDateGrain } =
    useSearchViewStore();
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [draft, setDraft] = useState<string | null>(null);        // threshold text while it is being typed
  const [pickerOpen, setPickerOpen] = useState(false);
  const [listAll, setListAll] = useState(false);

  const data = state.data;
  const files = useMemo(() => data?.files ?? [], [data]);
  const setFilter = <K extends keyof Filters>(key: K, value: Filters[K]) => setFilters((f) => ({ ...f, [key]: value }));
  const activeCount = Object.values(filters).filter((v) => v !== null).length;

  const commitThreshold = (text: string) => {
    setDraft(null);
    const n = Number(text);
    if (Number.isFinite(n) && n > 0) {
      setDashboardThreshold(n);
      setFilters(NO_FILTERS);
    }
  };

  // Every chart sees the files that pass all filters except its own dimension
  const view = useMemo(() => {
    const multiLibrary = new Set(files.map((f) => f.libraryId ?? '')).size > 1;
    const all = filterExcept(files, filters, null, dateField, dateGrain);
    const dated = byDate(filterExcept(files, filters, 'date', dateField, dateGrain), dateField, dateGrain);
    return {
      all,
      multiLibrary,
      categories: byCategory(filterExcept(files, filters, 'category', dateField, dateGrain)),
      extensions: byExtension(filterExcept(files, filters, 'ext', dateField, dateGrain)),
      folders: byFolder(filterExcept(files, filters, 'folder', dateField, dateGrain), multiLibrary),
      libraries: byLibrary(filterExcept(files, filters, 'library', dateField, dateGrain)),
      scores: byScore(filterExcept(files, filters, 'score', dateField, dateGrain)),
      topics: byTopic(filterExcept(files, filters, 'topic', dateField, dateGrain)),
      dates: dated.buckets,
      undated: dated.undated,
      counts: {
        category: filterExcept(files, filters, 'category', dateField, dateGrain).length,
        ext: filterExcept(files, filters, 'ext', dateField, dateGrain).length,
        folder: filterExcept(files, filters, 'folder', dateField, dateGrain).length,
        library: filterExcept(files, filters, 'library', dateField, dateGrain).length,
        topic: filterExcept(files, filters, 'topic', dateField, dateGrain).length,
      },
    };
  }, [files, filters, dateField, dateGrain]);

  const shown = view.all;
  const totalBytes = useMemo(() => shown.reduce((s, f) => s + (f.fileSize || 0), 0), [shown]);
  const folderCount = useMemo(() => new Set(shown.map(folderKey)).size, [shown]);
  const typeCount = useMemo(() => new Set(shown.map((f) => (f.fileType || '').toLowerCase())).size, [shown]);

  // Labels of the active filters, for the chips
  const chips: { key: keyof Filters; label: string }[] = [];
  if (filters.category) chips.push({ key: 'category', label: view.categories.find((b) => b.key === filters.category)?.label ?? filters.category });
  if (filters.ext) chips.push({ key: 'ext', label: `.${filters.ext}` });
  if (filters.folder) chips.push({ key: 'folder', label: view.folders.find((b) => b.key === filters.folder)?.label ?? 'Folder' });
  if (filters.library) chips.push({ key: 'library', label: view.libraries.find((b) => b.key === filters.library)?.label ?? 'Library' });
  if (filters.date) chips.push({ key: 'date', label: dateLabel(filters.date) });
  if (filters.score !== null) chips.push({ key: 'score', label: `${Math.round(filters.score * 100)}–${Math.round(filters.score * 100) + 5}% relevance` });
  if (filters.topic) chips.push({ key: 'topic', label: view.topics.find((b) => b.key === filters.topic)?.label ?? filters.topic });

  // ── states without data ────────────────────────────────────────────────────
  if (state.status === 'idle') {
    return <Notice icon={<AlertTriangle className="w-5 h-5" />} title="Dashboard not available" text="This kind of search does not keep its results for analysis. Run a normal search to see the dashboard." />;
  }
  if (state.status === 'error') {
    return (
      <Notice icon={<AlertTriangle className="w-5 h-5" style={{ color: 'var(--warning)' }} />} title="The dashboard could not be built" text={state.error ?? 'Something went wrong.'}>
        <button type="button" onClick={onRetry} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-white" style={{ background: 'var(--accent)' }}>
          <RotateCcw className="w-3.5 h-3.5" /> Try again
        </button>
      </Notice>
    );
  }
  if (!data) return <DashboardSkeleton />;

  const refreshing = state.status === 'loading';
  const visible = (id: ChartId) => visibleCharts.includes(id);
  const cutoffPct = Math.round(data.totals.minScore * 100);

  return (
    <div className="space-y-4" aria-busy={refreshing}>
      {/* Threshold + chart picker */}
      <div className="p-4 rounded-2xl flex flex-wrap items-center justify-between gap-3" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
        <div className="space-y-1.5 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>Analyse files within</span>
            <div className="flex items-center gap-1 flex-wrap" role="group" aria-label="Relative threshold">
              {PRESETS.map((p) => (
                <button
                  key={p}
                  type="button"
                  aria-pressed={dashboardThreshold === p}
                  onClick={() => { setDashboardThreshold(p); setFilters(NO_FILTERS); setDraft(null); }}
                  className="px-2.5 py-1 rounded-lg text-[11px] font-bold transition-colors"
                  style={{
                    background: dashboardThreshold === p ? 'var(--accent)' : 'var(--bg-active)',
                    color: dashboardThreshold === p ? '#fff' : 'var(--text-secondary)',
                  }}
                  title={p === DEFAULT_DASHBOARD_THRESHOLD ? 'Default' : undefined}
                >
                  {p}%
                </button>
              ))}
              <label className="flex items-center gap-1 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                <span className="sr-only">Custom threshold in percent</span>
                <input
                  type="number" min={1} max={100} inputMode="numeric"
                  value={draft ?? String(dashboardThreshold)}
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={(e) => draft !== null && commitThreshold(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && commitThreshold((e.target as HTMLInputElement).value)}
                  className="w-14 px-1.5 py-1 rounded-lg outline-none text-[11px] font-mono"
                  style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                />
                %
              </label>
            </div>
            {refreshing && <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: 'var(--accent)' }} aria-label="Updating" />}
          </div>
          <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
            of the best match: relevance {cutoffPct}% and up, {data.totals.kept} of {data.totals.candidates} files found.
          </p>
        </div>

        <div className="relative">
          <button
            type="button"
            aria-expanded={pickerOpen}
            onClick={() => setPickerOpen((v) => !v)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold"
            style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" /> Charts ({visibleCharts.length}/{DASHBOARD_CHARTS.length})
          </button>
          {pickerOpen && (
            <div className="absolute right-0 mt-1 z-20 p-2 rounded-xl shadow-lg min-w-[11rem]" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
              {DASHBOARD_CHARTS.map((c) => (
                <label key={c.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs cursor-pointer hover:bg-[var(--bg-hover)]" style={{ color: 'var(--text-primary)' }}>
                  <input type="checkbox" checked={visible(c.id)} onChange={() => toggleChart(c.id)} />
                  {c.label}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <Kpi label="Files" value={shown.length} sub={activeCount ? `of ${files.length} in range` : `of ${data.totals.candidates} found`} />
        <Kpi label="Top match" value={`${Math.round(data.totals.topScore * 100)}%`} sub="best relevance" />
        <Kpi label="Cutoff" value={`${cutoffPct}%`} sub="lowest included" />
        <Kpi label="Size" value={formatBytes(totalBytes)} sub="of these files" />
        <Kpi label="File types" value={typeCount} sub="distinct" />
        <Kpi label="Folders" value={folderCount} sub="distinct" />
      </div>

      {/* Active filters */}
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Active filters">
          {chips.map((c) => (
            <button
              key={c.key}
              type="button"
              onClick={() => setFilter(c.key, null as never)}
              className="inline-flex items-center gap-1 pl-2.5 pr-1.5 py-1 rounded-full text-[11px] font-semibold max-w-full"
              style={{ background: 'var(--accent-muted)', color: 'var(--accent)' }}
              title="Remove filter"
            >
              <span className="truncate">{c.label}</span> <X className="w-3 h-3 flex-shrink-0" aria-hidden />
              <span className="sr-only">remove filter</span>
            </button>
          ))}
          <button type="button" onClick={() => setFilters(NO_FILTERS)} className="text-[11px] underline" style={{ color: 'var(--text-secondary)' }}>
            Clear all
          </button>
        </div>
      )}

      {files.length === 0 ? (
        <Notice title="No files in range" text="Nothing is within this threshold of the best match. Try a wider threshold." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {visible('types') && (
            <Card title="File types" sub="By kind and by extension">
              <BarList buckets={view.categories} total={view.counts.category} activeKey={filters.category} onSelect={(k) => setFilter('category', k)} colorOf={(k) => CATEGORY_COLOR[k] ?? 'var(--viz-1)'} />
              <div className="my-3 border-t" style={{ borderColor: 'var(--border)' }} />
              <BarList buckets={view.extensions} total={view.counts.ext} activeKey={filters.ext} onSelect={(k) => setFilter('ext', k)} limit={6} />
            </Card>
          )}
          {visible('folders') && (
            <Card title="Folders" sub="Where the files live">
              <BarList buckets={view.folders} total={view.counts.folder} activeKey={filters.folder} onSelect={(k) => setFilter('folder', k)} limit={8} />
            </Card>
          )}
          {visible('dates') && (
            <Card
              title="Dates"
              sub={`Files by ${DATE_FIELDS.find((d) => d.id === dateField)?.label.toLowerCase()} ${dateGrain}`}
              action={
                <div className="flex items-center gap-1.5 flex-wrap justify-end">
                  <select
                    value={dateField}
                    onChange={(e) => { setDateField(e.target.value as DateField); setFilter('date', null); }}
                    aria-label="Date to chart"
                    className="px-1.5 py-1 rounded-lg text-[11px] outline-none"
                    style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                  >
                    {DATE_FIELDS.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
                  </select>
                  <div className="flex rounded-lg overflow-hidden" role="group" aria-label="Group dates by" style={{ border: '1px solid var(--border)' }}>
                    {DATE_GRAINS.map((g) => (
                      <button
                        key={g.id} type="button" aria-pressed={dateGrain === g.id}
                        onClick={() => { setDateGrain(g.id); setFilter('date', null); }}
                        className="px-2 py-1 text-[11px] font-semibold"
                        style={{ background: dateGrain === g.id ? 'var(--accent-muted)' : 'transparent', color: dateGrain === g.id ? 'var(--accent)' : 'var(--text-secondary)' }}
                      >
                        {g.label}
                      </button>
                    ))}
                  </div>
                </div>
              }
            >
              <ColumnChart buckets={view.dates} activeKey={filters.date} onSelect={(k) => setFilter('date', k)} />
              {view.undated > 0 && (
                <p className="text-[11px] mt-2" style={{ color: 'var(--text-muted)' }}>{view.undated} file{view.undated === 1 ? ' has' : 's have'} no {DATE_FIELDS.find((d) => d.id === dateField)?.label.toLowerCase()} date.</p>
              )}
            </Card>
          )}
          {visible('scores') && (
            <Card title="Relevance" sub="Files per 5% of relevance">
              <ColumnChart buckets={view.scores} activeKey={filters.score === null ? null : String(filters.score)} onSelect={(k) => setFilter('score', k === null ? null : Number(k))} />
            </Card>
          )}
          {visible('libraries') && view.libraries.length > 0 && (
            <Card title="Libraries" sub="Which library holds the files">
              <BarList buckets={view.libraries} total={view.counts.library} activeKey={filters.library} onSelect={(k) => setFilter('library', k)} />
            </Card>
          )}
          {visible('topics') && (
            <Card
              title="Topics"
              sub={data.totals.topicsFor < data.totals.kept
                ? `From the indexed text of the ${data.totals.topicsFor} best files`
                : 'From the indexed text and summaries'}
            >
              {view.topics.length === 0 && files.length > 0 && !filters.topic
                ? <p className="text-xs py-6 text-center" style={{ color: 'var(--text-muted)' }}>No topics were found in these files.</p>
                : <BarList buckets={view.topics} total={view.counts.topic} activeKey={filters.topic} onSelect={(k) => setFilter('topic', k)} limit={10} />}
            </Card>
          )}
        </div>
      )}

      {/* The files behind the charts */}
      {files.length > 0 && (
        <Card title={`Matching files (${shown.length})`} sub="Best first">
          {shown.length === 0 ? (
            <p className="text-xs py-4 text-center" style={{ color: 'var(--text-muted)' }}>No files match these filters.</p>
          ) : (
            <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
              {(listAll ? shown : shown.slice(0, FILE_LIST_SIZE)).map((f) => (
                <li key={f.id} className="py-2 flex items-start gap-3" style={{ borderColor: 'var(--border)' }}>
                  <span className="text-[11px] font-mono font-bold w-10 flex-shrink-0 pt-0.5" style={{ color: 'var(--accent)' }}>{Math.round(f.relevanceScore * 100)}%</span>
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="text-xs font-semibold truncate" style={{ color: 'var(--text-primary)' }} title={f.relPath}>{f.title}</p>
                    <p className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }}>
                      {f.libraryName ? `${f.libraryName} · ` : ''}{f.folder || '(top level)'} · {formatBytes(f.fileSize)}
                    </p>
                    <TopicChips topics={f.topics} events={f.events} />
                  </div>
                  {f.libraryId && (
                    <a href={withBase(`/api/knowledge/${f.sourceId}/file`)} target="_blank" rel="noopener noreferrer"
                      className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-semibold flex-shrink-0"
                      style={{ background: 'var(--accent-muted)', color: 'var(--accent)' }}>
                      Open <ExternalLink className="w-3 h-3" aria-hidden />
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
          {shown.length > FILE_LIST_SIZE && (
            <button type="button" onClick={() => setListAll((v) => !v)} className="text-[11px] font-semibold pt-2" style={{ color: 'var(--accent)' }}>
              {listAll ? 'Show fewer' : `Show all ${shown.length}`}
            </button>
          )}
        </Card>
      )}
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: ReactNode; sub: string }) {
  return (
    <div className="p-3 rounded-2xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
      <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>{label}</p>
      <p className="text-xl font-extrabold tabular-nums mt-0.5" style={{ color: 'var(--text-primary)' }}>{value}</p>
      <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{sub}</p>
    </div>
  );
}

function Card({ title, sub, action, children }: { title: string; sub?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="p-4 rounded-2xl space-y-3 min-w-0" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
      <header className="flex items-start justify-between gap-2 flex-wrap">
        <div>
          <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{title}</h3>
          {sub && <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{sub}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

function Notice({ icon, title, text, children }: { icon?: ReactNode; title: string; text: string; children?: ReactNode }) {
  return (
    <div className="p-8 rounded-3xl text-center space-y-2" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
      {icon && <div className="flex justify-center" style={{ color: 'var(--text-muted)' }}>{icon}</div>}
      <p className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{title}</p>
      <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{text}</p>
      {children}
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider" style={{ color: 'var(--accent)' }}>
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Analysing results…
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }, (_, i) => <div key={i} className="h-20 rounded-2xl animate-pulse" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }} />)}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {Array.from({ length: 4 }, (_, i) => <div key={i} className="h-56 rounded-2xl animate-pulse" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }} />)}
      </div>
    </div>
  );
}
