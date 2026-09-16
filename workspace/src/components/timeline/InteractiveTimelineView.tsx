'use client';
// src/components/timeline/InteractiveTimelineView.tsx
// Interactive Chronological Timeline Component with event filtering, date markers, and source provenance links

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Calendar, Search, ExternalLink, Sparkles, Filter, ChevronRight, CheckCircle2, Clock } from 'lucide-react';
import type { TimelineEvent } from '@/types/research';

interface Props {
  events: TimelineEvent[];
  onOpenSource?: (sourceId: string, timestamp?: number) => void;
}

export default function InteractiveTimelineView({ events, onOpenSource }: Props) {
  const [filterText, setFilterText] = useState('');
  const [importanceFilter, setImportanceFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all');
  const [selectedEventId, setSelectedEventId] = useState<string | null>(events[0]?.id || null);

  const filteredEvents = events.filter((ev) => {
    const matchesText =
      (ev.title || '').toLowerCase().includes(filterText.toLowerCase()) ||
      (ev.description || '').toLowerCase().includes(filterText.toLowerCase()) ||
      (ev.date || '').toLowerCase().includes(filterText.toLowerCase());

    const matchesImportance = importanceFilter === 'all' || ev.importance === importanceFilter;
    return matchesText && matchesImportance;
  });

  const getImportanceBadge = (importance: string) => {
    switch (importance) {
      case 'high':
        return { label: 'Critical Milestone', color: '#f43f5e', bg: 'rgba(244, 63, 94, 0.15)', border: 'rgba(244, 63, 94, 0.3)' };
      case 'medium':
        return { label: 'Key Development', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)', border: 'rgba(245, 158, 11, 0.3)' };
      default:
        return { label: 'Context Event', color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.15)', border: 'rgba(6, 182, 212, 0.3)' };
    }
  };

  return (
    <div
      className="p-5 rounded-3xl space-y-5 shadow-xl transition-all"
      style={{
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border)',
        boxShadow: '0 12px 36px rgba(0,0,0,0.25)',
      }}
    >
      {/* Header & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center"
            style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981' }}>
            <Calendar className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              Interactive Chronological Timeline
            </h3>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              {filteredEvents.length} events identified across verified source context
            </p>
          </div>
        </div>

        {/* Filter Toolbar */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Search Input */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              type="text"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              placeholder="Filter timeline..."
              className="pl-8 pr-3 py-1 text-xs rounded-xl bg-[var(--bg-base)] border border-[var(--border)] outline-none text-zinc-200 placeholder:text-zinc-500 w-36 focus:w-48 transition-all"
            />
          </div>

          {/* Importance Filter */}
          <div className="flex items-center gap-1 p-0.5 rounded-xl bg-[var(--bg-base)] border border-[var(--border)]">
            {(['all', 'high', 'medium'] as const).map((imp) => (
              <button
                key={imp}
                onClick={() => setImportanceFilter(imp)}
                className={`px-2 py-0.5 rounded-lg text-[10px] font-bold capitalize transition-all ${
                  importanceFilter === imp ? 'bg-emerald-500/20 text-emerald-400' : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                {imp}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Timeline Stream */}
      {filteredEvents.length === 0 ? (
        <div className="py-8 text-center text-xs text-zinc-400">
          No events match your filter criteria.
        </div>
      ) : (
        <div className="relative pl-6 sm:pl-8 space-y-6 before:absolute before:left-3 sm:before:left-4 before:top-2 before:bottom-2 before:w-0.5 before:bg-gradient-to-b before:from-emerald-500 before:via-cyan-500 before:to-indigo-500">
          {filteredEvents.map((ev, index) => {
            const isSelected = selectedEventId === ev.id;
            const badge = getImportanceBadge(ev.importance);

            return (
              <motion.div
                key={ev.id || index}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.05 }}
                onClick={() => setSelectedEventId(ev.id)}
                className="relative group cursor-pointer"
              >
                {/* Timeline Dot Marker */}
                <div
                  className={`absolute -left-6 sm:-left-8 top-1.5 w-3.5 h-3.5 rounded-full border-2 transition-transform ${
                    isSelected ? 'scale-125 ring-4 ring-emerald-500/20' : 'group-hover:scale-110'
                  }`}
                  style={{
                    background: isSelected ? '#10b981' : 'var(--bg-elevated)',
                    borderColor: badge.color,
                  }}
                />

                {/* Event Card */}
                <div
                  className={`p-4 rounded-2xl transition-all ${
                    isSelected ? 'border-emerald-500/50 shadow-md' : 'hover:border-zinc-500/30'
                  }`}
                  style={{
                    background: isSelected ? 'var(--bg-base)' : 'rgba(255,255,255,0.02)',
                    border: '1px solid var(--border)',
                  }}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-emerald-400 px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">
                        {ev.date || 'Timeline Milestone'}
                      </span>
                      <span
                        className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                        style={{ background: badge.bg, color: badge.color, border: `1px solid ${badge.border}` }}
                      >
                        {badge.label}
                      </span>
                    </div>

                    {/* Source Citations */}
                    {ev.sourceIds && ev.sourceIds.length > 0 && (
                      <div className="flex items-center gap-1">
                        {ev.sourceIds.map((sid, sIdx) => (
                          <button
                            key={sIdx}
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenSource?.(sid);
                            }}
                            className="flex items-center gap-1 text-[10px] font-semibold text-cyan-400 hover:text-cyan-300 px-2 py-0.5 rounded-md bg-cyan-500/10 hover:bg-cyan-500/20 transition-colors"
                          >
                            <span>Source #{sIdx + 1}</span>
                            <ExternalLink className="w-2.5 h-2.5" />
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <h4 className="text-sm font-bold mb-1" style={{ color: 'var(--text-primary)' }}>
                    {ev.title}
                  </h4>
                  <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                    {ev.description}
                  </p>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
