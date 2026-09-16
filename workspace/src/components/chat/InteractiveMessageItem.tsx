'use client';
// src/components/chat/InteractiveMessageItem.tsx
// Rich Interactive Research Chat Message Item with Action Toolbar, Inline Artifact Viewers, and Source Provenance

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  User, Bot, Copy, Check, Sparkles, Calendar, Share2, Scale,
  Flag, Link2, BookOpen, Loader2, ChevronDown, ChevronUp,
  ExternalLink, FileText, Video as VideoIcon, Music, Globe, Image as ImageIcon,
  MessageSquare, Layers, X
} from 'lucide-react';
import { toast } from 'sonner';
import MarkdownMessage from './MarkdownMessage';
import InteractiveTimelineView from '@/components/timeline/InteractiveTimelineView';
import InteractiveKnowledgeGraphView from '@/components/graph/InteractiveKnowledgeGraphView';
import SourceComparisonMatrix from '@/components/ai/SourceComparisonMatrix';
import KeyEventsViewer from '@/components/ai/KeyEventsViewer';
import CrossSourceConnections from '@/components/ai/CrossSourceConnections';
import ResearchReportModal from '@/components/report/ResearchReportModal';
import { useChatStore, ContextItem } from '@/store/chat';
import type { TimelineEvent, KnowledgeGraph, ComparisonResult, ResearchReport } from '@/types/research';

export interface InteractiveMessageProps {
  msg: {
    id: string;
    role: string;
    content: string;
    createdAt?: string;
  };
  onSendFollowup?: (question: string) => void;
  onOpenSourceModal?: (sourceId: string, timestamp?: number) => void;
}

type ActiveActionType = 'none' | 'followup' | 'sources' | 'timeline' | 'graph' | 'events' | 'compare' | 'connections' | 'report';

