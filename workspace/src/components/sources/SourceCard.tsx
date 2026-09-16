// src/components/sources/SourceCard.tsx
// High-craft Source Card with Persistent AI Selection Toggle, Modality Badges, and Expandable Insights

'use client';

import { useState, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Image from 'next/image';
import { useResearchStore } from '@/store/research';
import { useUIStore } from '@/store/ui';
import { SourceContextMenu } from './SourceContextMenu';
import { AISummaryPanel } from '@/components/ai/AISummaryPanel';
import { ChatPanel } from '@/components/ai/ChatPanel';
import { timeAgo } from '@/lib/utils/date';
import {
  ExternalLink, Bookmark, BookmarkCheck, Zap, MessageSquare,
  Video, BookOpen, FileText, BarChart3, Globe, ChevronDown,
  ChevronUp, ShieldCheck, Check, Plus, Sparkles
} from 'lucide-react';
import type { Source, SourceType } from '@/types/research';

const TYPE_CONFIG: Record<SourceType, { icon: React.ElementType; color: string; bg: string; label: string }> = {
  video: { icon: Video, color: '#f43f5e', bg: 'rgba(244, 63, 94, 0.15)', label: 'Video' },
  paper: { icon: BookOpen, color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.15)', label: 'Paper' },
  article: { icon: FileText, color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)', label: 'Article' },
  report: { icon: BarChart3, color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)', label: 'Report' },
  web: { icon: Globe, color: '#a855f7', bg: 'rgba(168, 85, 247, 0.15)', label: 'Web' },
};

interface SourceCardProps {
  source: Source;
  sessionId: string;
  compact?: boolean;
}

export function SourceCard({ source, sessionId, compact = false }: SourceCardProps) {
  const { toggleBookmarkSource } = useResearchStore();
  const { aiSelectedSourceIds, toggleAISelection, openSourceModal } = useUIStore();
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const typeConfig = TYPE_CONFIG[source.type] || TYPE_CONFIG.web;
  const Icon = typeConfig.icon;
  const isSelectedForAI = aiSelectedSourceIds.includes(source.id);
  const hasInsights = !!source.aiInsights;

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  };

  const qualityBadge = {
    high: { label: 'High Quality', bg: 'rgba(16, 185, 129, 0.12)', text: '#10b981', border: 'rgba(16, 185, 129, 0.25)' },
    medium: { label: 'Verified', bg: 'rgba(245, 158, 11, 0.12)', text: '#f59e0b', border: 'rgba(245, 158, 11, 0.25)' },
    low: { label: 'General', bg: 'rgba(148, 163, 184, 0.12)', text: '#94a3b8', border: 'rgba(148, 163, 184, 0.25)' },
  }[source.quality.level] || { label: 'Source', bg: 'rgba(99, 102, 241, 0.12)', text: '#6366f1', border: 'rgba(99, 102, 241, 0.25)' };

  return (
    <>
      <motion.div
        ref={cardRef}
        layout
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        onContextMenu={handleContextMenu}
        onClick={() => openSourceModal(source.id, 'details')}
        className={`group relative rounded-2xl overflow-hidden border transition-all duration-300 shadow-md cursor-pointer hover:scale-[1.01] hover:shadow-lg ${
          isSelectedForAI
            ? 'ring-2 ring-emerald-500/80 shadow-emerald-500/15'
            : 'hover:border-indigo-500/40'
        }`}
        style={{
          background: 'var(--bg-elevated)',
          borderColor: isSelectedForAI ? 'rgba(16, 185, 129, 0.5)' : 'var(--border)',
        }}
      >
        {/* Visual Thumbnail or Type Header Banner */}
        {source.thumbnail && !compact ? (
          <div className="relative w-full aspect-video overflow-hidden" style={{ position: 'relative', background: 'var(--bg-active)' }}>
            <Image
              src={source.thumbnail}
              alt={source.title}
              fill
              className="object-cover transition-transform duration-500 group-hover:scale-105"
              unoptimized
            />
            <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/30 to-transparent" />

            {/* Type badge on image */}
            <div
              className="absolute top-2.5 left-2.5 flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold backdrop-blur-md shadow-sm"
              style={{ background: typeConfig.bg, color: typeConfig.color, border: `1px solid ${typeConfig.color}40` }}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{typeConfig.label}</span>
            </div>

            {/* Use for AI toggle pill on top-right of thumbnail */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                toggleAISelection(source.id);
              }}
              className={`absolute top-2.5 right-2.5 flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold backdrop-blur-md transition-all shadow-md ${
                isSelectedForAI
                  ? 'bg-emerald-500 text-white shadow-emerald-500/30 ring-1 ring-white/30'
                  : 'bg-black/60 text-white/90 hover:bg-black/80 border border-white/20'
              }`}
              title={isSelectedForAI ? 'Selected for AI synthesis' : 'Include in AI synthesis'}
            >
              {isSelectedForAI ? (
                <>
                  <Check className="w-3 h-3 stroke-[3]" />
                  <span>Selected for AI</span>
                </>
              ) : (
                <>
                  <Plus className="w-3 h-3" />
                  <span>Use for AI</span>
                </>
              )}
            </button>

            {/* Video duration if applicable */}
            {source.duration && (
              <span className="absolute bottom-2.5 right-2.5 text-[10px] font-mono font-semibold px-2 py-0.5 rounded-md bg-black/85 text-white backdrop-blur-sm">
                {source.duration}
              </span>
            )}
          </div>
        ) : (
          <div className="px-4 pt-3 pb-2 flex items-center justify-between border-b" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-card)' }}>
            <div
              className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold"
              style={{ background: typeConfig.bg, color: typeConfig.color }}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{typeConfig.label}</span>
            </div>

            {/* Use for AI toggle for non-thumbnail cards */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                toggleAISelection(source.id);
              }}
              className={`flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold transition-all ${
                isSelectedForAI
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 shadow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] border border-[var(--border)] hover:border-indigo-500/40'
              }`}
            >
              {isSelectedForAI ? (
                <>
                  <Check className="w-3 h-3 stroke-[3]" />
                  <span>Selected for AI</span>
                </>
              ) : (
                <>
                  <Plus className="w-3 h-3" />
                  <span>Use for AI</span>
                </>
              )}
            </button>
          </div>
        )}

        {/* Card Body */}
        <div className="p-4 space-y-3">
          {/* Title and metadata */}
          <div>
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <span className="text-[11px] font-semibold truncate" style={{ color: 'var(--accent)' }}>
                {source.provider}
              </span>
              {source.date && (
                <span className="text-[11px] flex-shrink-0" style={{ color: 'var(--text-muted)' }}>
                  {timeAgo(source.date)}
                </span>
              )}
            </div>

            <h3 className="text-xs sm:text-sm font-bold leading-snug line-clamp-2 group-hover:text-indigo-400 transition-colors" style={{ color: 'var(--text-primary)' }}>
              {source.title}
            </h3>

            {source.author && (
              <p className="text-[11px] font-medium truncate mt-1" style={{ color: 'var(--text-muted)' }}>
                by {source.author}
              </p>
            )}
          </div>

          {/* Metrics / Quality Pills */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* Quality badge */}
            <div
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold"
              style={{
                background: qualityBadge.bg,
                color: qualityBadge.text,
                border: `1px solid ${qualityBadge.border}`
              }}
              title={source.quality.reason}
            >
              <ShieldCheck className="w-3 h-3" />
              <span>{qualityBadge.label}</span>
            </div>

            {/* Relevance score */}
            <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold" style={{ background: 'var(--bg-active)', color: 'var(--text-secondary)' }}>
              <span className="text-indigo-400">⚡</span>
              <span>{source.relevanceScore}% match</span>
            </div>

            {source.citationCount !== undefined && (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-mono font-medium" style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}>
                {source.citationCount} citations
              </span>
            )}
          </div>

          {/* Description Snippet */}
          {!compact && source.description && (
            <p className="text-xs font-normal leading-relaxed line-clamp-2" style={{ color: 'var(--text-secondary)' }}>
              {source.description}
            </p>
          )}

          {/* Action Toolbar */}
          <div className="flex items-center justify-between gap-1 pt-2 border-t" style={{ borderColor: 'var(--border)' }}>
            <div className="flex items-center gap-1.5">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  openSourceModal(source.id, 'insights');
                }}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-bold transition-all hover:scale-105 cursor-pointer"
                style={{
                  background: hasInsights ? 'var(--accent-ai-muted)' : 'var(--bg-active)',
                  color: hasInsights ? 'var(--accent-ai)' : 'var(--text-primary)',
                  border: hasInsights ? '1px solid rgba(168, 85, 247, 0.3)' : '1px solid var(--border)',
                }}
                title="View or Generate AI Insights"
              >
                <Zap className="w-3.5 h-3.5" />
                <span>{hasInsights ? 'AI Brief' : 'Analyze'}</span>
              </button>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  openSourceModal(source.id, 'chat');
                }}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-bold transition-all hover:bg-[var(--bg-hover)] cursor-pointer"
                style={{
                  background: 'var(--bg-card)',
                  color: 'var(--text-secondary)',
                  border: '1px solid var(--border)',
                }}
                title="Chat with AI about this source"
              >
                <MessageSquare className="w-3.5 h-3.5" />
                <span>Chat</span>
                {source.chatHistory.length > 0 && (
                  <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-indigo-500 text-white font-mono">
                    {source.chatHistory.length}
                  </span>
                )}
              </button>
            </div>

            <div className="flex items-center gap-1">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  toggleBookmarkSource(sessionId, source.id);
                }}
                className="p-2 rounded-xl transition-all hover:bg-[var(--bg-hover)]"
                style={{
                  color: source.isBookmarked ? '#f59e0b' : 'var(--text-muted)',
                  border: '1px solid var(--border)',
                }}
                aria-label="Bookmark"
                title={source.isBookmarked ? 'Bookmarked' : 'Bookmark Source'}
              >
                {source.isBookmarked ? <BookmarkCheck className="w-3.5 h-3.5 text-amber-400" /> : <Bookmark className="w-3.5 h-3.5" />}
              </button>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  openSourceModal(source.id, 'open');
                }}
                className="p-2 rounded-xl transition-all hover:bg-[var(--bg-hover)] cursor-pointer"
                style={{ color: 'var(--text-muted)', border: '1px solid var(--border)' }}
                aria-label="Open source modal"
                title="Open Source Portal"
              >
                <ExternalLink className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Floating Right-Click Menu */}
      {contextMenu && (
        <SourceContextMenu
          source={source}
          sessionId={sessionId}
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
        />
      )}
    </>
  );
}
