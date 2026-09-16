// src/components/sources/SourceGrid.tsx
// Renders real source grid or contextual provider status diagnostics (No fabricated data)

'use client';

import { motion } from 'framer-motion';
import { useResearchStore } from '@/store/research';
import { useFetchMore } from '@/hooks/useFetchMore';
import { SourceCard } from './SourceCard';
import { SourceSkeleton } from './SourceSkeleton';
import type { Source, SourceType } from '@/types/research';
import {
  Video, BookOpen, FileText, BarChart3, Globe, Search,
  AlertTriangle, KeyRound, RefreshCw, Info,
  AlertCircle, Plus, Sparkles
} from 'lucide-react';

interface SourceGridProps {
  sources: Source[];
  sessionId: string;
  loading?: boolean;
  emptyType?: SourceType;
}

const CATEGORY_META: Record<SourceType, { label: string; icon: React.ElementType; envVar: string; providerName: string; color: string }> = {
  video: { label: 'Video Lectures & Disquisitions', icon: Video, envVar: 'YOUTUBE_API_KEY', providerName: 'YouTube Data API v3', color: '#f43f5e' },
  paper: { label: 'Peer-Reviewed Academic Papers', icon: BookOpen, envVar: 'SEMANTIC_SCHOLAR_API_KEY (Optional)', providerName: 'Semantic Scholar API', color: '#06b6d4' },
  article: { label: 'Articles & News Publications', icon: FileText, envVar: 'NEWS_API_KEY', providerName: 'NewsAPI', color: '#10b981' },
  report: { label: 'Institutional & Policy Reports', icon: BarChart3, envVar: 'NEWS_API_KEY', providerName: 'NewsAPI Policy Reports', color: '#f59e0b' },
  web: { label: 'Live Web References', icon: Globe, envVar: 'SERP_API_KEY (Optional)', providerName: 'DuckDuckGo / SerpAPI', color: '#a855f7' },
};

