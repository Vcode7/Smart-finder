'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { SourceCard } from '@/components/sources/SourceCard';
import { BriefingPanel } from '@/components/ai/BriefingPanel';
import { KnowledgeGraph } from '@/components/graph/KnowledgeGraph';
import { ResearchTimeline } from '@/components/timeline/ResearchTimeline';
import { WorkspaceView } from '@/components/workspace/WorkspaceView';
import { ComparePanel } from '@/components/ai/ComparePanel';
import { ReportGenerator } from '@/components/report/ReportGenerator';
import { useFetchMore } from '@/hooks/useFetchMore';
import {
  Zap, BarChart2, Network, GitBranch, Layers,
  FileOutput, Video, BookOpen, FileText, BarChart3, Globe, Sparkles,
  Plus, RefreshCw
} from 'lucide-react';
import type { ResearchSession, SourceType } from '@/types/research';

interface OverviewTabProps {
  session: ResearchSession;
  sessionId: string;
}

const SECTION_TABS = [
  { id: 'briefing', label: 'AI Executive Briefing', icon: Zap, badge: 'Qwen 3.6 27B', color: '#a855f7' },
  { id: 'workspace', label: 'Multi-Source Workspace', icon: Layers, badge: '2×2 Fullscreen', color: '#6366f1' },
  { id: 'graph', label: 'Knowledge Graph', icon: Network, badge: 'Interactive', color: '#06b6d4' },
  { id: 'timeline', label: 'Research Timeline', icon: GitBranch, badge: 'Chronological', color: '#10b981' },
  { id: 'compare', label: 'Compare Sources', icon: BarChart2, badge: 'Synthesis', color: '#f59e0b' },
  { id: 'report', label: 'Generate Report', icon: FileOutput, badge: 'Export MD', color: '#f43f5e' },
];

const SOURCE_TYPES: Array<{ type: SourceType; label: string; icon: React.ElementType; color: string }> = [
  { type: 'video', label: 'Videos', icon: Video, color: '#f43f5e' },
  { type: 'paper', label: 'Academic Papers', icon: BookOpen, color: '#06b6d4' },
  { type: 'article', label: 'Articles & News', icon: FileText, color: '#10b981' },
  { type: 'report', label: 'Policy Reports', icon: BarChart3, color: '#f59e0b' },
  { type: 'web', label: 'Web References', icon: Globe, color: '#a855f7' },
];

