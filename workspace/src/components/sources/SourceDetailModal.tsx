// src/components/sources/SourceDetailModal.tsx
// Comprehensive Multi-Tab Source Detail & AI Intelligence Modal (Details, AI Chat, AI Insights, Open Source)

'use client';

import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Image from 'next/image';
import { useResearchStore } from '@/store/research';
import { useUIStore } from '@/store/ui';
import { AISummaryPanel } from '@/components/ai/AISummaryPanel';
import { ChatPanel } from '@/components/ai/ChatPanel';
import { timeAgo, formatDate } from '@/lib/utils/date';
import { toast } from 'sonner';
import {
  X,
  FileText,
  MessageSquare,
  Sparkles,
  ExternalLink,
  Video,
  BookOpen,
  BarChart3,
  Globe,
  ShieldCheck,
  Bookmark,
  BookmarkCheck,
  Check,
  Plus,
  Zap,
  Copy,
  Calendar,
  Link as LinkIcon,
} from 'lucide-react';
import type { Source, SourceType } from '@/types/research';

const TYPE_CONFIG: Record<
  SourceType,
  { icon: React.ElementType; color: string; bg: string; label: string }
> = {
  video: { icon: Video, color: '#f43f5e', bg: 'rgba(244, 63, 94, 0.15)', label: 'Video Lecture' },
  paper: { icon: BookOpen, color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.15)', label: 'Academic Paper' },
  article: { icon: FileText, color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)', label: 'News & Article' },
  report: { icon: BarChart3, color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)', label: 'Policy Report' },
  web: { icon: Globe, color: '#a855f7', bg: 'rgba(168, 85, 247, 0.15)', label: 'Web Reference' },
};

type ModalTab = 'details' | 'chat' | 'insights' | 'open';

interface SourceDetailModalProps {
  sessionId: string;
}

