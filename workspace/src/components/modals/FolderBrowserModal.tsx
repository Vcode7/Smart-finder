'use client';
// src/components/modals/FolderBrowserModal.tsx — browse folders on the PC running Smart Finder.
// Works from any device: the listing comes from the backend (/api/system/fs), not the browser.

import { useCallback, useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ChevronRight, File as FileIcon, Folder, HardDrive, Home, Loader2, Star, X, ArrowUp, Check,
} from 'lucide-react';
import { apiErrorMessage, readJson } from '@/lib/utils/api';

interface FsEntry {
  name: string;
  path: string;
  type: 'drive' | 'shortcut' | 'dir' | 'file';
  size?: number;
  supported?: boolean;
}

interface FsListing {
  path: string | null;
  parent: string | null;
  entries: FsEntry[];
  truncated: boolean;
  libraryId: string | null;
}

interface Props {
  open: boolean;
  mode: 'folder' | 'files';
  title?: string;
  onClose: () => void;
  onSelect: (paths: string[]) => void;
}

function formatBytes(bytes = 0): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
}

function crumbs(path: string): Array<{ label: string; path: string }> {
  const sep = path.includes('\\') ? '\\' : '/';
  const parts = path.split(/[\\/]/).filter(Boolean);
  const out: Array<{ label: string; path: string }> = [];
  let acc = path.startsWith('/') ? '/' : '';
  parts.forEach((part, i) => {
    acc = i === 0 && /^[A-Za-z]:$/.test(part) ? `${part}${sep}` : `${acc}${acc.endsWith(sep) ? '' : sep}${part}`;
    out.push({ label: part, path: acc });
  });
  return out;
}

// "This PC" when the server is Windows (drive letters or backslashes), "Computer" otherwise
function rootLabel(listing: FsListing | null): string {
  if (!listing) return 'This PC';
  const sample = listing.path ?? listing.entries[0]?.path ?? '';
  return /^[A-Za-z]:|\\/.test(sample) ? 'This PC' : 'Computer';
}

async function fetchListing(path: string | null, mode: Props['mode']): Promise<FsListing> {
  const params = new URLSearchParams();
  if (path) params.set('path', path);
  if (mode === 'files') params.set('files', 'true');
  const res = await fetch(`/api/system/fs?${params}`);
  const data = await readJson<FsListing>(res);
  if (!res.ok || !data) throw new Error(apiErrorMessage(data, 'Could not open this folder'));
  return data;
}

export function FolderBrowserModal(props: Props) {
  // The dialog mounts fresh on every open, so its selection and location start clean
  return <AnimatePresence>{props.open && <BrowserDialog {...props} />}</AnimatePresence>;
}

