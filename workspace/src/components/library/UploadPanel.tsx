'use client';
// src/components/library/UploadPanel.tsx — drag-and-drop / folder uploads through the chunked uploader

import { useEffect, useMemo, useRef, useState } from 'react';
import { FileUp, FolderUp, Pause, Play, Upload, X } from 'lucide-react';
import { toast } from 'sonner';
import { filesFromDataTransfer, getUploader, type UploadItem } from '@/lib/upload/chunked-uploader';

export interface UploadTarget {
  id: string;
  name: string;
}

function formatBytes(bytes = 0): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const v = bytes / 1024 ** i;
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatEta(remaining: number, speed: number): string {
  if (!speed || speed < 1) return '';
  const s = Math.round(remaining / speed);
  if (s < 60) return `${s}s left`;
  if (s < 3600) return `${Math.round(s / 60)} min left`;
  return `${(s / 3600).toFixed(1)} h left`;
}

export function UploadPanel({ targets = [] }: { targets?: UploadTarget[] }) {
  const uploader = useMemo(() => getUploader(), []);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [target, setTarget] = useState<string>('uploads');
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  useEffect(() => uploader.subscribe(setItems), [uploader]);

  useEffect(() => {
    if (folderInput.current) folderInput.current.setAttribute('webkitdirectory', '');
  }, []);

  const queue = (files: Array<{ file: File; relativePath?: string }>) => {
    if (!files.length) return;
    uploader.add(files, target === 'uploads' ? undefined : target);
    toast.info(`${files.length} file${files.length === 1 ? '' : 's'} queued for upload`);
  };

  const onInput = (e: React.ChangeEvent<HTMLInputElement>, keepPaths: boolean) => {
    const list = Array.from(e.target.files || []);
    queue(list.map((file) => ({
      file,
      relativePath: keepPaths && file.webkitRelativePath ? file.webkitRelativePath : undefined,
    })));
    e.target.value = '';
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    filesFromDataTransfer(e.dataTransfer).then(queue).catch(() => toast.error('Could not read the dropped items'));
  };

  const totals = items.reduce((acc, i) => {
    if (['uploading', 'checking', 'finishing', 'waiting', 'paused'].includes(i.state)) {
      acc.sent += i.sent; acc.total += i.total; acc.speed += i.speed;
    }
    return acc;
  }, { sent: 0, total: 0, speed: 0 });

  return (
    <section className="rounded-2xl p-4 space-y-3" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
      aria-label="Upload files">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Upload from this device</h2>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            Any size and any number of files; interrupted uploads resume when you select the same files again.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
          Save to
          <select value={target} onChange={(e) => setTarget(e.target.value)}
            className="px-2.5 py-1.5 rounded-lg text-xs outline-none"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
            {targets.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            {targets.length === 0 && <option value="uploads">Uploads</option>}
          </select>
        </label>
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className="rounded-xl p-6 text-center transition-colors"
        style={{
          border: `1.5px dashed ${dragOver ? 'var(--accent)' : 'var(--border-hover)'}`,
          background: dragOver ? 'var(--accent-muted)' : 'transparent',
        }}
      >
        <Upload className="w-6 h-6 mx-auto mb-2" style={{ color: 'var(--accent)' }} />
        <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>Drop files or folders here</p>
        <div className="mt-3 flex justify-center gap-2">
          <button onClick={() => fileInput.current?.click()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[var(--bg-hover)]"
            style={{ border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
            <FileUp className="w-3.5 h-3.5" /> Choose files
          </button>
          <button onClick={() => folderInput.current?.click()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[var(--bg-hover)]"
            style={{ border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
            <FolderUp className="w-3.5 h-3.5" /> Choose a folder
          </button>
        </div>
        <input ref={fileInput} type="file" multiple hidden onChange={(e) => onInput(e, false)} />
        <input ref={folderInput} type="file" multiple hidden onChange={(e) => onInput(e, true)} />
      </div>

      {items.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs" style={{ color: 'var(--text-secondary)' }}>
            <span>
              {totals.total > 0
                ? `${formatBytes(totals.sent)} of ${formatBytes(totals.total)} · ${formatBytes(totals.speed)}/s ${formatEta(totals.total - totals.sent, totals.speed)}`
                : 'Uploads finished'}
            </span>
            <button onClick={() => uploader.clearFinished()} className="hover:underline">Clear finished</button>
          </div>
          <div className="max-h-72 overflow-y-auto space-y-1.5 pr-1">
            {items.map((item) => <UploadRow key={item.id} item={item} />)}
          </div>
        </div>
      )}
    </section>
  );
}

function UploadRow({ item }: { item: UploadItem }) {
  const uploader = getUploader();
  const pct = item.total ? Math.round((item.sent / item.total) * 100) : 100;
  const label: Record<string, string> = {
    waiting: 'Waiting', checking: 'Checking', uploading: `${pct}%`, paused: 'Paused', finishing: 'Finishing',
    done: 'Uploaded — indexing', exists: 'Already in your library', error: 'Failed', cancelled: 'Cancelled',
  };
  const color = item.state === 'error' ? 'var(--error)'
    : item.state === 'done' || item.state === 'exists' ? 'var(--success)' : 'var(--text-secondary)';
  return (
    <div className="px-3 py-2 rounded-xl" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}>
      <div className="flex items-center gap-2 text-xs">
        <span className="flex-1 truncate" style={{ color: 'var(--text-primary)' }} title={item.relativePath || item.file.name}>
          {item.relativePath || item.file.name}
        </span>
        <span className="flex-shrink-0" style={{ color: 'var(--text-muted)' }}>{formatBytes(item.total)}</span>
        <span className="flex-shrink-0 w-36 text-right truncate" style={{ color }} title={item.error}>
          {item.state === 'error' ? item.error || label.error : label[item.state]}
        </span>
        {(item.state === 'uploading' || item.state === 'waiting') && (
          <button onClick={() => uploader.pause(item.id)} aria-label="Pause upload" className="p-1 rounded hover:bg-[var(--bg-hover)]">
            <Pause className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
          </button>
        )}
        {(item.state === 'paused' || item.state === 'error') && (
          <button onClick={() => uploader.resume(item.id)} aria-label="Resume upload" className="p-1 rounded hover:bg-[var(--bg-hover)]">
            <Play className="w-3.5 h-3.5" style={{ color: 'var(--accent)' }} />
          </button>
        )}
        {!['done', 'exists', 'cancelled'].includes(item.state) && (
          <button onClick={() => uploader.cancel(item.id)} aria-label="Cancel upload" className="p-1 rounded hover:bg-[var(--bg-hover)]">
            <X className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
          </button>
        )}
      </div>
      {['uploading', 'paused', 'checking', 'finishing'].includes(item.state) && (
        <div className="mt-1.5 h-1 rounded-full overflow-hidden" style={{ background: 'var(--bg-active)' }}>
          <div className="h-full rounded-full transition-all"
            style={{ width: `${pct}%`, background: item.state === 'paused' ? 'var(--warning)' : 'var(--accent)' }} />
        </div>
      )}
    </div>
  );
}