export function SourceDetailModal({ sessionId }: SourceDetailModalProps) {
  const { sessions, setAIInsights, toggleBookmarkSource } = useResearchStore();
  const {
    activeSourceModalId,
    activeSourceModalTab,
    setSourceModalTab,
    closeSourceModal,
    aiSelectedSourceIds,
    toggleAISelection,
  } = useUIStore();

  const [isSummarizing, setIsSummarizing] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);

  const session = sessions.find((s) => s.id === sessionId);
  const source = session?.sources.find((s) => s.id === activeSourceModalId);

  // Keyboard Escape listener
  useEffect(() => {
    if (!activeSourceModalId) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeSourceModal();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeSourceModalId, closeSourceModal]);

  if (!source) return null;

  const typeConfig = TYPE_CONFIG[source.type] || TYPE_CONFIG.web;
  const Icon = typeConfig.icon;
  const isSelectedForAI = aiSelectedSourceIds.includes(source.id);
  const hasInsights = !!source.aiInsights;

  const handleGenerateInsights = async () => {
    if (hasInsights) {
      setSourceModalTab('insights');
      return;
    }
    setIsSummarizing(true);
    try {
      toast.loading('Synthesizing source with Groq Qwen 3.6...', { id: 'modal-summarize' });
      const res = await fetch('/api/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source }),
      });
      if (!res.ok) throw new Error('AI summary generation failed');
      const { insights } = await res.json();
      setAIInsights(sessionId, source.id, insights);
      toast.success('AI Insights generated successfully!', { id: 'modal-summarize' });
      setSourceModalTab('insights');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to generate insights';
      toast.error(msg, { id: 'modal-summarize' });
    } finally {
      setIsSummarizing(false);
    }
  };

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(source.url);
      setCopiedLink(true);
      toast.success('Source URL copied to clipboard');
      setTimeout(() => setCopiedLink(false), 2000);
    } catch {
      toast.error('Failed to copy URL');
    }
  };

  const tabs: Array<{ id: ModalTab; label: string; icon: React.ElementType; badge?: string | number }> = [
    { id: 'details', label: 'Source Details', icon: FileText },
    {
      id: 'chat',
      label: 'AI Chat',
      icon: MessageSquare,
      badge: source.chatHistory.length > 0 ? source.chatHistory.length : undefined,
    },
    {
      id: 'insights',
      label: 'AI Insights',
      icon: Sparkles,
      badge: hasInsights ? 'Synthesized' : undefined,
    },
    { id: 'open', label: 'Open Source', icon: ExternalLink },
  ];

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 overflow-hidden">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={closeSourceModal}
          className="absolute inset-0 bg-black/75 backdrop-blur-md"
        />

        {/* Modal Window Container */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 15 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 15 }}
          transition={{ type: 'spring', bounce: 0.15, duration: 0.3 }}
          className="relative w-full max-w-4xl max-h-[90vh] flex flex-col rounded-3xl border shadow-2xl overflow-hidden z-10"
          style={{
            background: 'var(--bg-elevated)',
            borderColor: 'var(--border)',
            boxShadow: `0 20px 50px rgba(0, 0, 0, 0.5), 0 0 40px ${typeConfig.color}15`,
          }}
        >
          {/* Modal Header */}
          <div
            className="flex items-start justify-between gap-3 p-5 sm:p-6 border-b"
            style={{
              background: 'var(--bg-card)',
              borderColor: 'var(--border)',
            }}
          >
            <div className="space-y-1.5 flex-1 min-w-0 pr-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold"
                  style={{ background: typeConfig.bg, color: typeConfig.color }}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{typeConfig.label}</span>
                </span>

                <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-[var(--bg-active)] text-[var(--accent)]">
                  {source.provider}
                </span>

                {source.date && (
                  <span className="text-xs text-muted-foreground flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    <span>{formatDate(source.date)}</span>
                  </span>
                )}
              </div>

              <h2
                className="text-base sm:text-lg font-bold leading-snug line-clamp-2"
                style={{ color: 'var(--text-primary)' }}
                title={source.title}
              >
                {source.title}
              </h2>
            </div>

            {/* Top Right Action Tools */}
            <div className="flex items-center gap-2 flex-shrink-0">
              {/* Use for AI Toggle */}
              <button
                onClick={() => toggleAISelection(source.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition-all shadow-sm ${
                  isSelectedForAI
                    ? 'bg-emerald-500 text-white shadow-emerald-500/25'
                    : 'bg-[var(--bg-active)] text-[var(--text-secondary)] hover:text-white border border-[var(--border)]'
                }`}
                title={isSelectedForAI ? 'Included in AI synthesis' : 'Include in AI synthesis'}
              >
                {isSelectedForAI ? (
                  <>
                    <Check className="w-3.5 h-3.5 stroke-[3]" />
                    <span>Selected for AI</span>
                  </>
                ) : (
                  <>
                    <Plus className="w-3.5 h-3.5" />
                    <span>Use for AI</span>
                  </>
                )}
              </button>

              {/* Bookmark */}
              <button
                onClick={() => toggleBookmarkSource(sessionId, source.id)}
                className="p-2 rounded-xl border transition-all hover:bg-[var(--bg-hover)]"
                style={{
                  borderColor: 'var(--border)',
                  color: source.isBookmarked ? '#f59e0b' : 'var(--text-muted)',
                }}
                title={source.isBookmarked ? 'Bookmarked' : 'Bookmark Source'}
              >
                {source.isBookmarked ? (
                  <BookmarkCheck className="w-4 h-4 text-amber-400" />
                ) : (
                  <Bookmark className="w-4 h-4" />
                )}
              </button>

              {/* Close Button */}
              <button
                onClick={closeSourceModal}
                className="p-2 rounded-xl border text-[var(--text-muted)] hover:text-foreground hover:bg-[var(--bg-hover)] transition-all"
                style={{ borderColor: 'var(--border)' }}
                title="Close (Esc)"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* 4 Feature Tabs Bar */}
          <div
            className="flex items-center px-4 sm:px-6 border-b overflow-x-auto no-scrollbar"
            style={{
              background: 'var(--bg-elevated)',
              borderColor: 'var(--border)',
            }}
          >
            {tabs.map((tab) => {
              const isActive = activeSourceModalTab === tab.id;
              const TabIcon = tab.icon;

              return (
                <button
                  key={tab.id}
                  onClick={() => setSourceModalTab(tab.id)}
                  className={`relative flex items-center gap-2 px-4 py-3 text-xs sm:text-sm font-bold transition-all whitespace-nowrap ${
                    isActive
                      ? 'text-indigo-400'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  <TabIcon className="w-4 h-4" />
                  <span>{tab.label}</span>

                  {tab.badge !== undefined && (
                    <span
                      className={`text-[10px] font-mono px-2 py-0.5 rounded-full font-bold ${
                        isActive
                          ? 'bg-indigo-500/20 text-indigo-400'
                          : 'bg-[var(--bg-active)] text-muted-foreground'
                      }`}
                    >
                      {tab.badge}
                    </span>
                  )}

                  {isActive && (
                    <motion.div
                      layoutId="source-modal-tab-indicator"
                      className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full"
                      style={{
                        background: 'linear-gradient(90deg, #6366f1 0%, #a855f7 100%)',
                      }}
                      transition={{ type: 'spring', bounce: 0.15, duration: 0.3 }}
                    />
                  )}
                </button>
              );
            })}
          </div>

          {/* Modal Tab Body */}
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 min-h-[350px]">
            {/* TAB 1: SOURCE DETAILS */}
            {activeSourceModalTab === 'details' && (
              <div className="space-y-6">
                {/* Visual Media Header Preview if available */}
                {source.thumbnail && (
                  <div
                    className="relative w-full aspect-video sm:aspect-[21/9] rounded-2xl overflow-hidden border shadow-md"
                    style={{ borderColor: 'var(--border)', background: 'var(--bg-active)' }}
                  >
                    <Image
                      src={source.thumbnail}
                      alt={source.title}
                      fill
                      className="object-cover"
                      unoptimized
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/30 to-transparent flex items-end p-4">
                      <div className="text-white space-y-1">
                        <div className="flex items-center gap-2 text-xs font-semibold text-white/80">
                          <span>{source.provider}</span>
                          {source.channel && <span>• {source.channel}</span>}
                          {source.duration && (
                            <span className="px-2 py-0.5 rounded bg-black/80 font-mono text-[11px] font-bold">
                              ⏱️ {source.duration}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Key Metrics & Diagnostics Row */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div
                    className="p-3.5 rounded-2xl border space-y-1"
                    style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
                  >
                    <span className="text-[11px] font-medium text-muted-foreground">Match Score</span>
                    <p className="text-base sm:text-lg font-mono font-bold text-indigo-400">
                      ⚡ {source.relevanceScore}%
                    </p>
                  </div>

                  <div
                    className="p-3.5 rounded-2xl border space-y-1"
                    style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
                  >
                    <span className="text-[11px] font-medium text-muted-foreground">Quality Rating</span>
                    <p className="text-xs sm:text-sm font-bold text-emerald-400 flex items-center gap-1">
                      <ShieldCheck className="w-3.5 h-3.5" />
                      <span className="capitalize">{source.quality.level} Quality</span>
                    </p>
                  </div>

                  <div
                    className="p-3.5 rounded-2xl border space-y-1"
                    style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
                  >
                    <span className="text-[11px] font-medium text-muted-foreground">Author / Origin</span>
                    <p className="text-xs sm:text-sm font-bold truncate" style={{ color: 'var(--text-primary)' }}>
                      {source.author || source.provider}
                    </p>
                  </div>

                  <div
                    className="p-3.5 rounded-2xl border space-y-1"
                    style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
                  >
                    <span className="text-[11px] font-medium text-muted-foreground">Publication Date</span>
                    <p className="text-xs sm:text-sm font-mono font-semibold" style={{ color: 'var(--text-secondary)' }}>
                      {source.date ? timeAgo(source.date) : 'Recent publication'}
                    </p>
                  </div>
                </div>

                {/* Specific Attribute Details */}
                <div
                  className="p-5 rounded-2xl border space-y-3"
                  style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
                >
                  <h3 className="text-xs sm:text-sm font-bold uppercase tracking-wider text-indigo-400">
                    Source Overview & Content
                  </h3>

                  <p className="text-xs sm:text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                    {source.description || source.abstract || 'Detailed source text is accessible through original link.'}
                  </p>

                  {/* Type Specific Additions */}
                  {source.type === 'paper' && (
                    <div className="pt-3 border-t border-[var(--border-subtle)] space-y-2 text-xs">
                      {source.journal && (
                        <p style={{ color: 'var(--text-muted)' }}>
                          <span className="font-semibold text-foreground">Academic Venue:</span> {source.journal}
                        </p>
                      )}
                      {source.doi && (
                        <p style={{ color: 'var(--text-muted)' }}>
                          <span className="font-semibold text-foreground">DOI Reference:</span> {source.doi}
                        </p>
                      )}
                      {source.citationCount !== undefined && (
                        <p style={{ color: 'var(--text-muted)' }}>
                          <span className="font-semibold text-foreground">Citations Index:</span> {source.citationCount} recorded citations
                        </p>
                      )}
                    </div>
                  )}

                  {source.type === 'video' && source.viewCount !== undefined && source.viewCount > 0 && (
                    <div className="pt-2 border-t border-[var(--border-subtle)] text-xs text-muted-foreground">
                      <span className="font-semibold text-foreground">Verified Viewership:</span> {source.viewCount.toLocaleString()} views on YouTube
                    </div>
                  )}
                </div>

                {/* Quick Interactive Actions Row */}
                <div className="flex items-center gap-3 flex-wrap pt-2">
                  <button
                    onClick={() => setSourceModalTab('chat')}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold text-white shadow-md shadow-indigo-500/20 hover:scale-105 transition-all"
                    style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }}
                  >
                    <MessageSquare className="w-4 h-4" />
                    <span>Deep-Dive AI Chat</span>
                  </button>

                  <button
                    onClick={handleGenerateInsights}
                    disabled={isSummarizing}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all border hover:scale-105"
                    style={{
                      background: hasInsights ? 'var(--accent-ai-muted)' : 'var(--bg-card)',
                      borderColor: hasInsights ? 'rgba(168, 85, 247, 0.4)' : 'var(--border)',
                      color: hasInsights ? 'var(--accent-ai)' : 'var(--text-primary)',
                    }}
                  >
                    {isSummarizing ? (
                      <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Sparkles className="w-4 h-4 text-purple-400" />
                    )}
                    <span>{hasInsights ? 'View AI Insights' : 'Generate AI Insights'}</span>
                  </button>

                  <button
                    onClick={() => setSourceModalTab('open')}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold border transition-all hover:bg-[var(--bg-hover)]"
                    style={{
                      background: 'var(--bg-card)',
                      borderColor: 'var(--border)',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    <ExternalLink className="w-4 h-4" />
                    <span>Open Original Source</span>
                  </button>
                </div>
              </div>
            )}

            {/* TAB 2: AI CHAT */}
            {activeSourceModalTab === 'chat' && (
              <div className="h-full flex flex-col min-h-[420px]">
                <ChatPanel source={source} sessionId={sessionId} fullHeight />
              </div>
            )}

            {/* TAB 3: AI INSIGHTS */}
            {activeSourceModalTab === 'insights' && (
              <div className="space-y-4">
                {source.aiInsights ? (
                  <AISummaryPanel insights={source.aiInsights} />
                ) : (
                  <div
                    className="p-8 rounded-2xl border text-center space-y-4 max-w-md mx-auto my-6"
                    style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
                  >
                    <div className="w-12 h-12 rounded-2xl bg-purple-500/15 text-purple-400 flex items-center justify-center mx-auto">
                      <Sparkles className="w-6 h-6" />
                    </div>
                    <div>
                      <h4 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>
                        No AI Insights Generated Yet
                      </h4>
                      <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                        Extract executive synthesis, core arguments, key facts, statistics, and entities using Qwen 3.6 on Groq.
                      </p>
                    </div>

                    <button
                      onClick={handleGenerateInsights}
                      disabled={isSummarizing}
                      className="px-5 py-2.5 rounded-xl text-xs font-bold text-white shadow-lg shadow-purple-500/25 hover:scale-105 active:scale-95 transition-all cursor-pointer"
                      style={{ background: 'linear-gradient(135deg, #a855f7 0%, #6366f1 100%)' }}
                    >
                      {isSummarizing ? (
                        <div className="flex items-center gap-2">
                          <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                          <span>Synthesizing Source...</span>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <Zap className="w-4 h-4" />
                          <span>Generate Deep AI Insights</span>
                        </div>
                      )}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* TAB 4: OPEN SOURCE */}
            {activeSourceModalTab === 'open' && (
              <div className="space-y-6">
                {/* External Link Portal Card */}
                <div
                  className="p-6 rounded-3xl border text-center space-y-5"
                  style={{
                    background: 'var(--bg-card)',
                    borderColor: 'var(--border)',
                  }}
                >
                  <div className="w-14 h-14 rounded-2xl bg-indigo-500/15 text-indigo-400 flex items-center justify-center mx-auto">
                    <ExternalLink className="w-7 h-7" />
                  </div>

                  <div className="max-w-md mx-auto space-y-1.5">
                    <h3 className="text-base sm:text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
                      Access Original Verification Link
                    </h3>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      Visit the direct publisher portal to inspect complete original manuscripts, full video transcripts, or primary datasets.
                    </p>
                  </div>

                  {/* URL Address Bar */}
                  <div
                    className="flex items-center justify-between gap-2 p-2.5 rounded-xl border max-w-xl mx-auto"
                    style={{ background: 'var(--bg-base)', borderColor: 'var(--border)' }}
                  >
                    <div className="flex items-center gap-2 flex-1 min-w-0 px-1">
                      <LinkIcon className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
                      <span className="text-xs font-mono truncate select-all" style={{ color: 'var(--text-secondary)' }}>
                        {source.url}
                      </span>
                    </div>

                    <button
                      onClick={handleCopyLink}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors hover:bg-[var(--bg-hover)] flex-shrink-0"
                      style={{
                        borderColor: 'var(--border)',
                        color: copiedLink ? '#10b981' : 'var(--text-primary)',
                      }}
                      title="Copy URL"
                    >
                      {copiedLink ? (
                        <>
                          <Check className="w-3 h-3 text-emerald-400 stroke-[3]" />
                          <span className="text-emerald-400 font-bold">Copied</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3 h-3" />
                          <span>Copy URL</span>
                        </>
                      )}
                    </button>
                  </div>

                  {/* Big Primary Open Button */}
                  <div className="pt-2">
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-2.5 px-6 py-3 rounded-2xl text-xs sm:text-sm font-bold text-white shadow-xl shadow-indigo-500/25 hover:scale-105 active:scale-95 transition-all"
                      style={{
                        background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
                      }}
                    >
                      <span>Open in New Browser Tab</span>
                      <ExternalLink className="w-4 h-4" />
                    </a>
                  </div>
                </div>

                {/* Source Verification Matrix */}
                <div
                  className="p-4 rounded-2xl border space-y-2 text-xs"
                  style={{ background: 'var(--bg-base)', borderColor: 'var(--border)' }}
                >
                  <div className="flex items-center gap-2 font-bold text-emerald-400">
                    <ShieldCheck className="w-4 h-4" />
                    <span>Verified Authenticity & Provider Link</span>
                  </div>
                  <p className="text-muted-foreground leading-relaxed">
                    This source was discovered via <span className="font-semibold text-foreground">{source.provider}</span>. All content is directly indexed from live web endpoints and peer-reviewed academic feeds.
                  </p>
                </div>
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
