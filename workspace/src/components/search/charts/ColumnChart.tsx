'use client';
// Vertical bars over an ordered axis (dates, relevance bins). Scrolls sideways when there are
// many bars; clicking a bar filters the dashboard to it.

import type { Bucket } from '@/lib/search/charts';

interface Props {
  buckets: Bucket[];
  activeKey: string | null;
  onSelect: (key: string | null) => void;
  height?: number;
  noun?: string;
}

export default function ColumnChart({ buckets, activeKey, onSelect, height = 140, noun = 'files' }: Props) {
  if (buckets.length === 0) {
    return <p className="text-xs py-6 text-center" style={{ color: 'var(--text-muted)' }}>Nothing to show for the current filters.</p>;
  }
  const max = Math.max(...buckets.map((b) => b.count), 1);
  const step = Math.max(1, Math.ceil(buckets.length / 8));      // label every n-th bar

  return (
    <div className="flex gap-2">
      <div className="flex flex-col justify-between text-[10px] font-mono tabular-nums pt-6" style={{ color: 'var(--text-muted)', height: height + 48 }} aria-hidden>
        <span>{max}</span>
        <span style={{ paddingBottom: 20 }}>0</span>
      </div>
      <div className="overflow-x-auto flex-1 min-w-0 pt-6">
        <div className="flex items-end gap-[2px] border-b" style={{ height, minWidth: buckets.length * 16, borderColor: 'var(--viz-grid)' }}>
          {buckets.map((b) => {
            const active = activeKey === b.key;
            const dim = activeKey !== null && !active;
            return (
              <button
                key={b.key}
                type="button"
                aria-pressed={active}
                aria-label={`${b.hint ?? b.label}: ${b.count} ${noun}`}
                onClick={() => onSelect(active ? null : b.key)}
                disabled={b.count === 0}
                className="group relative flex-1 min-w-[14px] max-w-[48px] h-full flex items-end justify-center focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)] disabled:cursor-default"
              >
                <span
                  className="w-full rounded-t-[4px] transition-all group-hover:brightness-110"
                  style={{ height: b.count ? `${Math.max(3, (b.count / max) * 100)}%` : 0, background: 'var(--viz-1)', opacity: dim ? 0.35 : 1 }}
                />
                {b.count > 0 && (
                  <span
                    role="tooltip"
                    className="pointer-events-none absolute bottom-full mb-1 z-10 hidden group-hover:block group-focus-visible:block px-2 py-1 rounded-md text-[11px] whitespace-nowrap shadow-md"
                    style={{ background: 'var(--bg-active)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}
                  >
                    {b.hint ?? b.label} · {b.count} {noun}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <div className="flex gap-[2px] pt-1" style={{ minWidth: buckets.length * 16 }} aria-hidden>
          {buckets.map((b, i) => (
            <span key={b.key} className="flex-1 min-w-[14px] max-w-[48px] text-[10px] text-center whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>
              {i % step === 0 ? b.label : ''}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
