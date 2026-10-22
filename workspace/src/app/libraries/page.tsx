'use client';
// src/app/libraries/page.tsx — folder libraries (indexed in place), unlimited uploads, indexing progress

import { useCallback, useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Eye, EyeOff, FolderOpen, FolderPlus,
  HardDrive, Library as LibraryIcon, Link2, Loader2, Pause, Play, RefreshCw, RotateCcw, Search,
  Trash2, Upload, X, XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import Sidebar from '@/components/layout/Sidebar';
import { FolderBrowserModal } from '@/components/modals/FolderBrowserModal';
import { useAuthStore } from '@/store/auth';
import { apiErrorMessage, readJson } from '@/lib/utils/api';
import { UploadPanel } from '@/components/library/UploadPanel';

// ── API types ────────────────────────────────────────────────────────────────
interface LibrarySummary {
  id: string;
  name: string;
  kind: 'folder' | 'uploads' | 'linked';
  // Server paths, errors and scan details are sent to administrators only
  path?: string | null;
  indexPath?: string;
  online: boolean;
  watch: boolean;
  watching: boolean;
  paused: boolean;
  error?: string | null;
  counts?: Record<string, number>;
  total?: number;
  bytes?: number;
  scan?: { state: 'running' | 'done' | 'failed'; report?: Record<string, number>; error?: string } | null;
}

interface IndexingStatus {
  running: boolean;
  paused: boolean;
  current: null | { library: string; file: string; kind: string; stage: string; done: number; total: number; elapsed: number };
  queued: number;
  processing: number;
  indexed: number;
  failed: number;
  transcriptsPending: number;
  captionsPending?: number;
  soundsPending?: number;
  imageVectorsPending?: number;
  enrichmentPending?: number;
  lastError: string | null;
}

interface SourceRow {
  id: string;
  relPath: string;
  kind: string;
  file_size: number;
  status: string;
  error_message: string | null;
  indexed_at: string | null;
}

// ── helpers ──────────────────────────────────────────────────────────────────
function formatBytes(bytes = 0): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const v = bytes / 1024 ** i;
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

const STAGE_LABEL: Record<string, string> = {
  extracting: 'Reading file', text: 'Embedding text', images: 'Analysing images and frames',
  transcribing: 'Transcribing speech', 'describing pictures': 'Describing pictures',
  'analysing sound': 'Analysing sounds', 'updating image search': 'Updating image search',
};

const isLocalBrowser = () =>
  typeof window !== 'undefined' && ['localhost', '127.0.0.1', '::1', '[::1]'].includes(window.location.hostname);

async function api<T = Record<string, unknown>>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const data = await readJson<T>(res);
  if (!res.ok) throw new Error(apiErrorMessage(data, `Request failed (${res.status})`));
  return (data || {}) as T;
}

const jsonInit = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
});

