'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useResearchStore } from '@/store/research';
import { useUIStore } from '@/store/ui';
import { toast } from 'sonner';
import { GitBranch, Zap, RefreshCw, ExternalLink, Calendar, Sparkles, ChevronRight } from 'lucide-react';
import { formatDate } from '@/lib/utils/date';
import type { ResearchSession, TimelineEvent } from '@/types/research';

interface ResearchTimelineProps {
  session: ResearchSession;
  sessionId: string;
}

export function ResearchTimeline({ session, sessionId }: ResearchTimelineProps) {
  const { setTimeline } = useResearchStore();
  const { aiSelectedSourceIds } = useUIStore();
  const [loading, setLoading] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent | null>(null);
  const events = session.timeline || [];

  const generate = async () => {
    if (session.sources.length === 0) {
      toast.error('No sources available');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch('/api/timeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: session.topic,
          sources: session.sources,
          selectedSourceIds: aiSelectedSourceIds,
        }),
      });
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.message || 'Timeline generation failed');
      }
      const data = await res.json();
      setTimeline(sessionId, data.events);
      toast.success('Research timeline generated!');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to generate timeline';
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const importanceBadge = {
    high: { label: 'Major Milestone', color: '#f43f5e', bg: 'rgba(244, 63, 94, 0.15)' },
    medium: { label: 'Key Development', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)' },
    low: { label: 'Reference', color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.15)' },
  };

  if (events.length === 0) {
    return (
      <div
        className="rounded-3xl p-8 sm:p-12 text-center border shadow-xl relative overflow-hidden"
        style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
      >
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5 shadow-lg shadow-emerald-500/25" style={{ background: 'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)' }}>
          <GitBranch className="w-8 h-8 text-white" />
        </div>

        <h3 className="text-xl sm:text-2xl font-extrabold mb-2" style={{ color: 'var(--text-primary)' }}>
          Chronological Research Timeline
        </h3>

        <p className="text-xs sm:text-sm max-w-xl mx-auto mb-8 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Order historical events, policy declarations, technological breakthroughs, and developments with source citations.
        </p>

        <button
          onClick={generate}
          disabled={loading}
          className="inline-flex items-center gap-2.5 px-6 py-3 rounded-2xl font-bold text-sm text-white shadow-lg shadow-emerald-500/25 transition-all hover:scale-105 disabled:opacity-50"
          style={{ background: 'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)' }}
        >
          {loading ? (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Constructing Timeline...</span>
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4" />
              <span>Generate Interactive Timeline</span>
            </>
          )}
        </button>
      </div>
    );
  }

  const sorted = [...events].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());

  return (
    <div className="rounded-2xl overflow-hidden border shadow-xl" style={{ borderColor: 'var(--border)', background: 'var(--bg-elevated)' }}>
      {/* Timeline Header */}
      <div
        className="flex items-center justify-between px-5 py-3.5 border-b"
        style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}
      >
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center bg-emerald-500/15 text-emerald-400">
            <GitBranch className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              Chronological Research Timeline
            </h3>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              {events.length} chronological milestones detected across research corpus
            </p>
          </div>
        </div>

        <button
          onClick={generate}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all hover:bg-[var(--bg-hover)]"
          style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', background: 'var(--bg-base)' }}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span className="hidden sm:inline">Regenerate</span>
        </button>
      </div>

      {/* Modern Vertical Timeline */}
      <div className="p-6 max-w-4xl mx-auto">
        <div className="relative border-l-2 ml-4 pl-6 space-y-8" style={{ borderColor: 'var(--border)' }}>
          {sorted.map((event, i) => {
            const badge = importanceBadge[event.importance] || importanceBadge.low;
            const isSelected = selectedEvent?.id === event.id;
            const relatedSources = event.sourceIds
              .map((id) => session.sources.find((s) => s.id === id))
              .filter(Boolean);

            return (
              <motion.div
                key={event.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className="relative group"
              >
                {/* Glowing Node Dot */}
                <div
                  className="absolute -left-[31px] top-1.5 w-4 h-4 rounded-full border-2 transition-transform duration-200 group-hover:scale-125 shadow-md"
                  style={{
                    background: badge.color,
                    borderColor: 'var(--bg-elevated)',
                    boxShadow: `0 0 12px ${badge.color}80`,
                  }}
                />

                {/* Event Card */}
                <div
                  onClick={() => setSelectedEvent(isSelected ? null : event)}
                  className={`p-4 rounded-2xl border transition-all duration-200 cursor-pointer shadow-sm ${
                    isSelected ? 'ring-2 ring-indigo-500 shadow-indigo-500/20' : 'hover:border-indigo-500/30'
                  }`}
                  style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
                >
                  <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                    <div className="flex items-center gap-2">
                      <span
                        className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full"
                        style={{ background: badge.bg, color: badge.color }}
                      >
                        {badge.label}
                      </span>
                      <span className="text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>
                        {formatDate(event.date)}
                      </span>
                    </div>

                    {relatedSources.length > 0 && (
                      <span className="text-[10px] font-medium text-indigo-400">
                        {relatedSources.length} cited {relatedSources.length === 1 ? 'source' : 'sources'}
                      </span>
                    )}
                  </div>

                  <h4 className="text-sm font-bold mb-1.5" style={{ color: 'var(--text-primary)' }}>
                    {event.title}
                  </h4>

                  <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                    {event.description}
                  </p>

                  {/* Expandable Citations */}
                  <AnimatePresence>
                    {isSelected && relatedSources.length > 0 && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="mt-3 pt-3 border-t space-y-1.5"
                        style={{ borderColor: 'var(--border)' }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <p className="text-[11px] font-bold text-muted-foreground mb-1">Source Evidence:</p>
                        {relatedSources.map((s) => s && (
                          <button
                            key={s.id}
                            onClick={() => useUIStore.getState().openSourceModal(s.id, 'details')}
                            className="w-full flex items-center justify-between gap-2 p-2 rounded-xl border text-xs text-left hover:bg-[var(--bg-hover)] transition-all group/link cursor-pointer"
                            style={{ background: 'var(--bg-base)', borderColor: 'var(--border)' }}
                          >
                            <span className="truncate font-medium group-hover/link:text-indigo-400" style={{ color: 'var(--text-primary)' }}>
                              {s.title} ({s.provider})
                            </span>
                            <ExternalLink className="w-3 h-3 text-muted-foreground group-hover/link:text-indigo-400 flex-shrink-0" />
                          </button>
                        ))}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
