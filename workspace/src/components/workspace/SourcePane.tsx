// src/components/workspace/SourcePane.tsx
// High-Capability Multi-Modal Research Pane with Dynamic Type Switching, Source Picker, and Maximize Controls

'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Image from 'next/image';
import dynamic from 'next/dynamic';
import { useResearchStore } from '@/store/research';
import { ChatPanel } from '@/components/ai/ChatPanel';
import { AISummaryPanel } from '@/components/ai/AISummaryPanel';
import { BriefingPanel } from '@/components/ai/BriefingPanel';
import { ResearchTimeline } from '@/components/timeline/ResearchTimeline';
import { ComparePanel } from '@/components/ai/ComparePanel';
import {
  ExternalLink, Minimize2, Maximize2, X, MessageSquare,
  Zap, ChevronDown, LayoutGrid, Sparkles, Search, Video,
  BookOpen, FileText, BarChart3, Globe, GitBranch, Network,
  ShieldCheck, ArrowUpRight, Check, Eye
} from 'lucide-react';
import type { ResearchSession, WorkspacePane as WorkspacePaneType, PaneContentType, Source } from '@/types/research';

const KnowledgeGraphCanvas = dynamic(() => import('@/components/graph/KnowledgeGraphCanvas'), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center text-xs text-[var(--text-muted)]">
      Loading Graph Simulation...
    </div>
  ),
});

const CONTENT_TYPE_OPTIONS: Array<{ type: PaneContentType; label: string; icon: React.ElementType; color: string }> = [
  { type: 'insights', label: 'AI Insights & Brief', icon: Zap, color: '#a855f7' },
  { type: 'video', label: 'Video Lecture', icon: Video, color: '#f43f5e' },
  { type: 'paper', label: 'Academic Paper', icon: BookOpen, color: '#06b6d4' },
  { type: 'timeline', label: 'Research Timeline', icon: GitBranch, color: '#10b981' },
  { type: 'graph', label: 'Knowledge Graph', icon: Network, color: '#06b6d4' },
  { type: 'compare', label: 'Compare Sources', icon: BarChart3, color: '#f59e0b' },
  { type: 'chat', label: 'Deep-Dive Chat', icon: MessageSquare, color: '#6366f1' },
  { type: 'article', label: 'Articles & News', icon: FileText, color: '#10b981' },
  { type: 'report', label: 'Policy Report', icon: BarChart3, color: '#f59e0b' },
  { type: 'source', label: 'Specific Source', icon: LayoutGrid, color: '#8b5cf6' },
];

interface SourcePaneProps {
  pane: WorkspacePaneType;
  session: ResearchSession;
  sessionId: string;
  isFullScreen?: boolean;
}