export function SourceGrid({ sources, sessionId, loading, emptyType }: SourceGridProps) {
  const { sessions } = useResearchStore();
  const { fetchMore, loadingType } = useFetchMore(sessionId);
  const session = sessions.find((s) => s.id === sessionId);

  const isFetchingThisType = emptyType ? loadingType === emptyType : false;

  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <SourceSkeleton key={i} />
        ))}
      </div>
    );
  }

  // Handle zero results with clear provider diagnostic status
  if (sources.length === 0) {
    const meta = emptyType
      ? CATEGORY_META[emptyType]
      : { label: 'No sources found', icon: Search, envVar: 'API Keys', providerName: 'Source Provider', color: '#6366f1' };
    const Icon = meta.icon;
    const providerKey = emptyType === 'report' ? 'reports' : emptyType || 'web';
    const statusObj = session?.providerStatuses?.[providerKey];

    const isNotConfigured = statusObj?.status === 'not_configured';
    const isError = statusObj?.status === 'error';
    const isEmptyResult = statusObj?.status === 'empty';

    return (
      <div className="max-w-2xl mx-auto my-12 p-8 rounded-3xl border shadow-xl backdrop-blur-2xl text-center space-y-6" style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}>
        {/* Status Icon */}
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto shadow-md"
          style={{
            background: isNotConfigured
              ? 'rgba(245, 158, 11, 0.12)'
              : isError
              ? 'rgba(244, 63, 94, 0.12)'
              : 'var(--bg-card)',
            border: `1px solid ${isNotConfigured ? '#f59e0b40' : isError ? '#f43f5e40' : 'var(--border)'}`,
          }}
        >
          {isNotConfigured ? (
            <KeyRound className="w-8 h-8 text-amber-400" />
          ) : isError ? (
            <AlertTriangle className="w-8 h-8 text-rose-400" />
          ) : (
            <Icon className="w-8 h-8 text-muted-foreground" />
          )}
        </div>

        {/* Status Message */}
        <div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono font-bold mb-3"
            style={{
              background: isNotConfigured
                ? 'rgba(245, 158, 11, 0.15)'
                : isError
                ? 'rgba(244, 63, 94, 0.15)'
                : 'var(--bg-active)',
              color: isNotConfigured ? '#f59e0b' : isError ? '#f43f5e' : 'var(--text-muted)',
            }}
          >
            {isNotConfigured && <AlertCircle className="w-3.5 h-3.5" />}
            {isError && <AlertTriangle className="w-3.5 h-3.5" />}
            {isEmptyResult && <Info className="w-3.5 h-3.5" />}
            <span>
              {isNotConfigured
                ? 'API Not Configured'
                : isError
                ? 'Provider Request Failed'
                : isEmptyResult
                ? 'No Live Sources Returned'
                : 'Zero Sources Available'}
            </span>
          </div>

          <h3 className="text-base sm:text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
            {meta.label}
          </h3>

          <p className="text-xs sm:text-sm max-w-md mx-auto leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
            {statusObj?.error || (
              isNotConfigured
                ? `To discover real ${meta.label.toLowerCase()}, add your ${meta.envVar} to .env.local and restart the server.`
                : `No verified sources were returned from ${meta.providerName} for "${session?.topic || 'this topic'}".`
            )}
          </p>
        </div>

        {/* Retry / Fetch Button in Empty State */}
        {emptyType && (
          <div className="pt-2 flex justify-center">
            <button
              onClick={() => fetchMore(emptyType)}
              disabled={isFetchingThisType}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold text-white transition-all shadow-lg hover:scale-105 active:scale-95 disabled:opacity-50 disabled:scale-100"
              style={{
                background: `linear-gradient(135deg, ${meta.color} 0%, #6366f1 100%)`,
              }}
            >
              {isFetchingThisType ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Searching for {emptyType}...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  <span>Fetch {meta.label} Now</span>
                </>
              )}
            </button>
          </div>
        )}

        {/* Configuration Guidance Card */}
        {isNotConfigured && (
          <div className="p-4 rounded-2xl border text-left text-xs space-y-2" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
            <div className="flex items-center justify-between font-mono font-bold text-[11px]" style={{ color: 'var(--text-muted)' }}>
              <span>Configuration Required</span>
              <span className="text-amber-400 font-sans font-semibold">.env.local</span>
            </div>
            <div className="p-2.5 rounded-xl font-mono text-[11px] select-all overflow-x-auto" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
              {meta.envVar}=your_api_key_here
            </div>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              Mock data fallbacks are permanently disabled to ensure absolute research authenticity.
            </p>
          </div>
        )}
      </div>
    );
  }

  const currentMeta = emptyType ? CATEGORY_META[emptyType] : null;

  return (
    <div className="space-y-6">
      <motion.div
        layout
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
      >
        {sources.map((source, i) => (
          <motion.div
            key={source.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04, type: 'spring', bounce: 0.1, duration: 0.35 }}
          >
            <SourceCard source={source} sessionId={sessionId} />
          </motion.div>
        ))}
      </motion.div>

      {/* Bottom Discovery / Fetch More Card for Specific Source Type */}
      {emptyType && currentMeta && (
        <div
          className="p-4 sm:p-5 rounded-2xl border flex flex-col sm:flex-row items-center justify-between gap-4 transition-all shadow-sm"
          style={{
            background: 'var(--bg-elevated)',
            borderColor: 'var(--border)',
          }}
        >
          <div className="flex items-center gap-3 text-center sm:text-left">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 mx-auto sm:mx-0"
              style={{ background: `${currentMeta.color}15` }}
            >
              <currentMeta.icon className="w-5 h-5" style={{ color: currentMeta.color }} />
            </div>
            <div>
              <p className="text-xs sm:text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                Want more {currentMeta.label.toLowerCase()}?
              </p>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Query {currentMeta.providerName} for additional verified sources on &ldquo;{session?.topic}&rdquo;.
              </p>
            </div>
          </div>

          <button
            onClick={() => fetchMore(emptyType)}
            disabled={isFetchingThisType}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold text-white transition-all shadow-md hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 disabled:scale-100 flex-shrink-0 cursor-pointer"
            style={{
              background: `linear-gradient(135deg, ${currentMeta.color} 0%, #6366f1 100%)`,
              boxShadow: `0 4px 14px ${currentMeta.color}25`,
            }}
          >
            {isFetchingThisType ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span>Fetching {emptyType}...</span>
              </>
            ) : (
              <>
                <Plus className="w-3.5 h-3.5 stroke-[3]" />
                <span>Fetch 8 More {emptyType === 'web' ? 'References' : emptyType.charAt(0).toUpperCase() + emptyType.slice(1) + 's'}</span>
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
