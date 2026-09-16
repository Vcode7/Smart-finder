'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';
import { useResearchStore } from '@/store/research';
import { useUIStore } from '@/store/ui';
import { toast } from 'sonner';
import { Network, Zap, RefreshCw, Sparkles, Layers, Info } from 'lucide-react';
import type { ResearchSession } from '@/types/research';

// D3 graph is client-only for SSR safety
const KnowledgeGraphCanvas = dynamic(() => import('./KnowledgeGraphCanvas'), {
  ssr: false,
  loading: () => (
    <div className="h-[480px] rounded-2xl flex flex-col items-center justify-center border" style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}>
      <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mb-3" />
      <span className="text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Initializing Graph Simulation...</span>
    </div>
  ),
});

interface KnowledgeGraphProps {
  session: ResearchSession;
  sessionId: string;
}

export function KnowledgeGraph({ session, sessionId }: KnowledgeGraphProps) {
  const { setKnowledgeGraph } = useResearchStore();
  const { aiSelectedSourceIds } = useUIStore();
  const [loading, setLoading] = useState(false);
  const graph = session.knowledgeGraph;

  const generate = async () => {
    if (session.sources.length === 0) {
      toast.error('No sources available');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch('/api/entities', {
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
        throw new Error(errorData.message || 'Graph extraction failed');
      }
      const data = await res.json();
      setKnowledgeGraph(sessionId, data);
      toast.success('Knowledge graph constructed!');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to construct graph';
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  if (!graph || graph.nodes.length === 0) {
    return (
      <div
        className="rounded-3xl p-8 sm:p-12 text-center border shadow-xl relative overflow-hidden"
        style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
      >
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5 shadow-lg shadow-cyan-500/25" style={{ background: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)' }}>
          <Network className="w-8 h-8 text-white" />
        </div>

        <h3 className="text-xl sm:text-2xl font-extrabold mb-2" style={{ color: 'var(--text-primary)' }}>
          Interactive Entity & Concept Knowledge Graph
        </h3>

        <p className="text-xs sm:text-sm max-w-xl mx-auto mb-8 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Discover underlying links between key people, organizations, policy entities, technologies, and source materials with D3 force-directed physics.
        </p>

        <button
          onClick={generate}
          disabled={loading}
          className="inline-flex items-center gap-2.5 px-6 py-3 rounded-2xl font-bold text-sm text-white shadow-lg shadow-cyan-500/25 transition-all hover:scale-105 disabled:opacity-50"
          style={{ background: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)' }}
        >
          {loading ? (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Extracting Graph Nodes...</span>
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4" />
              <span>Construct Knowledge Graph</span>
            </>
          )}
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-2xl overflow-hidden border shadow-xl" style={{ borderColor: 'var(--border)', background: 'var(--bg-elevated)' }}>
      {/* Graph Toolbar */}
      <div
        className="flex items-center justify-between px-5 py-3.5 border-b"
        style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}
      >
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center bg-cyan-500/15 text-cyan-400">
            <Network className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              Entity Knowledge Graph
            </h3>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              {graph.nodes.length} entity nodes • {graph.edges.length} relational connections
            </p>
          </div>
        </div>

        <button
          onClick={generate}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all hover:bg-[var(--bg-hover)]"
          style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', background: 'var(--bg-base)' }}
          title="Rebuild Knowledge Graph"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span className="hidden sm:inline">Rebuild Graph</span>
        </button>
      </div>

      {/* D3 Graph Viewport */}
      <KnowledgeGraphCanvas graph={graph} session={session} />
    </div>
  );
}