export function SourcePane({ pane, session, sessionId, isFullScreen = true }: SourcePaneProps) {
  const { updatePane, setPaneSource, setPaneContentType, setAIInsights } = useResearchStore();
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [typeDropdownOpen, setTypeDropdownOpen] = useState(false);
  const [searchFilter, setSearchFilter] = useState('');
  const [isSummarizing, setIsSummarizing] = useState(false);

  // Determine current active content type and source
  const contentType = pane.contentType || 'source';

  // Automatically find appropriate source based on contentType if no specific sourceId is pinned
  const source: Source | null = pane.sourceId
    ? session.sources.find((s) => s.id === pane.sourceId) || null
    : contentType === 'video'
    ? session.sources.find((s) => s.type === 'video') || null
    : contentType === 'paper'
    ? session.sources.find((s) => s.type === 'paper') || null
    : contentType === 'article'
    ? session.sources.find((s) => s.type === 'article') || null
    : contentType === 'report'
    ? session.sources.find((s) => s.type === 'report') || null
    : session.sources[0] || null;

  const currentTypeConfig = CONTENT_TYPE_OPTIONS.find((t) => t.type === contentType) || CONTENT_TYPE_OPTIONS[0];
  const TypeIcon = currentTypeConfig.icon;

  const handleSummarize = async () => {
    if (!source) return;
    if (source.aiInsights) {
      updatePane(sessionId, pane.id, { insightsOpen: !pane.insightsOpen });
      return;
    }
    setIsSummarizing(true);
    try {
      const res = await fetch('/api/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source }),
      });
      if (res.ok) {
        const { insights } = await res.json();
        setAIInsights(sessionId, source.id, insights);
        updatePane(sessionId, pane.id, { insightsOpen: true });
      }
    } finally {
      setIsSummarizing(false);
    }
  };

  const filteredSources = session.sources.filter((s) =>
    s.title.toLowerCase().includes(searchFilter.toLowerCase()) ||
    s.provider.toLowerCase().includes(searchFilter.toLowerCase()) ||
    s.type.toLowerCase().includes(searchFilter.toLowerCase())
  );

  return (
    <motion.div
      layout
      className={`flex flex-col rounded-2xl border transition-all duration-200 overflow-hidden shadow-lg h-full ${
        pane.isMaximized ? 'ring-2 ring-indigo-500/80 shadow-indigo-500/20' : ''
      }`}
      style={{
        background: 'var(--bg-elevated)',
        borderColor: 'var(--border)',
      }}
    >
      {/* Pane Toolbar Header */}
      <header
        className="flex items-center justify-between gap-2 px-3.5 py-2 border-b flex-shrink-0 z-20"
        style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}
      >
        {/* Left: Content Type Switcher Dropdown */}
        <div className="relative">
          <button
            onClick={() => {
              setTypeDropdownOpen(!typeDropdownOpen);
              setSelectorOpen(false);
            }}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl border text-xs font-bold transition-all hover:bg-[var(--bg-hover)]"
            style={{
              background: 'var(--bg-base)',
              borderColor: 'var(--border)',
              color: currentTypeConfig.color,
            }}
            title="Switch Pane View"
          >
            <TypeIcon className="w-3.5 h-3.5" />
            <span className="font-bold">{currentTypeConfig.label}</span>
            <ChevronDown className="w-3 h-3 opacity-60 ml-0.5" />
          </button>

          {/* Type Switcher Popover */}
          <AnimatePresence>
            {typeDropdownOpen && (
              <motion.div
                initial={{ opacity: 0, y: -4, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -4, scale: 0.95 }}
                className="absolute top-full left-0 mt-1.5 z-40 w-52 p-1.5 rounded-2xl border shadow-2xl backdrop-blur-2xl"
                style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
              >
                <div className="p-1 text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                  Switch Pane Content
                </div>
                <div className="space-y-0.5 max-h-60 overflow-y-auto">
                  {CONTENT_TYPE_OPTIONS.map((opt) => {
                    const Icon = opt.icon;
                    const isSelected = contentType === opt.type;
                    return (
                      <button
                        key={opt.type}
                        onClick={() => {
                          setPaneContentType(sessionId, pane.id, opt.type);
                          setTypeDropdownOpen(false);
                        }}
                        className={`w-full flex items-center gap-2 px-2.5 py-1.5 text-xs rounded-xl transition-all ${
                          isSelected ? 'bg-indigo-500/15 text-indigo-400 font-bold' : 'hover:bg-[var(--bg-hover)] text-foreground'
                        }`}
                      >
                        <Icon className="w-3.5 h-3.5" style={{ color: opt.color }} />
                        <span className="flex-1 text-left">{opt.label}</span>
                        {isSelected && <Check className="w-3 h-3 text-indigo-400" />}
                      </button>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Center: Searchable Source Selector */}
        <div className="relative flex-1 min-w-0">
          <button
            onClick={() => {
              setSelectorOpen(!selectorOpen);
              setTypeDropdownOpen(false);
            }}
            className="flex items-center gap-2 px-2.5 py-1 rounded-xl border text-left text-xs font-semibold truncate transition-all hover:bg-[var(--bg-hover)] w-full"
            style={{
              background: 'var(--bg-base)',
              borderColor: 'var(--border)',
              color: source ? 'var(--text-primary)' : 'var(--text-muted)',
            }}
            title="Replace source for this pane"
          >
            <span className="truncate flex-1">
              {source ? source.title : 'Select Source...'}
            </span>
            <Search className="w-3 h-3 opacity-60 flex-shrink-0" />
          </button>

          {/* Searchable Source Selection Dropdown */}
          <AnimatePresence>
            {selectorOpen && (
              <motion.div
                initial={{ opacity: 0, y: -6, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -6, scale: 0.98 }}
                className="absolute top-full left-0 right-0 z-40 mt-1.5 p-2 rounded-2xl border shadow-2xl backdrop-blur-2xl"
                style={{
                  background: 'var(--bg-elevated)',
                  borderColor: 'var(--border)',
                  maxHeight: 280,
                }}
              >
                <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl border mb-2" style={{ background: 'var(--bg-base)', borderColor: 'var(--border)' }}>
                  <Search className="w-3 h-3 text-muted-foreground" />
                  <input
                    value={searchFilter}
                    onChange={(e) => setSearchFilter(e.target.value)}
                    placeholder="Search sources across all modalities..."
                    className="bg-transparent text-xs outline-none flex-1 font-medium"
                    style={{ color: 'var(--text-primary)' }}
                    autoFocus
                  />
                </div>

                <div className="overflow-y-auto max-h-48 space-y-1">
                  {filteredSources.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => {
                        setPaneSource(sessionId, pane.id, s.id);
                        setSelectorOpen(false);
                      }}
                      className={`w-full text-left px-3 py-2 text-xs rounded-xl transition-all ${
                        s.id === source?.id ? 'bg-indigo-500/15 text-indigo-400 font-bold' : 'hover:bg-[var(--bg-hover)] text-foreground'
                      }`}
                    >
                      <p className="truncate font-semibold">{s.title}</p>
                      <p className="text-[10px] text-muted-foreground truncate">{s.provider} • {s.type} • {s.relevanceScore}% match</p>
                    </button>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Right: Actions (AI Analyze, Chat, Open, Maximize, Close) */}
        <div className="flex items-center gap-1 flex-shrink-0">
          {source && (
            <>
              <button
                onClick={handleSummarize}
                disabled={isSummarizing}
                className="p-1.5 rounded-lg border text-xs transition-all hover:bg-[var(--bg-hover)]"
                style={{
                  color: source.aiInsights ? '#a855f7' : 'var(--text-muted)',
                  borderColor: 'var(--border)',
                }}
                title={source.aiInsights ? 'View AI Insights' : 'Analyze Source with Groq Qwen 3.6'}
              >
                {isSummarizing ? (
                  <div className="w-3.5 h-3.5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
                ) : (
                  <Zap className="w-3.5 h-3.5" />
                )}
              </button>

              <button
                onClick={() => updatePane(sessionId, pane.id, { chatOpen: !pane.chatOpen })}
                className="p-1.5 rounded-lg border text-xs transition-all hover:bg-[var(--bg-hover)]"
                style={{
                  color: pane.chatOpen ? '#6366f1' : 'var(--text-muted)',
                  borderColor: 'var(--border)',
                }}
                title="Toggle AI Source Chat"
              >
                <MessageSquare className="w-3.5 h-3.5" />
              </button>

              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1.5 rounded-lg border text-xs transition-all hover:bg-[var(--bg-hover)]"
                style={{ color: 'var(--text-muted)', borderColor: 'var(--border)' }}
                title="Open original link"
              >
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            </>
          )}

          {/* Maximize / Restore Button */}
          <button
            onClick={() => updatePane(sessionId, pane.id, { isMaximized: !pane.isMaximized })}
            className="p-1.5 rounded-lg border text-xs transition-all hover:bg-[var(--bg-hover)]"
            style={{
              color: pane.isMaximized ? '#6366f1' : 'var(--text-muted)',
              borderColor: 'var(--border)',
            }}
            title={pane.isMaximized ? 'Restore 2×2 View' : 'Maximize Pane (Full Focus)'}
          >
            {pane.isMaximized ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </header>

      {/* Pane Content Body */}
      <main className="flex-1 overflow-y-auto p-3 min-h-0 relative">
        {/* VIEW 1: AI INSIGHTS / BRIEF */}
        {contentType === 'insights' && (
          <div className="h-full overflow-y-auto pr-1">
            {source?.aiInsights ? (
              <AISummaryPanel insights={source.aiInsights} />
            ) : session.overallBriefing ? (
              <div className="space-y-3">
                <div className="p-3.5 rounded-xl border" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
                  <div className="flex items-center gap-2 mb-2 text-indigo-400 font-bold text-xs">
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Executive Summary</span>
                  </div>
                  <p className="text-xs leading-relaxed" style={{ color: 'var(--text-primary)' }}>
                    {session.overallBriefing.executiveSummary}
                  </p>
                </div>

                <div className="p-3.5 rounded-xl border" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
                  <div className="flex items-center gap-2 mb-2 text-emerald-400 font-bold text-xs">
                    <ShieldCheck className="w-3.5 h-3.5" />
                    <span>Key Findings ({session.overallBriefing.mainFindings.length})</span>
                  </div>
                  <ul className="space-y-1.5 text-xs">
                    {session.overallBriefing.mainFindings.slice(0, 4).map((f, i) => (
                      <li key={i} className="flex items-start gap-2" style={{ color: 'var(--text-secondary)' }}>
                        <span className="text-indigo-400 font-bold">•</span>
                        <span>{f}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-center p-6">
                <Zap className="w-8 h-8 text-indigo-400 mb-2" />
                <p className="text-xs font-bold mb-1" style={{ color: 'var(--text-primary)' }}>No Insights Generated Yet</p>
                <p className="text-[11px] mb-3 max-w-xs" style={{ color: 'var(--text-muted)' }}>
                  Click below to synthesize this source or generate an overall brief using Qwen 3.6 27B.
                </p>
                <button
                  onClick={handleSummarize}
                  disabled={isSummarizing || !source}
                  className="px-3 py-1.5 rounded-xl text-xs font-bold text-white shadow-md shadow-indigo-500/20"
                  style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}
                >
                  {isSummarizing ? 'Analyzing...' : 'Generate AI Insights'}
                </button>
              </div>
            )}
          </div>
        )}

        {/* VIEW 2: VIDEO LECTURE / PRESENTATION */}
        {contentType === 'video' && source && (
          <div className="h-full flex flex-col space-y-3 overflow-y-auto pr-1">
            {source.thumbnail && (
              <div className="relative w-full aspect-video rounded-xl overflow-hidden border flex-shrink-0" style={{ borderColor: 'var(--border)' }}>
                <Image
                  src={source.thumbnail}
                  alt={source.title}
                  fill
                  className="object-cover"
                  unoptimized
                />
                <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent flex items-end p-3">
                  <div className="text-white text-xs font-bold truncate">
                    {source.title}
                  </div>
                </div>
                {source.duration && (
                  <span className="absolute bottom-2 right-2 text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-black/80 text-white">
                    {source.duration}
                  </span>
                )}
              </div>
            )}

            <div className="p-3 rounded-xl border flex-1 space-y-2" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
              <div className="flex items-center justify-between text-[11px]">
                <span className="font-bold text-rose-400">{source.provider}</span>
                {source.author && <span style={{ color: 'var(--text-muted)' }}>Channel: {source.author}</span>}
              </div>
              <p className="text-xs leading-relaxed line-clamp-4" style={{ color: 'var(--text-secondary)' }}>
                {source.description || 'No video description available.'}
              </p>
            </div>
          </div>
        )}

        {/* VIEW 3: ACADEMIC PAPER */}
        {contentType === 'paper' && source && (
          <div className="h-full overflow-y-auto space-y-3 pr-1">
            <div className="p-3.5 rounded-xl border space-y-2" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-400">
                  {source.provider || 'Academic Venue'}
                </span>
                {source.citationCount !== undefined && (
                  <span className="text-[10px] font-mono font-semibold" style={{ color: 'var(--text-muted)' }}>
                    {source.citationCount} Citations
                  </span>
                )}
              </div>

              <h4 className="text-xs sm:text-sm font-bold leading-snug" style={{ color: 'var(--text-primary)' }}>
                {source.title}
              </h4>

              {source.author && (
                <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  Authors: <span className="font-medium text-foreground">{source.author}</span>
                </p>
              )}

              <div className="pt-2 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
                <p className="text-[11px] font-bold text-indigo-400 mb-1">Abstract & Methodology:</p>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                  {source.description || 'Abstract text available on original publication site.'}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* VIEW 4: RESEARCH TIMELINE */}
        {contentType === 'timeline' && (
          <div className="h-full overflow-y-auto pr-1">
            <ResearchTimeline session={session} sessionId={sessionId} />
          </div>
        )}

        {/* VIEW 5: KNOWLEDGE GRAPH */}
        {contentType === 'graph' && (
          <div className="h-full w-full rounded-xl overflow-hidden border" style={{ borderColor: 'var(--border)' }}>
            <KnowledgeGraphCanvas graph={session.knowledgeGraph || { nodes: [], edges: [] }} session={session} />
          </div>
        )}

        {/* VIEW 6: COMPARATIVE SYNTHESIS */}
        {contentType === 'compare' && (
          <div className="h-full overflow-y-auto pr-1">
            <ComparePanel session={session} sessionId={sessionId} />
          </div>
        )}

        {/* VIEW 7: SOURCE CHAT OR GENERIC SOURCE DETAIL */}
        {(contentType === 'chat' || contentType === 'source' || contentType === 'article' || contentType === 'report') && (
          <div className="h-full flex flex-col">
            {pane.chatOpen || contentType === 'chat' ? (
              source ? (
                <ChatPanel source={source} sessionId={sessionId} fullHeight />
              ) : (
                <div className="text-center text-xs p-6 text-muted-foreground">Select a source to chat</div>
              )
            ) : source ? (
              <div className="space-y-3 overflow-y-auto pr-1">
                <div className="p-3.5 rounded-xl border space-y-2" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="font-bold text-indigo-400">{source.provider}</span>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded-full" style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}>
                      {source.relevanceScore}% Relevance
                    </span>
                  </div>

                  <h4 className="text-xs sm:text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                    {source.title}
                  </h4>

                  <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                    {source.description || 'Full source text available via external link.'}
                  </p>
                </div>

                {source.aiInsights && (
                  <AISummaryPanel insights={source.aiInsights} compact />
                )}
              </div>
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
                No source loaded
              </div>
            )}
          </div>
        )}
      </main>
    </motion.div>
  );
}
