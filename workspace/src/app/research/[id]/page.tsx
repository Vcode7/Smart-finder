'use client';

import { useParams } from 'next/navigation';
import { AnimatePresence } from 'framer-motion';
import { useResearchStore } from '@/store/research';
import { ResearchTabs } from '@/components/tabs/ResearchTabs';
import { OverviewTab } from '@/components/tabs/OverviewTab';
import { SourceGrid } from '@/components/sources/SourceGrid';
import { SourceDetailModal } from '@/components/sources/SourceDetailModal';
import { FullScreenWorkspace } from '@/components/workspace/FullScreenWorkspace';
import { useUIStore } from '@/store/ui';
import { sortSources } from '@/lib/utils/scoring';
import { useFetchMore } from '@/hooks/useFetchMore';
import { Video, BookOpen, FileText, BarChart3, Globe, Sparkles, Plus, RefreshCw } from 'lucide-react';
import type { SourceType } from '@/types/research';

const TYPE_TAB_MAP: Record<string, SourceType> = {
  videos: 'video',
  papers: 'paper',
  articles: 'article',
  reports: 'report',
  sources: 'web',
};

const TAB_DESCRIPTIONS: Record<string, { title: string; desc: string; icon: React.ElementType; color: string; fetchLabel: string }> = {
  videos: { title: 'Video Intelligence & Transcripts', desc: 'YouTube and lecture recordings with AI-generated chapters, timestamps and speakers', icon: Video, color: '#f43f5e', fetchLabel: 'Fetch More Videos' },
  papers: { title: 'Peer-Reviewed Academic Papers', desc: 'Preprints and published studies with methodology breakdowns and citation metrics', icon: BookOpen, color: '#06b6d4', fetchLabel: 'Fetch More Papers' },
  articles: { title: 'News & Media Publications', desc: 'Authoritative coverage, journalistic analysis and editorial viewpoints', icon: FileText, color: '#10b981', fetchLabel: 'Fetch More Articles' },
  reports: { title: 'Policy Frameworks & Official Reports', desc: 'Government whitepapers, NITI Aayog guidelines and institutional benchmarks', icon: BarChart3, color: '#f59e0b', fetchLabel: 'Fetch More Reports' },
  sources: { title: 'Web References & Encylopedic Data', desc: 'Broad internet research references, wiki data and institutional portals', icon: Globe, color: '#a855f7', fetchLabel: 'Fetch More Web References' },
};

export default function ResearchPage() {
  const params = useParams();
  const sessionId = params?.id as string;
  const { sessions } = useResearchStore();
  const { sortBy, searchQuery, workspaceModalOpen, setWorkspaceModalOpen } = useUIStore();
  const { fetchMore, loadingType } = useFetchMore(sessionId);

  const session = sessions.find((s) => s.id === sessionId);
  if (!session) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-8 text-center">
        <div className="w-12 h-12 rounded-2xl bg-indigo-500/15 text-indigo-400 flex items-center justify-center mb-3">
          <Sparkles className="w-6 h-6" />
        </div>
        <p className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Research Session Not Found</p>
        <p className="text-xs text-muted-foreground mt-1">This session may have been deleted or expired from local memory.</p>
      </div>
    );
  }

  const activeTab = session.activeTab;

  // Filter + sort sources
  let displaySources = session.sources;
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    displaySources = displaySources.filter((s) =>
      s.title.toLowerCase().includes(q) ||
      s.description?.toLowerCase().includes(q) ||
      s.provider.toLowerCase().includes(q)
    );
  }

  const tabType = TYPE_TAB_MAP[activeTab];
  if (tabType) {
    displaySources = displaySources.filter((s) => s.type === tabType);
  }
  displaySources = sortSources(displaySources, sortBy);

  const tabInfo = TAB_DESCRIPTIONS[activeTab];
  const isFetchingThisType = loadingType === tabType;

  return (
    <div className="h-full flex-1 flex flex-col overflow-hidden min-h-0" style={{ background: 'var(--bg-base)' }}>
      {/* Sticky Tab Navigation Header */}
      <ResearchTabs sessionId={sessionId} session={session} />

      {/* Main Tab Viewport */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {activeTab === 'overview' && (
          <OverviewTab session={session} sessionId={sessionId} />
        )}

        {activeTab !== 'overview' && (
          <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-5">
            {/* Category Header Banner */}
            {tabInfo && (
              <div
                className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 sm:p-5 rounded-2xl border shadow-sm"
                style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
              >
                <div className="flex items-center gap-3">
                  <div
                    className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                    style={{ background: `${tabInfo.color}18` }}
                  >
                    <tabInfo.icon className="w-5 h-5" style={{ color: tabInfo.color }} />
                  </div>
                  <div>
                    <h2 className="text-sm sm:text-base font-bold" style={{ color: 'var(--text-primary)' }}>
                      {tabInfo.title}
                    </h2>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {tabInfo.desc}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2.5 flex-wrap self-start sm:self-auto">
                  <span
                    className="text-xs font-mono font-bold px-3 py-1.5 rounded-xl border"
                    style={{
                      background: `${tabInfo.color}15`,
                      color: tabInfo.color,
                      borderColor: `${tabInfo.color}30`,
                    }}
                  >
                    {displaySources.length} {displaySources.length === 1 ? 'source' : 'sources'}
                  </span>

                  {/* Dedicated Per-Source-Type Fetch More Button */}
                  {tabType && (
                    <button
                      onClick={() => fetchMore(tabType)}
                      disabled={isFetchingThisType}
                      className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-bold text-white transition-all shadow-md hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 disabled:scale-100 cursor-pointer"
                      style={{
                        background: isFetchingThisType
                          ? 'var(--bg-active)'
                          : `linear-gradient(135deg, ${tabInfo.color} 0%, #6366f1 100%)`,
                        boxShadow: `0 4px 14px ${tabInfo.color}30`,
                      }}
                      title={`Fetch additional ${tabType} results only`}
                    >
                      {isFetchingThisType ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          <span>Fetching {tabType}...</span>
                        </>
                      ) : (
                        <>
                          <Plus className="w-3.5 h-3.5 stroke-[2.5]" />
                          <span>{tabInfo.fetchLabel}</span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Source Grid */}
            <SourceGrid
              sources={displaySources}
              sessionId={sessionId}
              emptyType={tabType}
            />
          </div>
        )}
      </div>

      {/* Full-Screen Multi-View Workspace Overlay (2×2 True Fullscreen) */}
      <AnimatePresence>
        {workspaceModalOpen && (
          <FullScreenWorkspace
            session={session}
            sessionId={sessionId}
            onClose={() => setWorkspaceModalOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Comprehensive Multi-Tab Source Detail & Intelligence Modal */}
      <SourceDetailModal sessionId={sessionId} />
    </div>
  );
}