function BrowserDialog({ mode, title, onClose, onSelect }: Props) {
  const [listing, setListing] = useState<FsListing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const show = useCallback((p: Promise<FsListing>) => {
    p.then((data) => { setListing(data); setError(null); })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not open this folder'))
      .finally(() => setLoading(false));
  }, []);

  const load = (path: string | null) => {
    setLoading(true);
    show(fetchListing(path, mode));
  };

  useEffect(() => {
    show(fetchListing(null, mode));
  }, [mode, show]);

  const toggleFile = (path: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  };

  const confirm = () => {
    if (mode === 'folder' && listing?.path) onSelect([listing.path]);
    if (mode === 'files' && selected.size) onSelect(Array.from(selected));
  };

  const iconFor = (e: FsEntry) => {
    if (e.type === 'drive') return <HardDrive className="w-4 h-4" style={{ color: 'var(--accent-cyan)' }} />;
    if (e.type === 'shortcut') return e.name === 'Home'
      ? <Home className="w-4 h-4" style={{ color: 'var(--accent-amber)' }} />
      : <Star className="w-4 h-4" style={{ color: 'var(--accent-amber)' }} />;
    if (e.type === 'dir') return <Folder className="w-4 h-4" style={{ color: 'var(--accent)' }} />;
    return <FileIcon className="w-4 h-4" style={{ color: e.supported ? 'var(--text-secondary)' : 'var(--text-muted)' }} />;
  };

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.55)' }}
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        role="dialog" aria-modal="true" aria-label={title || 'Browse folders'}
        className="w-full max-w-2xl rounded-2xl flex flex-col overflow-hidden"
        style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', maxHeight: '80vh', boxShadow: 'var(--shadow-lg)' }}
        initial={{ scale: 0.97, y: 8 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.97, y: 8 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--border)' }}>
          <div>
            <h2 className="font-semibold" style={{ color: 'var(--text-primary)' }}>
              {title || (mode === 'folder' ? 'Choose a folder' : 'Choose files')}
            </h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
              Folders on the computer running Smart Finder. Files are indexed where they are, never copied.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)]">
            <X className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />
          </button>
        </div>

        {/* Location bar */}
        <div className="flex items-center gap-1 px-5 py-2.5 text-xs overflow-x-auto whitespace-nowrap"
          style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-secondary)' }}>
          <button onClick={() => load(null)} className="px-1.5 py-0.5 rounded hover:bg-[var(--bg-hover)]">{rootLabel(listing)}</button>
          {listing?.path && crumbs(listing.path).map((c) => (
            <span key={c.path} className="flex items-center gap-1">
              <ChevronRight className="w-3 h-3" style={{ color: 'var(--text-muted)' }} />
              <button onClick={() => load(c.path)} className="px-1.5 py-0.5 rounded hover:bg-[var(--bg-hover)]">{c.label}</button>
            </span>
          ))}
          {listing?.parent && (
            <button onClick={() => load(listing.parent)} className="ml-auto flex items-center gap-1 px-2 py-0.5 rounded hover:bg-[var(--bg-hover)]"
              aria-label="Up one folder">
              <ArrowUp className="w-3 h-3" /> Up
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2 min-h-[280px]">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-6 h-6 animate-spin" style={{ color: 'var(--accent)' }} />
            </div>
          ) : error ? (
            <p className="text-sm px-3 py-6 text-center" style={{ color: 'var(--error)' }}>{error}</p>
          ) : listing && listing.entries.length === 0 ? (
            <p className="text-sm px-3 py-6 text-center" style={{ color: 'var(--text-muted)' }}>This folder is empty.</p>
          ) : (
            listing?.entries.map((e) => {
              const isFile = e.type === 'file';
              const isSelected = selected.has(e.path);
              return (
                <button
                  key={e.path}
                  onClick={() => (isFile ? (e.supported && toggleFile(e.path)) : load(e.path))}
                  disabled={isFile && !e.supported}
                  className="w-full flex items-center gap-3 px-3 py-2 rounded-xl text-left text-sm transition-colors hover:bg-[var(--bg-hover)] disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{
                    color: 'var(--text-primary)',
                    background: isSelected ? 'var(--accent-muted)' : undefined,
                  }}
                >
                  {iconFor(e)}
                  <span className="flex-1 truncate">{e.name}</span>
                  {isFile && <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{formatBytes(e.size)}</span>}
                  {isSelected && <Check className="w-4 h-4" style={{ color: 'var(--accent)' }} />}
                  {!isFile && <ChevronRight className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />}
                </button>
              );
            })
          )}
          {listing?.truncated && (
            <p className="text-xs px-3 py-2" style={{ color: 'var(--text-muted)' }}>
              Showing the first 5,000 entries of this folder.
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 px-5 py-3.5" style={{ borderTop: '1px solid var(--border)' }}>
          <span className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
            {mode === 'folder'
              ? (listing?.path ? listing.path : 'Open the folder you want to index')
              : `${selected.size} file${selected.size === 1 ? '' : 's'} selected`}
          </span>
          <div className="flex gap-2 flex-shrink-0">
            <button onClick={onClose} className="px-4 py-2 rounded-xl text-sm hover:bg-[var(--bg-hover)]"
              style={{ color: 'var(--text-secondary)', border: '1px solid var(--border)' }}>
              Cancel
            </button>
            <button
              onClick={confirm}
              disabled={mode === 'folder' ? !listing?.path : selected.size === 0}
              className="px-4 py-2 rounded-xl text-sm font-semibold text-white disabled:opacity-40"
              style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
            >
              {mode === 'folder' ? 'Use this folder' : 'Add files'}
            </button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