export function OverviewTab({ session, sessionId }: OverviewTabProps) {
  const [activeSection, setActiveSection] = useState('briefing');
  const { fetchMore, loadingType } = useFetchMore(sessionId);

  const statCounts = SOURCE_TYPES.map((st) => ({
    ...st,
    count: session.sources.filter((s) => s.type === st.type).length,
  }));

  const topSources = session.sources.slice(0, 4);

  return (
    <div className="h-full overflow-auto">
      <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
        {/* Metric Cards Row */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5">
          {statCounts.map(({ type, label, icon: Icon, color, count }) => {
            const isFetchingThis = loadingType === type;

            return (
              <motion.div
                key={type}
                whileHover={{ y: -2 }}
                className="p-4 rounded-2xl border transition-all duration-200 shadow-sm relative overflow-hidden group flex flex-col justify-between"
                style={{
                  background: 'var(--bg-card)',
                  borderColor: 'var(--border)',
                  backdropFilter: 'blur(16px)',
                }}
              >
                <div
                  className="absolute top-0 right-0 w-20 h-20 rounded-full blur-2xl opacity-15 pointer-events-none group-hover:opacity-30 transition-opacity"
                  style={{ background: color }}
                />

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <div className="w-8 h-8 rounded-xl flex items-center justify-center" style={{ background: `${color}18` }}>
                      <Icon className="w-4 h-4" style={{ color }} />
                    </div>
                    <span className="text-[11px] font-semibold" style={{ color: 'var(--text-muted)' }}>{count} items</span>
                  </div>

                  <div>
                    <p className="text-2xl font-black tracking-tight" style={{ color: 'var(--text-primary)' }}>{count}</p>
                    <p className="text-xs font-medium truncate mt-0.5" style={{ color: 'var(--text-secondary)' }}>{label}</p>
                  </div>
                </div>

                <div className="mt-3 pt-2 border-t border-[var(--border-subtle)] flex items-center justify-between">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      fetchMore(type);
                    }}
                    disabled={isFetchingThis}
                    className="w-full flex items-center justify-center gap-1.5 py-1 px-2 rounded-lg text-[11px] font-bold transition-all hover:bg-[var(--bg-hover)] disabled:opacity-50 cursor-pointer"
                    style={{
                      color: color,
                      background: `${color}10`,
                      border: `1px solid ${color}25`,
                    }}
                    title={`Fetch more ${label.toLowerCase()} only`}
                  >
                    {isFetchingThis ? (
                      <>
                        <RefreshCw className="w-3 h-3 animate-spin" />
                        <span>Fetching...</span>
                      </>
                    ) : (
                      <>
                        <Plus className="w-3 h-3 stroke-[2.5]" />
                        <span>Fetch More</span>
                      </>
                    )}
                  </button>
                </div>
              </motion.div>
            );
          })}
        </div>

        {/* Provider Pipeline Diagnostics & Health Matrix */}
        {session.providerStatuses && (
          <div
            className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 rounded-2xl border shadow-sm"
            style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
          >
            <div className="flex items-center gap-2 text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              <span>Real Provider Pipeline Status:</span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {[
                { key: 'video', label: 'YouTube API', icon: Video, status: session.providerStatuses.video },
                { key: 'paper', label: 'Semantic Scholar', icon: BookOpen, status: session.providerStatuses.paper },
                { key: 'article', label: 'NewsAPI', icon: FileText, status: session.providerStatuses.article },
                { key: 'reports', label: 'Policy Reports', icon: BarChart3, status: session.providerStatuses.reports },
                { key: 'web', label: 'Web Search', icon: Globe, status: session.providerStatuses.web },
              ].map(({ key, label, icon: Icon, status }) => {
                if (!status) return null;
                const isSuccess = status.status === 'success';
                const isNotConfigured = status.status === 'not_configured';
                const isError = status.status === 'error';
                const isEmpty = status.status === 'empty';

                const badgeBg = isSuccess
                  ? 'rgba(16, 185, 129, 0.12)'
                  : isNotConfigured
                  ? 'rgba(245, 158, 11, 0.12)'
                  : isError
                  ? 'rgba(244, 63, 94, 0.12)'
                  : 'var(--bg-card)';

                const badgeColor = isSuccess
                  ? '#10b981'
                  : isNotConfigured
                  ? '#f59e0b'
                  : isError
                  ? '#f43f5e'
                  : 'var(--text-muted)';

                return (
                  <div
                    key={key}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-[11px] font-mono border"
                    style={{ background: badgeBg, borderColor: `${badgeColor}35`, color: badgeColor }}
                    title={status.error || `${label}: ${status.count} verified sources discovered`}
                  >
                    <Icon className="w-3 h-3" />
                    <span className="font-sans font-semibold">{label}:</span>
                    <span className="font-bold">
                      {isSuccess ? `${status.count} live` : isNotConfigured ? 'No Key' : isError ? 'Error' : '0 found'}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Section Navigation Tabs */}
        <div className="p-1.5 rounded-2xl border flex items-center gap-1.5 overflow-x-auto no-scrollbar shadow-sm" style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}>
          {SECTION_TABS.map((tab) => {
            const isActive = activeSection === tab.id;
            const Icon = tab.icon;

            return (
              <button
                key={tab.id}
                onClick={() => setActiveSection(tab.id)}
                className={`relative flex items-center gap-2 px-3.5 py-2.5 rounded-xl text-xs font-bold transition-all duration-200 whitespace-nowrap flex-shrink-0 ${
                  isActive ? 'shadow-sm text-white' : 'hover:bg-[var(--bg-hover)]'
                }`}
                style={{
                  background: isActive ? 'var(--bg-active)' : 'transparent',
                  color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                  border: isActive ? '1px solid var(--border)' : '1px solid transparent',
                }}
              >
                <Icon className="w-4 h-4" style={{ color: isActive ? tab.color : 'var(--text-muted)' }} />
                <span>{tab.label}</span>
                <span
                  className="text-[10px] px-1.5 py-0.2 rounded-full font-mono font-medium"
                  style={{
                    background: isActive ? `${tab.color}25` : 'var(--bg-base)',
                    color: isActive ? tab.color : 'var(--text-muted)',
                  }}
                >
                  {tab.badge}
                </span>

                {isActive && (
                  <motion.div
                    layoutId="active-overview-section"
                    className="absolute inset-0 rounded-xl pointer-events-none"
                    style={{ border: `1px solid ${tab.color}50` }}
                    transition={{ type: 'spring', bounce: 0.1, duration: 0.25 }}
                  />
                )}
              </button>
            );
          })}
        </div>

        {/* Dynamic Section Viewport */}
        <div className="min-h-[400px]">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeSection}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ type: 'spring', bounce: 0, duration: 0.25 }}
            >
              {activeSection === 'briefing' && (
                <BriefingPanel session={session} sessionId={sessionId} />
              )}
              {activeSection === 'workspace' && (
                <WorkspaceView session={session} sessionId={sessionId} />
              )}
              {activeSection === 'graph' && (
                <KnowledgeGraph session={session} sessionId={sessionId} />
              )}
              {activeSection === 'timeline' && (
                <ResearchTimeline session={session} sessionId={sessionId} />
              )}
              {activeSection === 'compare' && (
                <ComparePanel session={session} sessionId={sessionId} />
              )}
              {activeSection === 'report' && (
                <ReportGenerator session={session} sessionId={sessionId} />
              )}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Top Sources Highlighting */}
        {topSources.length > 0 && (
          <div className="pt-4 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-indigo-400" />
                <h2 className="text-sm font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
                  High Relevance Discoveries
                </h2>
              </div>
              <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
                Sorted by AI relevance score
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
              {topSources.map((source) => (
                <SourceCard key={source.id} source={source} sessionId={sessionId} compact />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
