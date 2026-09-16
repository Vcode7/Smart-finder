// src/components/ai/ComparePanel.tsx
// Cross-Source Intelligence Comparison with Unrestricted Multi-Source Selection & Select All / Deselect All

'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { useResearchStore } from '@/store/research';
import { useUIStore } from '@/store/ui';
import { toast } from 'sonner';
import {
  CheckSquare, Square, Zap,
  GitCompare, CheckCircle2, AlertTriangle, Scale,
  Table as TableIcon, Sparkles, CheckCheck, XSquare
} from 'lucide-react';
import type { ResearchSession } from '@/types/research';

interface ComparePanelProps {
  session: ResearchSession;
  sessionId: string;
}

export function ComparePanel({ session, sessionId }: ComparePanelProps) {
  const { addComparison } = useResearchStore();
  const { aiSelectedSourceIds } = useUIStore();
  const [selectedIds, setSelectedIds] = useState<string[]>(() => {
    if (aiSelectedSourceIds.length >= 2) return aiSelectedSourceIds;
    if (aiSelectedSourceIds.length === 1) {
      const other = session.sources.find((s) => s.id !== aiSelectedSourceIds[0]);
      return other ? [aiSelectedSourceIds[0], other.id] : [aiSelectedSourceIds[0]];
    }
    return session.sources.slice(0, 3).map((s) => s.id);
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(session.comparisons[0] || null);

  const toggle = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const selectAll = () => {
    setSelectedIds(session.sources.map((s) => s.id));
  };

  const deselectAll = () => {
    setSelectedIds([]);
  };

  const compare = async () => {
    if (selectedIds.length < 2) {
      toast.error('Please select at least 2 sources to compare');
      return;
    }
    setLoading(true);
    try {
      const sources = selectedIds
        .map((id) => session.sources.find((s) => s.id === id))
        .filter(Boolean);

      const res = await fetch('/api/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources, selectedSourceIds: selectedIds }),
      });

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.message || 'Comparison failed');
      }
      const data = await res.json();
      addComparison(sessionId, data);
      setResult(data);
      toast.success('Comparative synthesis generated!');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to compare sources.';
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Source Selector Box */}
      <div
        className="rounded-2xl overflow-hidden border shadow-lg"
        style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
      >
        <div
          className="flex items-center justify-between px-5 py-3.5 border-b gap-3 flex-wrap"
          style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl flex items-center justify-center bg-indigo-500/15 text-indigo-400 flex-shrink-0">
              <Scale className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                Select Sources to Cross-Examine
              </h3>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                Choose 2 or more sources for topic-by-topic comparison ({selectedIds.length} of {session.sources.length} selected)
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Select All / Deselect All Controls */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={selectAll}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-[11px] font-semibold transition-colors hover:bg-[var(--bg-hover)] text-[var(--text-secondary)]"
                style={{ borderColor: 'var(--border)', background: 'var(--bg-base)' }}
                title="Select all sources"
              >
                <CheckCheck className="w-3.5 h-3.5 text-indigo-400" />
                <span>Select All</span>
              </button>

              <button
                type="button"
                onClick={deselectAll}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-[11px] font-semibold transition-colors hover:bg-[var(--bg-hover)] text-[var(--text-secondary)]"
                style={{ borderColor: 'var(--border)', background: 'var(--bg-base)' }}
                title="Clear selection"
              >
                <XSquare className="w-3.5 h-3.5 text-muted-foreground" />
                <span>Clear</span>
              </button>
            </div>

            <button
              onClick={compare}
              disabled={selectedIds.length < 2 || loading}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold text-white shadow-md shadow-indigo-500/20 transition-all hover:scale-105 disabled:opacity-40 disabled:hover:scale-100"
              style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}
            >
              {loading ? (
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <Zap className="w-3.5 h-3.5" />
              )}
              <span>{loading ? 'Synthesizing...' : `Compare (${selectedIds.length})`}</span>
            </button>
          </div>
        </div>

        {/* Source Checklist with unrestricted selection */}
        <div className="max-h-72 overflow-y-auto divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
          {session.sources.map((source) => {
            const isSelected = selectedIds.includes(source.id);
            return (
              <button
                key={source.id}
                type="button"
                onClick={() => toggle(source.id)}
                className={`w-full flex items-center gap-3.5 px-5 py-3 text-left transition-all duration-150 ${
                  isSelected ? 'bg-indigo-500/10' : 'hover:bg-[var(--bg-hover)]'
                }`}
                style={{
                  color: 'var(--text-primary)',
                }}
              >
                <div className="flex-shrink-0">
                  {isSelected ? (
                    <div className="w-5 h-5 rounded-md bg-indigo-600 flex items-center justify-center text-white shadow-sm">
                      <CheckSquare className="w-3.5 h-3.5" />
                    </div>
                  ) : (
                    <div className="w-5 h-5 rounded-md border border-[var(--border)] flex items-center justify-center text-muted-foreground" style={{ background: 'var(--bg-base)' }}>
                      <Square className="w-3.5 h-3.5 opacity-40" />
                    </div>
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold truncate leading-snug" style={{ color: 'var(--text-primary)' }}>
                    {source.title}
                  </p>
                  <p className="text-[11px] truncate mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    {source.provider} • {source.type} • {source.relevanceScore}% match
                  </p>
                </div>

                <span
                  className="text-[10px] font-mono uppercase px-2 py-0.5 rounded-full"
                  style={{
                    background: isSelected ? 'var(--accent-muted)' : 'var(--bg-active)',
                    color: isSelected ? 'var(--accent)' : 'var(--text-muted)',
                  }}
                >
                  {source.type}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Comparison Results */}
      {result && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl overflow-hidden border shadow-xl"
          style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
        >
          {/* Header Banner */}
          <div
            className="flex items-center justify-between px-5 py-4 border-b"
            style={{
              background: 'linear-gradient(90deg, rgba(99,102,241,0.15) 0%, rgba(168,85,247,0.15) 100%)',
              borderColor: 'var(--border)',
            }}
          >
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                Cross-Source Intelligence Synthesis
              </span>
            </div>
            <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
              {new Date(result.generatedAt).toLocaleTimeString()}
            </span>
          </div>

          <div className="p-5 space-y-6">
            {/* AI Conclusion High-Impact Card */}
            {result.aiConclusion && (
              <div
                className="p-4 rounded-2xl border"
                style={{
                  background: 'linear-gradient(135deg, rgba(99,102,241,0.12) 0%, rgba(168,85,247,0.08) 100%)',
                  borderColor: 'rgba(99,102,241,0.3)',
                }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-6 h-6 rounded-lg bg-indigo-500/20 flex items-center justify-center text-indigo-400">
                    <Zap className="w-3.5 h-3.5" />
                  </div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-400">
                    Unified AI Conclusion & Synthesis
                  </h4>
                </div>
                <p className="text-xs sm:text-sm font-normal leading-relaxed" style={{ color: 'var(--text-primary)' }}>
                  {result.aiConclusion}
                </p>
              </div>
            )}

            {/* Grid for Similarities, Differences, Contradictions */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Similarities */}
              <div
                className="p-4 rounded-2xl border"
                style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
              >
                <div className="flex items-center gap-2 mb-3">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  <h4 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
                    Key Consensus ({result.similarities.length})
                  </h4>
                </div>
                <ul className="space-y-2">
                  {result.similarities.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mt-1.5 flex-shrink-0" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Differences */}
              <div
                className="p-4 rounded-2xl border"
                style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
              >
                <div className="flex items-center gap-2 mb-3">
                  <GitCompare className="w-4 h-4 text-amber-400" />
                  <h4 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
                    Distinct Focuses ({result.differences.length})
                  </h4>
                </div>
                <ul className="space-y-2">
                  {result.differences.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 flex-shrink-0" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Contradicting Claims */}
              <div
                className="p-4 rounded-2xl border"
                style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
              >
                <div className="flex items-center gap-2 mb-3">
                  <AlertTriangle className="w-4 h-4 text-rose-400" />
                  <h4 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
                    Conflicting Claims ({result.conflictingClaims.length})
                  </h4>
                </div>
                <ul className="space-y-2">
                  {result.conflictingClaims.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                      <span className="w-1.5 h-1.5 rounded-full bg-rose-400 mt-1.5 flex-shrink-0" />
                      <span>{item}</span>
                    </li>
                  ))}
                  {result.conflictingClaims.length === 0 && (
                    <p className="text-xs italic" style={{ color: 'var(--text-muted)' }}>
                      No direct conflicting claims detected.
                    </p>
                  )}
                </ul>
              </div>
            </div>

            {/* Matrix Table View */}
            {result.topicTable && result.topicTable.length > 0 && (
              <div className="rounded-2xl border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
                <div className="px-4 py-3 border-b flex items-center gap-2" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
                  <TableIcon className="w-4 h-4 text-indigo-400" />
                  <h4 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
                    Topic-by-Topic Comparative Matrix
                  </h4>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr style={{ background: 'var(--bg-active)' }}>
                        <th className="text-left px-4 py-3 font-bold" style={{ color: 'var(--text-primary)', width: '25%' }}>
                          Topic Dimension
                        </th>
                        {result.sourceIds.map((id) => {
                          const s = session.sources.find((src) => src.id === id);
                          return (
                            <th key={id} className="text-left px-4 py-3 font-bold min-w-[200px]" style={{ color: 'var(--text-primary)' }}>
                              <span className="line-clamp-1">{s?.title || id.slice(0, 8)}</span>
                              <span className="text-[10px] font-normal block opacity-70">{s?.provider}</span>
                            </th>
                          );
                        })}
                      </tr>
                    </thead>
                    <tbody className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
                      {result.topicTable.map((row, i) => (
                        <tr key={i} className="hover:bg-[var(--bg-hover)] transition-colors">
                          <td className="px-4 py-3 font-bold" style={{ color: 'var(--accent)' }}>
                            {row.topic}
                          </td>
                          {result.sourceIds.map((id) => (
                            <td key={id} className="px-4 py-3 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                              {row[id] || '—'}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </motion.div>
      )}
    </div>
  );
}
