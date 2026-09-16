'use client';

import { Zap, Star, AlertCircle, Sparkles, Hash, BarChart2, ShieldCheck, Bookmark } from 'lucide-react';
import type { AIInsights } from '@/types/research';

interface AISummaryPanelProps {
  insights: AIInsights;
  compact?: boolean;
}

export function AISummaryPanel({ insights, compact }: AISummaryPanelProps) {
  return (
    <div
      className="rounded-2xl p-4 space-y-3.5 border shadow-sm"
      style={{
        background: 'linear-gradient(135deg, rgba(168, 85, 247, 0.08) 0%, rgba(99, 102, 241, 0.05) 100%)',
        borderColor: 'rgba(168, 85, 247, 0.25)',
      }}
    >
      {/* Executive Summary */}
      <div>
        <div className="flex items-center gap-2 mb-1.5">
          <div className="w-5 h-5 rounded-md bg-purple-500/20 flex items-center justify-center text-purple-400">
            <Sparkles className="w-3 h-3" />
          </div>
          <span className="text-xs font-bold uppercase tracking-wider text-purple-400">
            Executive Synthesis
          </span>
        </div>
        <p className="text-xs leading-relaxed font-medium" style={{ color: 'var(--text-primary)' }}>
          {compact && insights.summary.length > 240
            ? insights.summary.slice(0, 240) + '…'
            : insights.summary}
        </p>
      </div>

      {/* Key Extracted Points */}
      {!compact && insights.keyPoints && insights.keyPoints.length > 0 && (
        <div className="pt-1 border-t" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
          <div className="flex items-center gap-1.5 mb-2">
            <Hash className="w-3.5 h-3.5 text-indigo-400" />
            <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-400">
              Core Takeaways
            </span>
          </div>
          <ul className="space-y-1.5">
            {insights.keyPoints.slice(0, 5).map((kp, i) => (
              <li key={i} className="flex items-start gap-2 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 flex-shrink-0" />
                <span className="flex-1">
                  {kp.text}
                  {kp.citation?.timestamp && (
                    <span className="ml-1.5 text-[10px] px-1.5 py-0.2 rounded font-mono font-bold bg-indigo-500/20 text-indigo-400">
                      @{kp.citation.timestamp}
                    </span>
                  )}
                  {kp.citation?.page && (
                    <span className="ml-1.5 text-[10px] px-1.5 py-0.2 rounded font-mono font-bold bg-cyan-500/20 text-cyan-400">
                      {kp.citation.page}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Key Quantitative Statistics */}
      {!compact && insights.statistics && insights.statistics.length > 0 && (
        <div className="pt-1 border-t" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
          <div className="flex items-center gap-1.5 mb-2">
            <BarChart2 className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-400">
              Key Statistics
            </span>
          </div>
          <div className="grid grid-cols-1 gap-1.5">
            {insights.statistics.slice(0, 3).map((stat, i) => (
              <div
                key={i}
                className="text-xs p-2 rounded-xl border flex items-center gap-2"
                style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
              >
                <span className="text-emerald-400 font-mono font-bold">📊</span>
                <span className="font-medium" style={{ color: 'var(--text-primary)' }}>{stat}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Extracted Entities */}
      {!compact && insights.entities && insights.entities.length > 0 && (
        <div className="pt-1 border-t" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
          <span className="text-[11px] font-bold uppercase tracking-wider block mb-2" style={{ color: 'var(--text-muted)' }}>
            Associated Entities & Topics
          </span>
          <div className="flex flex-wrap gap-1.5">
            {insights.entities.slice(0, 8).map((entity, i) => (
              <span
                key={i}
                className="text-[11px] font-semibold px-2.5 py-0.5 rounded-full border"
                style={{
                  background: 'var(--bg-card)',
                  borderColor: 'var(--border)',
                  color: 'var(--text-secondary)'
                }}
              >
                {entity.name}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Strategic Significance / Importance */}
      {!compact && insights.importance && (
        <div
          className="flex items-start gap-2.5 p-3 rounded-xl border text-xs"
          style={{ background: 'rgba(245, 158, 11, 0.1)', borderColor: 'rgba(245, 158, 11, 0.25)' }}
        >
          <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <span className="font-bold text-amber-400 block mb-0.5">Why This Source Matters:</span>
            <span className="font-normal" style={{ color: 'var(--text-primary)' }}>{insights.importance}</span>
          </div>
        </div>
      )}
    </div>
  );
}