// ── page ─────────────────────────────────────────────────────────────────────
export default function LibrariesPage() {
  const { user } = useAuthStore();
  const isAdmin = user?.role === 'admin';
  const [libraries, setLibraries] = useState<LibrarySummary[]>([]);
  const [indexing, setIndexing] = useState<IndexingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [browser, setBrowser] = useState<null | 'folder' | 'files'>(null);
  const [manualPath, setManualPath] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    return api<{ libraries: LibrarySummary[]; indexing: IndexingStatus }>('/api/libraries')
      .then((data) => {
        setLibraries(data.libraries || []);
        setIndexing(data.indexing || null);
      })
      .catch(() => { /* keep the last good state; the next poll retries */ })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const tick = () => { if (document.visibilityState === 'visible') refresh(); };
    tick();
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, [refresh]);

  const attach = async (path: string) => {
    setBusy(true);
    try {
      const lib = await api<LibrarySummary>('/api/libraries', jsonInit('POST', { path }));
      toast.success(`Added “${lib.name}”. Indexing starts in the background; your files stay where they are.`);
      setManualPath('');
      refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not add the folder');
    } finally {
      setBusy(false);
    }
  };

  const addFiles = async (paths: string[]) => {
    if (!paths.length) return;
    setBusy(true);
    try {
      const data = await api<{ results: Array<{ path: string; status: string; error?: string }> }>(
        '/api/libraries/files', jsonInit('POST', { paths }));
      const added = data.results.filter((r) => r.status === 'added').length;
      const failed = data.results.filter((r) => r.status === 'error');
      if (added) toast.success(`${added} file${added === 1 ? '' : 's'} added — indexed in place, not copied`);
      failed.slice(0, 3).forEach((r) => toast.error(`${r.path.split(/[\\/]/).pop()}: ${r.error}`));
      refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not add the files');
    } finally {
      setBusy(false);
    }
  };

  const pickNative = async (kind: 'folder' | 'files') => {
    setBusy(true);
    try {
      if (kind === 'folder') {
        const r = await api<{ path: string | null }>('/api/system/pick-folder', { method: 'POST' });
        if (r.path) await attach(r.path);
      } else {
        const r = await api<{ paths: string[] }>('/api/system/pick-files', { method: 'POST' });
        if (r.paths?.length) await addFiles(r.paths);
      }
    } catch {
      // No desktop dialog on the server (e.g. a Linux service without a display): browse in the app
      setBrowser(kind);
    } finally {
      setBusy(false);
    }
  };

  const toggleAllPaused = async () => {
    if (!indexing) return;
    try {
      await api(indexing.paused ? '/api/libraries/resume' : '/api/libraries/pause', { method: 'POST' });
      refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Request failed');
    }
  };

  const local = isLocalBrowser();
  const uploadTargets = libraries.filter((l) => l.kind !== 'linked' && l.online);

  return (
    <div className="flex flex-col md:flex-row h-dvh overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 space-y-6">
          <header className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl flex items-center justify-center"
                style={{ background: 'linear-gradient(135deg, #6366f1 0%, #06b6d4 100%)' }}>
                <LibraryIcon className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>Libraries</h1>
                <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                  {isAdmin
                    ? 'Folders indexed where they are: no copies, no size limits. Everything here is searched together.'
                    : 'The libraries your administrator has shared with you. You can search them, but not change them.'}
                </p>
              </div>
            </div>
            {isAdmin && (
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => (local ? pickNative('folder') : setBrowser('folder'))}
                  disabled={busy}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-white disabled:opacity-50"
                  style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
                >
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <FolderPlus className="w-4 h-4" />}
                  Add folder
                </button>
                <button
                  onClick={() => (local ? pickNative('files') : setBrowser('files'))}
                  disabled={busy}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 hover:bg-[var(--bg-hover)]"
                  style={{ border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                  title="Index single files where they are (no copy)"
                >
                  <Link2 className="w-4 h-4" /> Add files
                </button>
                {local && (
                  <button
                    onClick={() => setBrowser('folder')}
                    className="px-3 py-2.5 rounded-xl text-sm hover:bg-[var(--bg-hover)]"
                    style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                    title="Browse folders inside the app instead of the Windows dialog"
                  >
                    Browse…
                  </button>
                )}
              </div>
            )}
          </header>

          {isAdmin && (
            <form
              onSubmit={(e) => { e.preventDefault(); if (manualPath.trim()) attach(manualPath.trim()); }}
              className="flex gap-2"
            >
              <input
                value={manualPath}
                onChange={(e) => setManualPath(e.target.value)}
                placeholder="…or paste a folder path, e.g. D:\Photos"
                className="flex-1 px-4 py-2.5 rounded-xl text-sm outline-none"
                style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                aria-label="Folder path"
              />
              <button type="submit" disabled={!manualPath.trim() || busy}
                className="px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-40 hover:bg-[var(--bg-hover)]"
                style={{ border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
                Add
              </button>
            </form>
          )}

          {isAdmin && (
            <>
              <IndexingBanner status={indexing} isAdmin={isAdmin} onTogglePause={toggleAllPaused} />
              <UploadPanel targets={uploadTargets} />
            </>
          )}

          <section className="space-y-3" aria-label="Libraries">
            {loading ? (
              <div className="flex justify-center py-16">
                <Loader2 className="w-7 h-7 animate-spin" style={{ color: 'var(--accent)' }} />
              </div>
            ) : !isAdmin && libraries.length === 0 ? (
              <div className="rounded-2xl p-8 text-center text-sm"
                style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                No data has been shared with you yet. Ask your administrator to share a library with you.
              </div>
            ) : (
              libraries.map((lib) => (
                <LibraryCard key={lib.id} lib={lib} isAdmin={isAdmin} onChanged={refresh} />
              ))
            )}
          </section>
        </div>
      </main>

      <FolderBrowserModal
        open={browser !== null}
        mode={browser || 'folder'}
        onClose={() => setBrowser(null)}
        onSelect={(paths) => {
          const mode = browser;
          setBrowser(null);
          if (mode === 'folder') attach(paths[0]);
          else addFiles(paths);
        }}
      />
    </div>
  );
}

// ── indexing banner ──────────────────────────────────────────────────────────
function IndexingBanner({ status, isAdmin, onTogglePause }: {
  status: IndexingStatus | null; isAdmin: boolean; onTogglePause: () => void;
}) {
  if (!status) return null;
  const enrichment = status.enrichmentPending ?? status.transcriptsPending;
  const busy = status.queued + status.processing > 0 || enrichment > 0 || !!status.current;
  const cur = status.current;
  const pct = cur && cur.total > 0 ? Math.round((cur.done / cur.total) * 100) : null;
  return (
    <div className="rounded-2xl p-4" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          {status.paused ? (
            <Pause className="w-5 h-5 flex-shrink-0" style={{ color: 'var(--warning)' }} />
          ) : busy ? (
            <Loader2 className="w-5 h-5 flex-shrink-0 animate-spin" style={{ color: 'var(--accent)' }} />
          ) : (
            <CheckCircle2 className="w-5 h-5 flex-shrink-0" style={{ color: 'var(--success)' }} />
          )}
          <div className="min-w-0">
            <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
              {status.paused ? 'Indexing paused' : busy ? 'Indexing' : 'Everything is indexed'}
            </p>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {status.indexed.toLocaleString()} indexed · {status.queued.toLocaleString()} waiting
              {status.transcriptsPending > 0 && ` · ${status.transcriptsPending} to transcribe`}
              {(status.captionsPending ?? 0) > 0 && ` · ${status.captionsPending} to describe`}
              {(status.soundsPending ?? 0) > 0 && ` · ${status.soundsPending} sound tracks`}
              {(status.imageVectorsPending ?? 0) > 0 && ` · ${status.imageVectorsPending} files updating image search`}
              {status.failed > 0 && <span style={{ color: 'var(--error)' }}> · {status.failed} failed</span>}
            </p>
          </div>
        </div>
        {isAdmin && (
          <button onClick={onTogglePause}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[var(--bg-hover)]"
            style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
            {status.paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
            {status.paused ? 'Resume' : 'Pause'}
          </button>
        )}
      </div>
      {cur && (
        <div className="mt-3">
          <div className="flex justify-between gap-3 text-xs mb-1.5" style={{ color: 'var(--text-secondary)' }}>
            <span className="truncate">
              {STAGE_LABEL[cur.stage] || cur.stage}: <span style={{ color: 'var(--text-primary)' }}>{cur.file}</span>
              <span style={{ color: 'var(--text-muted)' }}> · {cur.library}</span>
            </span>
            <span className="flex-shrink-0 font-mono">{pct !== null ? `${pct}%` : `${Math.round(cur.elapsed)}s`}</span>
          </div>
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--bg-active)' }}>
            <motion.div
              className="h-full rounded-full"
              style={{ background: 'linear-gradient(90deg, #6366f1, #06b6d4)' }}
              animate={{ width: pct !== null ? `${pct}%` : '35%' }}
              transition={{ duration: 0.4 }}
            />
          </div>
        </div>
      )}
      {status.lastError && (
        <p className="mt-2 text-xs truncate" style={{ color: 'var(--text-muted)' }} title={status.lastError}>
          Last problem: {status.lastError}
        </p>
      )}
    </div>
  );
}

// ── library card ─────────────────────────────────────────────────────────────
function LibraryCard({ lib, isAdmin, onChanged }: { lib: LibrarySummary; isAdmin: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [confirmDetach, setConfirmDetach] = useState(false);
  const counts = lib.counts || {};
  const indexed = counts.indexed || 0;
  const waiting = (counts.queued || 0) + (counts.processing || 0);
  const failed = counts.failed || 0;
  const builtin = lib.kind !== 'folder';

  const act = async (url: string, init: RequestInit, done?: string) => {
    try {
      await api(url, init);
      if (done) toast.success(done);
      onChanged();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Request failed');
    }
  };

  const Icon = lib.kind === 'linked' ? Link2 : lib.kind === 'uploads' ? Upload : HardDrive;

  return (
    <div className="rounded-2xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
      <div className="flex flex-wrap items-center gap-3 p-4">
        <button onClick={() => setOpen(!open)} aria-expanded={open} aria-label={open ? 'Hide files' : 'Show files'}
          className="p-1 rounded-lg hover:bg-[var(--bg-hover)]">
          {open ? <ChevronDown className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />
            : <ChevronRight className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />}
        </button>
        <Icon className="w-5 h-5 flex-shrink-0" style={{ color: lib.online ? 'var(--accent)' : 'var(--text-muted)' }} />
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold truncate" style={{ color: 'var(--text-primary)' }}>{lib.name}</span>
            {!lib.online && (
              <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: 'var(--warning-muted)', color: 'var(--warning)' }}>
                Offline
              </span>
            )}
            {lib.paused && (
              <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: 'var(--bg-active)', color: 'var(--text-secondary)' }}>
                Paused
              </span>
            )}
            {lib.scan?.state === 'running' && (
              <span className="flex items-center gap-1 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                <Loader2 className="w-3 h-3 animate-spin" /> scanning
              </span>
            )}
          </div>
          <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }} title={lib.path || ''}>
            {lib.kind === 'linked' ? 'Single files indexed where they are' : lib.path}
            {lib.error && !lib.online ? ` — ${lib.error}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs" style={{ color: 'var(--text-secondary)' }}>
          <span title="Indexed files"><b style={{ color: 'var(--text-primary)' }}>{indexed.toLocaleString()}</b> indexed</span>
          {waiting > 0 && <span title="Waiting to be indexed">{waiting.toLocaleString()} waiting</span>}
          {failed > 0 && <span style={{ color: 'var(--error)' }}>{failed} failed</span>}
          <span>{formatBytes(lib.bytes)}</span>
        </div>
        {isAdmin && lib.online && (
          <div className="flex items-center gap-1">
            {lib.kind !== 'linked' && (
              <button title={lib.watch ? 'Watching for changes (click to stop)' : 'Not watching (click to watch)'}
                onClick={() => act(`/api/libraries/${lib.id}`, jsonInit('PATCH', { watch: !lib.watch }))}
                className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)]">
                {lib.watch ? <Eye className="w-4 h-4" style={{ color: 'var(--accent)' }} />
                  : <EyeOff className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />}
              </button>
            )}
            <button title={lib.paused ? 'Resume indexing this library' : 'Pause indexing this library'}
              onClick={() => act(`/api/libraries/${lib.id}`, jsonInit('PATCH', { paused: !lib.paused }))}
              className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)]">
              {lib.paused ? <Play className="w-4 h-4" style={{ color: 'var(--accent)' }} />
                : <Pause className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />}
            </button>
            <button title="Rescan the folder now"
              onClick={() => act(`/api/libraries/${lib.id}/rescan`, { method: 'POST' }, 'Rescan started')}
              className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)]">
              <RefreshCw className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />
            </button>
            {failed > 0 && (
              <button title="Retry failed files"
                onClick={() => act(`/api/libraries/${lib.id}/retry-failed`, { method: 'POST' }, 'Failed files queued again')}
                className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)]">
                <RotateCcw className="w-4 h-4" style={{ color: 'var(--warning)' }} />
              </button>
            )}
            {!builtin && (
              <button title="Stop indexing this folder" onClick={() => setConfirmDetach(true)}
                className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)]">
                <Trash2 className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />
              </button>
            )}
          </div>
        )}
      </div>

      <AnimatePresence>
        {confirmDetach && (
          <DetachConfirm lib={lib} onCancel={() => setConfirmDetach(false)}
            onConfirm={async (deleteIndex) => {
              setConfirmDetach(false);
              await act(`/api/libraries/${lib.id}?deleteIndex=${deleteIndex}`, { method: 'DELETE' },
                `“${lib.name}” removed. Your files were not touched.`);
            }} />
        )}
      </AnimatePresence>

      {open && lib.online && <SourcesList lib={lib} isAdmin={isAdmin} onChanged={onChanged} />}
    </div>
  );
}

function DetachConfirm({ lib, onCancel, onConfirm }: {
  lib: LibrarySummary; onCancel: () => void; onConfirm: (deleteIndex: boolean) => void;
}) {
  const [deleteIndex, setDeleteIndex] = useState(false);
  return (
    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
      className="overflow-hidden">
      <div className="mx-4 mb-4 p-3 rounded-xl text-sm" style={{ background: 'var(--warning-muted)', border: '1px solid var(--border)' }}>
        <p className="flex items-center gap-2 font-medium" style={{ color: 'var(--text-primary)' }}>
          <AlertTriangle className="w-4 h-4" style={{ color: 'var(--warning)' }} />
          Stop indexing “{lib.name}”?
        </p>
        <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
          The files in {lib.path} stay exactly as they are. It disappears from search until you add the folder again.
        </p>
        <label className="flex items-center gap-2 mt-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
          <input type="checkbox" checked={deleteIndex} onChange={(e) => setDeleteIndex(e.target.checked)} />
          Also delete the hidden index (.smartfind) — re-adding the folder later re-indexes from scratch
        </label>
        <div className="flex gap-2 mt-3">
          <button onClick={() => onConfirm(deleteIndex)} className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
            style={{ background: 'var(--error)' }}>Stop indexing</button>
          <button onClick={onCancel} className="px-3 py-1.5 rounded-lg text-xs hover:bg-[var(--bg-hover)]"
            style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>Cancel</button>
        </div>
      </div>
    </motion.div>
  );
}

// ── files of one library ─────────────────────────────────────────────────────
function SourcesList({ lib, isAdmin, onChanged }: { lib: LibrarySummary; isAdmin: boolean; onChanged: () => void }) {
  const [rows, setRows] = useState<SourceRow[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const limit = 50;

  // Filter changes set `loading` in their handlers; results arrive in the fetch callback
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (status) params.set('status', status);
    if (q.trim()) params.set('q', q.trim());
    api<{ total: number; sources: SourceRow[] }>(`/api/libraries/${lib.id}/sources?${params}`)
      .then((data) => {
        if (!active) return;
        setRows(data.sources || []);
        setTotal(data.total || 0);
      })
      .catch(() => { if (active) setRows([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [lib.id, offset, status, q, reloadKey]);

  const reload = () => { setLoading(true); setReloadKey((k) => k + 1); };

  const exclude = async (relPath: string) => {
    try {
      await api(`/api/libraries/${lib.id}/exclusions`, jsonInit('POST', { pattern: relPath }));
      toast.success('Removed from the library. The file itself was not touched.');
      reload();
      onChanged();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Request failed');
    }
  };

  const statusIcon = (s: string) => {
    if (s === 'indexed') return <CheckCircle2 className="w-3.5 h-3.5" style={{ color: 'var(--success)' }} />;
    if (s === 'failed') return <XCircle className="w-3.5 h-3.5" style={{ color: 'var(--error)' }} />;
    if (s === 'processing') return <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: 'var(--accent)' }} />;
    return <FolderOpen className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />;
  };

  return (
    <div className="px-4 pb-4" style={{ borderTop: '1px solid var(--border-subtle)' }}>
      <div className="flex flex-wrap gap-2 pt-3">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
          <input value={q} onChange={(e) => { setLoading(true); setQ(e.target.value); setOffset(0); }} placeholder="Filter by name or folder"
            className="w-full pl-8 pr-3 py-1.5 rounded-lg text-xs outline-none"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }} />
        </div>
        <select value={status} onChange={(e) => { setLoading(true); setStatus(e.target.value); setOffset(0); }}
          className="px-2.5 py-1.5 rounded-lg text-xs outline-none" aria-label="Filter by status"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
          <option value="">All files</option>
          <option value="indexed">Indexed</option>
          <option value="queued">Waiting</option>
          <option value="processing">Indexing now</option>
          <option value="failed">Failed</option>
        </select>
      </div>
      <div className="mt-2 space-y-1">
        {loading ? (
          <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin" style={{ color: 'var(--accent)' }} /></div>
        ) : rows.length === 0 ? (
          <p className="text-xs py-4 text-center" style={{ color: 'var(--text-muted)' }}>No files match.</p>
        ) : rows.map((r) => (
          <div key={r.id} className="group flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs hover:bg-[var(--bg-hover)]">
            {statusIcon(r.status)}
            <span className="flex-1 truncate" style={{ color: 'var(--text-primary)' }} title={r.relPath}>{r.relPath}</span>
            {r.status === 'failed' && r.error_message && (
              <span className="max-w-[40%] truncate" style={{ color: 'var(--error)' }} title={r.error_message}>{r.error_message}</span>
            )}
            <span style={{ color: 'var(--text-muted)' }}>{formatBytes(r.file_size)}</span>
            {isAdmin && lib.kind !== 'linked' && (
              <button onClick={() => exclude(r.relPath)} title="Remove from library (keeps the file)"
                className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[var(--bg-active)]">
                <X className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
              </button>
            )}
          </div>
        ))}
      </div>
      {total > limit && (
        <div className="flex items-center justify-between mt-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
          <span>{offset + 1}–{Math.min(offset + limit, total)} of {total.toLocaleString()}</span>
          <div className="flex gap-2">
            <button disabled={offset === 0} onClick={() => { setLoading(true); setOffset(Math.max(0, offset - limit)); }}
              className="px-2 py-1 rounded disabled:opacity-40 hover:bg-[var(--bg-hover)]">Previous</button>
            <button disabled={offset + limit >= total} onClick={() => { setLoading(true); setOffset(offset + limit); }}
              className="px-2 py-1 rounded disabled:opacity-40 hover:bg-[var(--bg-hover)]">Next</button>
          </div>
        </div>
      )}
    </div>
  );
}
