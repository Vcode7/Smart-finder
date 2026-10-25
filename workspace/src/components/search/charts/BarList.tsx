'use client';
// Horizontal bars for a categorical breakdown (file types, folders, libraries, topics).
// Each row is a button: clicking it filters the dashboard to that value.

import { useState } from 'react';
import type { Bucket } from '@/lib/search/charts';

interface Props {
  buckets: Bucket[];
  total: number;                          // files the percentages in the tooltip are of
  activeKey?: string | null;
  onSelect?: (key: string | null) => void;     // without it the bars are a plain, unclickable breakdown
  colorOf?: (key: string) => string;
  limit?: number;
  noun?: string;
}

export default function BarList({ buckets, total, activeKey = null, onSelect, colorOf, limit = 8, noun = 'files' }: Props) {
  const [all, setAll] = useState(false);
  if (buckets.length === 0) {
    return <p className="text-xs py-6 text-center" style={{ color: 'var(--text-muted)' }}>Nothing to show for the current filters.</p>;
  }
  const max = Math.max(...buckets.map((b) => b.count), 1);
  let shown = all ? buckets : buckets.slice(0, limit);
  // A selected value that fell below the cut stays visible so it can be cleared
  if (activeKey && !shown.some((b) => b.key === activeKey)) {
    const active = buckets.find((b) => b.key === activeKey);
    if (active) shown = [...shown, active];
  }

  return (
    <div className="space-y-1">
      {shown.map((b) => {
        const active = activeKey === b.key;
        const dim = activeKey !== null && !active;
        const pct = total ? Math.round((b.count / total) * 100) : 0;
        const Row = (onSelect ? 'button' : 'div') as 'button';
        return (
          <Row
            key={b.key}
            {...(onSelect ? { type: 'button' as const, 'aria-pressed': active, onClick: () => onSelect(active ? null : b.key) } : {})}
            className="group relative w-full grid grid-cols-[minmax(0,9rem)_1fr_auto] sm:grid-cols-[minmax(0,12rem)_1fr_auto] items-center gap-2 px-1.5 py-1 rounded-lg text-left transition-colors hover:bg-[var(--bg-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
            style={{ background: active ? 'var(--accent-muted)' : undefined }}
          >
            <span className="text-xs truncate" style={{ color: 'var(--text-secondary)' }} title={b.label}>{b.label}</span>
            <span className="relative h-2.5 rounded-r-[4px]" style={{ background: 'var(--viz-grid)' }}>
              <span
                className="absolute inset-y-0 left-0 rounded-r-[4px] transition-all"
                style={{ width: `${Math.max(2, (b.count / max) * 100)}%`, background: colorOf?.(b.key) ?? 'var(--viz-1)', opacity: dim ? 0.35 : 1 }}
              />
            </span>
            <span className="text-xs font-mono tabular-nums text-right min-w-[2ch]" style={{ color: 'var(--text-primary)' }}>{b.count}</span>
            <span
              role="tooltip"
              className="pointer-events-none absolute right-0 -top-7 z-10 hidden group-hover:block group-focus-visible:block px-2 py-1 rounded-md text-[11px] whitespace-nowrap shadow-md"
              style={{ background: 'var(--bg-active)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}
            >
              {b.label} · {b.count} {noun} · {pct}%
            </span>
          </Row>
        );
      })}
      {buckets.length > limit && (
        <button type="button" onClick={() => setAll((v) => !v)} className="text-[11px] font-semibold px-1.5 pt-1" style={{ color: 'var(--accent)' }}>
          {all ? 'Show fewer' : `Show all ${buckets.length}`}
        </button>
      )}
    </div>
  );
}
