'use client';
// src/components/ai/CrossSourceConnections.tsx
// Cross-source connection insights and shared correlation patterns

import { Link2, Sparkles, CheckCircle2, ShieldCheck, ArrowRight } from 'lucide-react';

interface ConnectionItem {
  id: string;
  theme: string;
  description: string;
  sourcesInvolved: string[];
  confidence: 'high' | 'medium' | 'low';
}

interface Props {
  connections: ConnectionItem[];
  crossSynthesis?: string;
  onOpenSource?: (sourceId: string) => void;
}

export default function CrossSourceConnections({ connections, crossSynthesis, onOpenSource }: Props) {
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
          style={{ background: 'rgba(6, 182, 212, 0.15)', color: '#06b6d4' }}>
          <Link2 className="w-4 h-4" />
        </div>
        <div>
          <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
            Cross-Source Connections & Correlation Patterns
          </h3>
          <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
            Identifying shared entities, common patterns, and multi-document correlations
          </p>
        </div>
      </div>

      {/* Cross Synthesis Summary */}
      {crossSynthesis && (
        <div className="p-4 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 text-xs text-cyan-200 leading-relaxed">
          <div className="font-bold text-cyan-400 mb-1 flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Overarching Connection Synthesis:</span>
          </div>
          {crossSynthesis}
        </div>
      )}

      {/* Connections List */}
      <div className="space-y-3">
        {connections.map((conn, index) => (
          <div
            key={conn.id || index}
            className="p-4 rounded-2xl space-y-2 transition-all hover:border-zinc-500/30"
            style={{
              background: 'var(--bg-base)',
              border: '1px solid var(--border)',
            }}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-bold text-white flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-cyan-400" />
                {conn.theme}
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-bold uppercase">
                {conn.confidence} confidence
              </span>
            </div>

            <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
              {conn.description}
            </p>

            {conn.sourcesInvolved && conn.sourcesInvolved.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 pt-1.5 border-t border-[var(--border)] text-[10px] text-zinc-400">
                <span className="font-semibold text-zinc-300">Connected Sources:</span>
                {conn.sourcesInvolved.map((srcName, sIdx) => (
                  <span
                    key={sIdx}
                    className="px-2 py-0.5 rounded-md bg-white/5 border border-white/10 text-cyan-300 truncate max-w-[200px]"
                  >
                    {srcName}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