export default function InteractiveMessageItem({ msg, onSendFollowup, onOpenSourceModal }: InteractiveMessageProps) {
  const isUser = msg.role === 'user';
  const { activeContext } = useChatStore();
  const [copied, setCopied] = useState(false);
  const [activeAction, setActiveAction] = useState<ActiveActionType>('none');
  const [actionLoading, setActionLoading] = useState(false);

  // Cached Artifact Data
  const [timelineEvents, setTimelineEvents] = useState<TimelineEvent[] | null>(null);
  const [knowledgeGraph, setKnowledgeGraph] = useState<KnowledgeGraph | null>(null);
  const [comparisonResult, setComparisonResult] = useState<ComparisonResult | null>(null);
  const [keyEvents, setKeyEvents] = useState<any[] | null>(null);
  const [connectionsData, setConnectionsData] = useState<{ connections: any[]; crossSynthesis?: string } | null>(null);
  const [reportData, setReportData] = useState<ResearchReport | null>(null);
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);

  // Default suggested follow-ups
  const defaultFollowups = [
    'What are the key pieces of evidence supporting this?',
    'What are the primary contradictions or counter-arguments?',
    'How do the local document findings correlate with live news reports?',
    'What are the chronological next steps or policy outcomes?',
  ];

  const handleCopy = () => {
    const clean = msg.content.replace(/<think>[\s\S]*?<\/think>/gi, '').trim() || msg.content;
    navigator.clipboard.writeText(clean);
    setCopied(true);
    toast.success('Message copied');
    setTimeout(() => setCopied(false), 2000);
  };

  const handleTriggerAction = async (action: ActiveActionType) => {
    if (activeAction === action) {
      setActiveAction('none');
      return;
    }

    if (action === 'followup' || action === 'sources') {
      setActiveAction(action);
      return;
    }

    if (activeContext.length === 0) {
      toast.error('No sources in context. Please add or retrieve sources first.');
      return;
    }

    setActiveAction(action);

    // If data is already cached, no need to re-fetch
    if (action === 'timeline' && timelineEvents) return;
    if (action === 'graph' && knowledgeGraph) return;
    if (action === 'compare' && comparisonResult) return;
    if (action === 'events' && keyEvents) return;
    if (action === 'connections' && connectionsData) return;
    if (action === 'report' && reportData) {
      setIsReportModalOpen(true);
      return;
    }

    setActionLoading(true);
    try {
      const topic = msg.content.slice(0, 100).replace(/[^a-zA-Z0-9\s]/g, ' ').trim() || 'Research Topic';

      const res = await fetch('/api/chat/actions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          topic,
          contextItems: activeContext,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.message || err.error || 'Action failed');
      }

      const data = await res.json();

      if (action === 'timeline') {
        setTimelineEvents(data.data?.events || []);
        toast.success('Timeline generated!');
      } else if (action === 'graph') {
        setKnowledgeGraph(data.data || { nodes: [], edges: [] });
        toast.success('Knowledge Graph mapped!');
      } else if (action === 'compare') {
        setComparisonResult(data.data);
        toast.success('Source Comparison matrix ready!');
      } else if (action === 'events') {
        setKeyEvents(data.data?.events || []);
        toast.success('Key Events extracted!');
      } else if (action === 'connections') {
        setConnectionsData(data.data);
        toast.success('Cross-source Connections identified!');
      } else if (action === 'report') {
        setReportData(data.data);
        setIsReportModalOpen(true);
        toast.success('Research Report compiled!');
      }
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Action failed';
      toast.error(errorMsg);
      setActiveAction('none');
    } finally {
      setActionLoading(false);
    }
  };

  const getSourceIcon = (type: string) => {
    switch (type) {
      case 'video': return VideoIcon;
      case 'audio': return Music;
      case 'image': return ImageIcon;
      case 'web': return Globe;
      default: return FileText;
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', bounce: 0.2 }}
      className={`flex gap-3 group ${isUser ? 'flex-row-reverse' : 'flex-row'}`}
    >
      {/* Avatar */}
      <div
        className={`w-9 h-9 rounded-2xl flex-shrink-0 flex items-center justify-center shadow-md ${
          isUser ? 'self-end' : 'self-start mt-1'
        }`}
        style={{
          background: isUser
            ? 'linear-gradient(135deg, #6366f1, #8b5cf6)'
            : 'linear-gradient(135deg, #06b6d4 0%, #6366f1 100%)',
        }}
      >
        {isUser ? (
          <User className="w-4 h-4 text-white" />
        ) : (
          <Bot className="w-4 h-4 text-white" />
        )}
      </div>

      {/* Message Container */}
      <div className={`max-w-[92%] sm:max-w-[85%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-2`}>
        {/* Bubble */}
        <div
          className="px-5 py-4 rounded-3xl text-sm leading-relaxed relative shadow-md"
          style={{
            background: isUser
              ? 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)'
              : 'var(--bg-elevated)',
            color: isUser ? '#fff' : 'var(--text-primary)',
            border: isUser ? 'none' : '1px solid var(--border)',
            borderBottomRightRadius: isUser ? '4px' : '24px',
            borderBottomLeftRadius: isUser ? '24px' : '4px',
          }}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{msg.content}</p>
          ) : (
            <div className="space-y-3">
              <MarkdownMessage content={msg.content} />

              {/* Context Source Badges (Shown when assistant used sources) */}
              {activeContext.length > 0 && (
                <div className="pt-3 border-t border-[var(--border)] flex flex-wrap items-center gap-1.5">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400 mr-1 flex items-center gap-1">
                    <Layers className="w-3 h-3 text-cyan-400" />
                    <span>Citations:</span>
                  </span>
                  {activeContext.slice(0, 4).map((item) => {
                    const Icon = getSourceIcon(item.type);
                    const sourceId = (item.metadata?.sourceId as string) || (item.type !== 'web' ? item.id : undefined);
                    const timestamp = item.metadata?.timestamp as number | undefined;
                    const pageNum = item.metadata?.pageNum as number | undefined;

                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => sourceId && onOpenSourceModal?.(sourceId, timestamp)}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-[11px] font-semibold transition-all hover:scale-105"
                        style={{
                          background: 'var(--bg-base)',
                          border: '1px solid var(--border)',
                          color: 'var(--text-secondary)',
                        }}
                        title={`Open source: ${item.title}`}
                      >
                        <Icon className="w-3 h-3 text-cyan-400" />
                        <span className="truncate max-w-[140px]">{item.title}</span>
                        {pageNum && <span className="text-[10px] text-indigo-400">p.{pageNum}</span>}
                        {timestamp !== undefined && (
                          <span className="text-[10px] text-rose-400">
                            {Math.floor(timestamp / 60)}:{(timestamp % 60).toString().padStart(2, '0')}
                          </span>
                        )}
                        <ExternalLink className="w-2.5 h-2.5 opacity-60" />
                      </button>
                    );
                  })}
                  {activeContext.length > 4 && (
                    <button
                      type="button"
                      onClick={() => handleTriggerAction('sources')}
                      className="text-[10px] font-bold text-cyan-400 hover:underline px-1.5"
                    >
                      +{activeContext.length - 4} more
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ═══════════════════════════════════════════════════════════════
            RESEARCH INTERACTIVE ACTIONS TOOLBAR (FOR ASSISTANT)
           ═══════════════════════════════════════════════════════════════ */}
        {!isUser && (
          <div className="w-full space-y-3">
            {/* Action Buttons Row */}
            <div className="flex flex-wrap items-center gap-1.5 px-1 text-xs">
              {/* Follow-up */}
              <button
                type="button"
                onClick={() => handleTriggerAction('followup')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-semibold transition-all ${
                  activeAction === 'followup'
                    ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40 shadow-sm'
                    : 'hover:bg-[var(--bg-elevated)] border border-transparent hover:border-[var(--border)] text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <MessageSquare className="w-3.5 h-3.5 text-cyan-400" />
                <span>Follow-up</span>
              </button>

              {/* View Sources */}
              <button
                type="button"
                onClick={() => handleTriggerAction('sources')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-semibold transition-all ${
                  activeAction === 'sources'
                    ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/40 shadow-sm'
                    : 'hover:bg-[var(--bg-elevated)] border border-transparent hover:border-[var(--border)] text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <Layers className="w-3.5 h-3.5 text-indigo-400" />
                <span>Sources ({activeContext.length})</span>
              </button>

              {/* Timeline */}
              <button
                type="button"
                onClick={() => handleTriggerAction('timeline')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-semibold transition-all ${
                  activeAction === 'timeline'
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 shadow-sm'
                    : 'hover:bg-[var(--bg-elevated)] border border-transparent hover:border-[var(--border)] text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <Calendar className="w-3.5 h-3.5 text-emerald-400" />
                <span>Timeline</span>
              </button>

              {/* Knowledge Graph */}
              <button
                type="button"
                onClick={() => handleTriggerAction('graph')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-semibold transition-all ${
                  activeAction === 'graph'
                    ? 'bg-purple-500/20 text-purple-400 border border-purple-500/40 shadow-sm'
                    : 'hover:bg-[var(--bg-elevated)] border border-transparent hover:border-[var(--border)] text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <Share2 className="w-3.5 h-3.5 text-purple-400" />
                <span>Knowledge Graph</span>
              </button>

              {/* Key Events */}
              <button
                type="button"
                onClick={() => handleTriggerAction('events')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-semibold transition-all ${
                  activeAction === 'events'
                    ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40 shadow-sm'
                    : 'hover:bg-[var(--bg-elevated)] border border-transparent hover:border-[var(--border)] text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <Flag className="w-3.5 h-3.5 text-rose-400" />
                <span>Key Events</span>
              </button>

              {/* Compare Sources */}
              <button
                type="button"
                onClick={() => handleTriggerAction('compare')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-semibold transition-all ${
                  activeAction === 'compare'
                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40 shadow-sm'
                    : 'hover:bg-[var(--bg-elevated)] border border-transparent hover:border-[var(--border)] text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <Scale className="w-3.5 h-3.5 text-amber-400" />
                <span>Compare Sources</span>
              </button>

              {/* Connections */}
              <button
                type="button"
                onClick={() => handleTriggerAction('connections')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-semibold transition-all ${
                  activeAction === 'connections'
                    ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40 shadow-sm'
                    : 'hover:bg-[var(--bg-elevated)] border border-transparent hover:border-[var(--border)] text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <Link2 className="w-3.5 h-3.5 text-cyan-400" />
                <span>Connections</span>
              </button>

              {/* Generate Report */}
              <button
                type="button"
                onClick={() => handleTriggerAction('report')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-bold bg-gradient-to-r from-indigo-500/20 to-cyan-500/20 text-indigo-300 border border-indigo-500/30 hover:scale-105 transition-all shadow-sm"
              >
                <BookOpen className="w-3.5 h-3.5 text-indigo-400" />
                <span>Create Report</span>
              </button>

              {/* Copy Message */}
              <button
                type="button"
                onClick={handleCopy}
                className="p-1.5 rounded-xl text-zinc-400 hover:text-zinc-200 hover:bg-[var(--bg-elevated)] transition-colors ml-auto"
                title="Copy response"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>

            {/* ═══════════════════════════════════════════════════════════════
                INLINE DYNAMIC ARTIFACT CONTAINER
               ═══════════════════════════════════════════════════════════════ */}
            <AnimatePresence>
              {activeAction !== 'none' && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden space-y-3"
                >
                  {/* Action Loading State */}
                  {actionLoading ? (
                    <div className="p-8 rounded-3xl bg-[var(--bg-elevated)] border border-[var(--border)] flex flex-col items-center justify-center gap-3 text-center">
                      <Loader2 className="w-8 h-8 animate-spin text-cyan-400" />
                      <p className="text-xs font-semibold text-zinc-200">
                        Synthesizing intelligence across selected sources...
                      </p>
                    </div>
                  ) : (
                    <>
                      {/* 1. Follow-up suggestions */}
                      {activeAction === 'followup' && (
                        <div className="p-4 rounded-2xl bg-[var(--bg-elevated)] border border-[var(--border)] space-y-2">
                          <div className="flex items-center justify-between text-xs font-bold text-cyan-400">
                            <span className="flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5" /> Suggested Research Follow-ups</span>
                            <button onClick={() => setActiveAction('none')} className="text-zinc-400 hover:text-zinc-200"><X className="w-3.5 h-3.5" /></button>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {defaultFollowups.map((q, idx) => (
                              <button
                                key={idx}
                                type="button"
                                onClick={() => {
                                  onSendFollowup?.(q);
                                  setActiveAction('none');
                                }}
                                className="text-left text-xs px-3 py-1.5 rounded-xl bg-[var(--bg-base)] border border-[var(--border)] text-zinc-300 hover:text-white hover:border-cyan-500/40 hover:scale-[1.01] transition-all"
                              >
                                {q}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* 2. Sources Inspector */}
                      {activeAction === 'sources' && (
                        <div className="p-4 rounded-2xl bg-[var(--bg-elevated)] border border-[var(--border)] space-y-3">
                          <div className="flex items-center justify-between text-xs font-bold text-indigo-400">
                            <span className="flex items-center gap-1.5"><Layers className="w-3.5 h-3.5" /> Active Retrieved Sources ({activeContext.length})</span>
                            <button onClick={() => setActiveAction('none')} className="text-zinc-400 hover:text-zinc-200"><X className="w-3.5 h-3.5" /></button>
                          </div>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                            {activeContext.map((item) => {
                              const Icon = getSourceIcon(item.type);
                              const sourceId = (item.metadata?.sourceId as string) || (item.type !== 'web' ? item.id : undefined);
                              const timestamp = item.metadata?.timestamp as number | undefined;

                              return (
                                <div
                                  key={item.id}
                                  onClick={() => sourceId && onOpenSourceModal?.(sourceId, timestamp)}
                                  className="p-3 rounded-xl bg-[var(--bg-base)] border border-[var(--border)] space-y-1.5 cursor-pointer hover:border-indigo-500/40 transition-all"
                                >
                                  <div className="flex items-center justify-between gap-2">
                                    <div className="flex items-center gap-1.5 min-w-0">
                                      <Icon className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
                                      <span className="text-xs font-bold truncate text-zinc-200">{item.title}</span>
                                    </div>
                                    <ExternalLink className="w-3 h-3 text-zinc-400" />
                                  </div>
                                  {item.snippet && (
                                    <p className="text-[11px] text-zinc-400 line-clamp-2 leading-relaxed">
                                      {item.snippet}
                                    </p>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* 3. Timeline */}
                      {activeAction === 'timeline' && timelineEvents && (
                        <InteractiveTimelineView
                          events={timelineEvents}
                          onOpenSource={(sid) => onOpenSourceModal?.(sid)}
                        />
                      )}

                      {/* 4. Knowledge Graph */}
                      {activeAction === 'graph' && knowledgeGraph && (
                        <InteractiveKnowledgeGraphView
                          graph={knowledgeGraph}
                          topic={msg.content.slice(0, 60)}
                          onOpenSource={(sid) => onOpenSourceModal?.(sid)}
                        />
                      )}

                      {/* 5. Key Events */}
                      {activeAction === 'events' && keyEvents && (
                        <KeyEventsViewer
                          events={keyEvents}
                          onOpenSource={(sid) => onOpenSourceModal?.(sid)}
                        />
                      )}

                      {/* 6. Compare Sources */}
                      {activeAction === 'compare' && comparisonResult && (
                        <SourceComparisonMatrix
                          comparison={comparisonResult}
                          onOpenSource={(sid) => onOpenSourceModal?.(sid)}
                        />
                      )}

                      {/* 7. Cross-Source Connections */}
                      {activeAction === 'connections' && connectionsData && (
                        <CrossSourceConnections
                          connections={connectionsData.connections}
                          crossSynthesis={connectionsData.crossSynthesis}
                          onOpenSource={(sid) => onOpenSourceModal?.(sid)}
                        />
                      )}
                    </>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>

      {/* Report Modal */}
      <ResearchReportModal
        report={reportData}
        isOpen={isReportModalOpen}
        onClose={() => setIsReportModalOpen(false)}
        onOpenSource={(sid) => onOpenSourceModal?.(sid)}
      />
    </motion.div>
  );
}
