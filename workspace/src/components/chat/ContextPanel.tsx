'use client';
// src/components/chat/ContextPanel.tsx — Sources sidebar for Smart Search review, inspection, and active context persistence

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Database, FileText, Video, Image as ImageIcon, Globe, X, Trash2,
  ChevronRight, ChevronLeft, Info, Sparkles, Eye, CheckCircle2,
  Search, Tag, Loader2, ArrowRight, ExternalLink
} from 'lucide-react';
import { useChatStore, ContextItem } from '@/store/chat';
import DocumentMetadataModal from '@/components/modals/DocumentMetadataModal';

interface ExtractedSearchInfo {
  searchQuery?: string;
  keywords?: string[];
  searchTerms?: string[];
  intent?: string;
}

interface ContextPanelProps {
  isOpen: boolean;
  onToggle: () => void;
  isReviewMode?: boolean;
  extractedInfo?: ExtractedSearchInfo | null;
  onGenerateAnswer?: () => void;
  isGeneratingAnswer?: boolean;
}

const TYPE_ICONS: Record<string, typeof FileText> = {
  document: FileText,
  video: Video,
  image: ImageIcon,
  web: Globe,
};

export function ContextPanel({
  isOpen,
  onToggle,
  isReviewMode = false,
  extractedInfo = null,
  onGenerateAnswer,
  isGeneratingAnswer = false,
}: ContextPanelProps) {
  const { activeChatId, activeContext, removeContextItem, clearContext } = useChatStore();
  const [inspectSourceId, setInspectSourceId] = useState<string | null>(null);
  const [showQueryDetails, setShowQueryDetails] = useState(true);

  const handleRemoveSource = async (itemId: string, sourceId?: string) => {
    removeContextItem(itemId);
    // Also delete from backend chat_context if chat is active
    if (activeChatId) {
      try {
        await fetch(`/api/chats/${activeChatId}/context/${itemId}`, { method: 'DELETE' });
      } catch {
        // silent fallback
      }
    }
  };

  const handleClearAll = async () => {
    clearContext();
    if (activeChatId) {
      try {
        await fetch(`/api/chats/${activeChatId}/context`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ contextItems: [] }),
        });
      } catch {
        // silent fallback
      }
    }
  };

  return (
    <>
      <div className="relative flex h-full">
        {/* Drawer Toggle Button */}
        <button
          onClick={onToggle}
          className="absolute -left-3.5 top-6 z-20 p-1.5 rounded-full shadow-lg transition-all hover:scale-105"
          style={{
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            color: 'var(--text-secondary)',
          }}
          title={isOpen ? 'Hide sources sidebar' : 'Show sources sidebar'}
        >
          {isOpen ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronLeft className="w-3.5 h-3.5" />}
        </button>

        <AnimatePresence initial={false}>
          {isOpen && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 330, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="h-full flex flex-col overflow-hidden select-none"
              style={{
                background: 'var(--bg-elevated)',
                borderLeft: '1px solid var(--border)',
              }}
            >
              {/* Header */}
              <div
                className="p-3.5 flex flex-col gap-2 flex-shrink-0"
                style={{
                  borderBottom: '1px solid var(--border)',
                  background: isReviewMode
                    ? 'linear-gradient(180deg, rgba(6,182,212,0.08) 0%, transparent 100%)'
                    : 'transparent',
                }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {isReviewMode ? (
                      <div className="p-1.5 rounded-lg bg-cyan-500/15 text-cyan-400">
                        <Sparkles className="w-4 h-4 animate-pulse" />
                      </div>
                    ) : (
                      <div className="p-1.5 rounded-lg bg-indigo-500/15 text-indigo-400">
                        <Database className="w-4 h-4" />
                      </div>
                    )}
                    <div>
                      <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-primary)]">
                        {isReviewMode ? 'Discovered Sources' : 'Active Sources'}
                      </h3>
                      <p className="text-[10px] text-muted-foreground">
                        {isReviewMode ? 'Review matches for answer' : 'Permanent chat context'}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <span
                      className="px-2 py-0.5 rounded-full text-[10px] font-bold"
                      style={{
                        background: isReviewMode ? 'rgba(6,182,212,0.15)' : 'rgba(99,102,241,0.15)',
                        color: isReviewMode ? '#06b6d4' : '#818cf8',
                        border: `1px solid ${isReviewMode ? 'rgba(6,182,212,0.3)' : 'rgba(99,102,241,0.3)'}`,
                      }}
                    >
                      {activeContext.length}
                    </span>

                    {activeContext.length > 0 && (
                      <button
                        onClick={handleClearAll}
                        className="p-1 rounded-lg text-xs transition-colors hover:bg-red-500/10 text-red-400"
                        title="Clear all sources"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Review Mode Helper Tip */}
                {isReviewMode && (
                  <div className="text-[11px] leading-relaxed text-cyan-300/90 bg-cyan-950/30 border border-cyan-500/20 rounded-xl p-2 flex items-start gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0 mt-0.5" />
                    <span>
                      Sources filtered with <strong>20% relative similarity</strong> (both local & live internet). Review and remove unwanted sources, then click <strong>Generate Answer</strong>.
                    </span>
                  </div>
                )}
              </div>

              {/* Extracted LLM Query & Keywords Banner (if available) */}
              {extractedInfo?.searchQuery && (
                <div
                  className="px-3.5 py-2.5 flex-shrink-0 text-xs"
                  style={{
                    background: 'rgba(6,182,212,0.04)',
                    borderBottom: '1px solid var(--border)',
                  }}
                >
                  <div
                    className="flex items-center justify-between cursor-pointer text-muted-foreground hover:text-cyan-400 transition-colors"
                    onClick={() => setShowQueryDetails(!showQueryDetails)}
                  >
                    <div className="flex items-center gap-1.5 font-semibold text-[11px] text-cyan-400">
                      <Search className="w-3 h-3" />
                      <span>Extracted Search Query</span>
                    </div>
                    <span className="text-[10px] underline">
                      {showQueryDetails ? 'hide' : 'show'}
                    </span>
                  </div>

                  {showQueryDetails && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      className="mt-1.5 space-y-1.5 overflow-hidden"
                    >
                      <p className="text-[11px] font-medium text-[var(--text-primary)] italic bg-[var(--bg-base)] px-2 py-1 rounded-lg border border-[var(--border)]">
                        &ldquo;{extractedInfo.searchQuery}&rdquo;
                      </p>

                      {extractedInfo.keywords && extractedInfo.keywords.length > 0 && (
                        <div className="flex flex-wrap gap-1 pt-0.5">
                          {extractedInfo.keywords.map((kw, i) => (
                            <span
                              key={i}
                              className="text-[9px] font-medium px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/20"
                            >
                              #{kw}
                            </span>
                          ))}
                        </div>
                      )}
                    </motion.div>
                  )}
                </div>
              )}

              {/* Sources List */}
              <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
                {activeContext.length === 0 ? (
                  <div className="text-center py-12 px-4 space-y-2">
                    <Database className="w-10 h-10 mx-auto opacity-25 text-muted-foreground" />
                    <p className="text-xs font-semibold text-[var(--text-secondary)]">
                      No sources in context
                    </p>
                    <p className="text-[11px] text-muted-foreground leading-relaxed">
                      Enable <strong>Smart Search</strong> or attach a file to discover matching knowledge documents.
                    </p>
                  </div>
                ) : (
                  activeContext.map((item, idx) => {
                    const Icon = TYPE_ICONS[item.type] || FileText;
                    const sourceId = (item.metadata?.sourceId as string) || (item.type !== 'web' && !item.metadata?.isInternet && !item.metadata?.isUserAttachment ? item.id : null);
                    const matchPercent = Math.round((item.relevanceScore || 0.85) * 100);
                    const isUserAtt = Boolean(item.metadata?.isUserAttachment || item.title.startsWith('[Attached'));
                    const isInternet = Boolean(item.metadata?.isInternet || item.type === 'web' || (!sourceId && item.metadata?.url));
                    const itemUrl = item.metadata?.url as string | undefined;
                    const thumbnail = (item.metadata?.thumbnail as string) || (item.metadata?.previewUrl as string);
                    const domain = (item.metadata?.domain as string) || (item.metadata?.author as string);

                    return (
                      <motion.div
                        key={item.id || idx}
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.95 }}
                        className="p-3 rounded-2xl relative group transition-all"
                        style={{
                          background: 'var(--bg-base)',
                          border: isUserAtt
                            ? '1px solid rgba(168, 85, 247, 0.4)'
                            : isReviewMode
                            ? '1px solid rgba(6,182,212,0.25)'
                            : '1px solid var(--border)',
                          boxShadow: isUserAtt ? '0 2px 12px rgba(168, 85, 247, 0.15)' : '0 2px 8px rgba(0,0,0,0.15)',
                        }}
                      >
                        {/* Action buttons on card */}
                        <div className="absolute top-2.5 right-2.5 flex items-center gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
                          {itemUrl && (
                            <a
                              href={itemUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="p-1 rounded-lg hover:bg-emerald-500/15 text-zinc-400 hover:text-emerald-300 transition-colors"
                              title="Open source in browser"
                            >
                              <ExternalLink className="w-3.5 h-3.5" />
                            </a>
                          )}
                          {sourceId && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setInspectSourceId(sourceId);
                              }}
                              className="p-1 rounded-lg hover:bg-[var(--bg-hover)] text-zinc-400 hover:text-cyan-300 transition-colors"
                              title="Open & view document details"
                            >
                              <Eye className="w-3.5 h-3.5" />
                            </button>
                          )}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRemoveSource(item.id, sourceId || undefined);
                            }}
                            className="p-1 rounded-lg hover:bg-red-500/10 text-zinc-400 hover:text-red-400 transition-colors"
                            title="Remove from context"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>

                        {/* Title & Type */}
                        <div className="flex items-start gap-2 mb-1.5 pr-14">
                          <div
                            className="p-1 rounded-lg flex-shrink-0 mt-0.5"
                            style={{
                              background: isUserAtt ? 'rgba(168,85,247,0.15)' : isInternet ? 'rgba(16,185,129,0.15)' : 'rgba(6,182,212,0.15)',
                              color: isUserAtt ? '#c084fc' : isInternet ? '#34d399' : '#22d3ee',
                            }}
                          >
                            <Icon className="w-3.5 h-3.5" />
                          </div>
                          <h4
                            onClick={() => {
                              if (sourceId) setInspectSourceId(sourceId);
                              else if (itemUrl) window.open(itemUrl, '_blank');
                            }}
                            className={`text-xs font-semibold leading-tight line-clamp-2 text-[var(--text-primary)] ${
                              sourceId || itemUrl ? 'cursor-pointer hover:text-cyan-400 transition-colors' : ''
                            }`}
                            title={item.title}
                          >
                            {item.title}
                          </h4>
                        </div>

                        {/* Optional media thumbnail */}
                        {thumbnail && (
                          <div className="my-1.5 overflow-hidden rounded-lg border border-[var(--border)] max-h-24 bg-black/40">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={thumbnail}
                              alt={item.title}
                              className="w-full h-24 object-cover hover:scale-105 transition-transform"
                              onError={(e) => {
                                (e.target as HTMLElement).style.display = 'none';
                              }}
                            />
                          </div>
                        )}

                        {/* Snippet */}
                        {item.snippet && (
                          <p className="text-[11px] leading-relaxed line-clamp-3 text-muted-foreground mt-1 font-normal">
                            {item.snippet}
                          </p>
                        )}

                        {/* Footer Badges */}
                        <div className="flex items-center justify-between mt-2 pt-2 border-t border-[var(--border)]">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span
                              className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                              style={{
                                background: isUserAtt
                                  ? 'rgba(168,85,247,0.15)'
                                  : matchPercent >= 80
                                  ? 'rgba(16,185,129,0.12)'
                                  : 'rgba(6,182,212,0.12)',
                                color: isUserAtt ? '#c084fc' : matchPercent >= 80 ? '#10b981' : '#06b6d4',
                                border: `1px solid ${
                                  isUserAtt
                                    ? 'rgba(168,85,247,0.3)'
                                    : matchPercent >= 80
                                    ? 'rgba(16,185,129,0.25)'
                                    : 'rgba(6,182,212,0.25)'
                                }`,
                              }}
                            >
                              {isUserAtt ? 'Attachment' : `${matchPercent}% Match`}
                            </span>

                            {isInternet && (
                              <span className="text-[9px] uppercase px-1 py-0.2 rounded bg-emerald-500/10 text-emerald-400 font-semibold border border-emerald-500/20">
                                Live Web
                              </span>
                            )}
                          </div>

                          <div className="flex items-center gap-1.5">
                            {domain && (
                              <span className="text-[9px] truncate max-w-[80px] px-1 rounded bg-[var(--bg-elevated)] text-muted-foreground font-mono">
                                {domain}
                              </span>
                            )}
                            {Boolean(item.metadata?.fileType) && (
                              <span className="text-[9px] uppercase px-1 rounded bg-[var(--bg-elevated)] text-muted-foreground font-mono">
                                {String(item.metadata?.fileType)}
                              </span>
                            )}
                            {sourceId ? (
                              <button
                                onClick={() => setInspectSourceId(sourceId)}
                                className="text-[10px] text-indigo-400 hover:text-indigo-300 font-medium flex items-center gap-0.5"
                              >
                                <Info className="w-3 h-3" /> Inspect
                              </button>
                            ) : itemUrl ? (
                              <a
                                href={itemUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[10px] text-emerald-400 hover:text-emerald-300 font-medium flex items-center gap-0.5"
                              >
                                Visit <ExternalLink className="w-2.5 h-2.5" />
                              </a>
                            ) : null}
                          </div>
                        </div>
                      </motion.div>
                    );
                  })
                )}
              </div>

              {/* Sticky Action Footer */}
              <div
                className="p-3 flex-shrink-0"
                style={{
                  borderTop: '1px solid var(--border)',
                  background: 'var(--bg-elevated)',
                }}
              >
                {isReviewMode ? (
                  <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    onClick={onGenerateAnswer}
                    disabled={activeContext.length === 0 || isGeneratingAnswer}
                    className="w-full py-2.5 px-4 rounded-2xl font-bold text-xs flex items-center justify-center gap-2 shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{
                      background: 'linear-gradient(135deg, #06b6d4 0%, #6366f1 100%)',
                      color: 'white',
                      boxShadow: '0 4px 16px rgba(6,182,212,0.35)',
                    }}
                  >
                    {isGeneratingAnswer ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Generating Answer...</span>
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-4 h-4" />
                        <span>Generate Answer ({activeContext.length} Sources)</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </>
                    )}
                  </motion.button>
                ) : (
                  <div className="text-center">
                    <p className="text-[10px] text-muted-foreground">
                      Active context is preserved across messages in this chat.
                    </p>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Metadata Detail Modal */}
      <DocumentMetadataModal
        sourceId={inspectSourceId}
        isOpen={Boolean(inspectSourceId)}
        onClose={() => setInspectSourceId(null)}
      />
    </>
  );
}

export default ContextPanel;

