'use client';
// src/components/ai/KeyEventsViewer.tsx
// Structured Key Events with significance badges and source citations

import { Flag, ExternalLink, Sparkles, CheckCircle2 } from 'lucide-react';

interface KeyEventItem {
  id: string;
  title: string;
  description: string;
  significance: string;
  sourceId?: string;
  sourceName?: string;
  dateOrPhase?: string;
}

interface Props {
  events: KeyEventItem[];
  onOpenSource?: (sourceId: string) => void;
}

export default function KeyEventsViewer({ events, onOpenSource }: Props) {
  return (
    <div
      className="p-5 rounded-3xl space-y-4 shadow-xl"
      style={{
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border)',
        boxShadow: '0 12px 36px rgba(0,0,0,0.25)',
      }}
    >
      {/* Header */}
      <div className="flex items-center gap-2.5 pb-3 border-b border-[var(--border)]">
        <div className="w-8 h-8 rounded-xl flex items-center justify-center"
          style={{ background: 'rgba(244, 63, 94, 0.15)', color: '#f43f5e' }}>
          <Flag className="w-4 h-4" />
        </div>
        <div>
          <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
            Extracted Key Events & Milestones
          </h3>
          <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
            {events.length} critical occurrences and structural developments identified
          </p>
        </div>
      </div>

      {/* Events Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        {events.map((ev, index) => (
          <div
            key={ev.id || index}
            className="p-4 rounded-2xl flex flex-col justify-between gap-2.5 transition-all hover:border-zinc-500/30"
            style={{
              background: 'var(--bg-base)',
              border: '1px solid var(--border)',
            }}
          >
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                {ev.dateOrPhase && (
                  <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-rose-500/10 text-rose-400 border border-rose-500/20">
                    {ev.dateOrPhase}
                  </span>
                )}
                {ev.sourceId && (
                  <button
                    type="button"
                    onClick={() => onOpenSource?.(ev.sourceId!)}
                    className="flex items-center gap-1 text-[10px] text-cyan-400 hover:text-cyan-300 transition-colors"
                  >
                    <span>{ev.sourceName || 'Source Citation'}</span>
                    <ExternalLink className="w-2.5 h-2.5" />
                  </button>
                )}
              </div>
              <h4 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
                {ev.title}
              </h4>
              <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                {ev.description}
              </p>
            </div>

            {ev.significance && (
              <div className="pt-2 border-t border-[var(--border)] text-[11px] text-rose-300/90 leading-relaxed">
                <span className="font-semibold text-rose-400">Impact: </span>
                {ev.significance}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
