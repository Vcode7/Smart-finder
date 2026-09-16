'use client';
// src/components/ai/SourceComparisonMatrix.tsx
// Interactive multi-perspective Source Comparison Matrix

import { Scale, CheckCircle2, AlertTriangle, HelpCircle, FileText, ExternalLink } from 'lucide-react';
import type { ComparisonResult } from '@/types/research';

interface Props {
  comparison: ComparisonResult;
  onOpenSource?: (sourceId: string) => void;
}

export default function SourceComparisonMatrix({ comparison, onOpenSource }: Props) {
  return (
    <div
      className="p-5 rounded-3xl space-y-5 shadow-xl"
      style={{
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border)',
        boxShadow: '0 12px 36px rgba(0,0,0,0.25)',
      }}
    >
      {/* Header */}
      <div className="flex items-center gap-2.5 pb-3 border-b border-[var(--border)]">
        <div className="w-8 h-8 rounded-xl flex items-center justify-center"
          style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b' }}>
          <Scale className="w-4 h-4" />
        </div>
        <div>
          <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
            Comparative Source Analysis Matrix
          </h3>
          <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
            Cross-referencing {comparison.sourceIds.length} sources for consensus, discrepancies, and evidence
          </p>
        </div>
      </div>

      {/* Similarities & Points of Consensus */}
      {comparison.similarities && comparison.similarities.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-400">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Core Points of Consensus & Agreement</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
            {comparison.similarities.map((item, idx) => (
              <div
                key={idx}
                className="p-3 rounded-xl text-xs leading-relaxed"
                style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.2)', color: 'var(--text-secondary)' }}
              >
                {item}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Discrepancies & Divergent Perspectives */}
      {comparison.differences && comparison.differences.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-bold text-amber-400">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>Key Divergences & Perspective Differences</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
            {comparison.differences.map((item, idx) => (
              <div
                key={idx}
                className="p-3 rounded-xl text-xs leading-relaxed"
                style={{ background: 'rgba(245, 158, 11, 0.08)', border: '1px solid rgba(245, 158, 11, 0.2)', color: 'var(--text-secondary)' }}
              >
                {item}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Topic Comparison Table */}
      {comparison.topicTable && comparison.topicTable.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-bold text-indigo-400 flex items-center gap-1.5">
            <FileText className="w-3.5 h-3.5" />
            <span>Dimension-by-Dimension Breakdown</span>
          </div>
          <div className="overflow-x-auto rounded-2xl border border-[var(--border)]">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-[var(--bg-base)] border-b border-[var(--border)]">
                  <th className="p-3 font-bold text-zinc-300">Dimension / Topic</th>
                  {comparison.sourceIds.map((sid, sIdx) => (
                    <th key={sIdx} className="p-3 font-bold text-zinc-300">
                      <button
                        type="button"
                        onClick={() => onOpenSource?.(sid)}
                        className="hover:text-indigo-400 transition-colors inline-flex items-center gap-1"
                      >
                        <span>Source #{sIdx + 1}</span>
                        <ExternalLink className="w-2.5 h-2.5" />
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {comparison.topicTable.map((row, rIdx) => (
                  <tr key={rIdx} className="border-b border-[var(--border)] hover:bg-white/[0.02]">
                    <td className="p-3 font-semibold text-zinc-200">{row.topic || `Dimension ${rIdx + 1}`}</td>
                    {comparison.sourceIds.map((sid, sIdx) => (
                      <td key={sIdx} className="p-3 text-zinc-400 leading-relaxed">
                        {row[sid] || '—'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* AI Synthesis Conclusion */}
      {comparison.aiConclusion && (
        <div className="p-3.5 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 text-xs text-indigo-200 leading-relaxed">
          <span className="font-bold text-indigo-300">Comparative Conclusion: </span>
          {comparison.aiConclusion}
        </div>
      )}
    </div>
  );
}
