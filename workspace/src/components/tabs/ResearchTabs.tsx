// src/components/tabs/ResearchTabs.tsx
// Research Navigation Bar with Modality Tabs, Search Filter, and AI Selection Actions

'use client';

import { motion } from 'framer-motion';
import { useResearchStore } from '@/store/research';
import { useUIStore } from '@/store/ui';
import {
  Video, BookOpen, FileText, BarChart3, Globe, LayoutGrid,
  Search, CheckCheck, Sparkles, X, CheckSquare
} from 'lucide-react';
import type { ResearchSession, TabType } from '@/types/research';

const TABS: Array<{ id: TabType; label: string; icon: React.ElementType; typeKey: string; color: string }> = [
  { id: 'overview', label: 'Intelligence Overview', icon: LayoutGrid, typeKey: 'all', color: '#6366f1' },
  { id: 'videos', label: 'Videos', icon: Video, typeKey: 'video', color: '#f43f5e' },
  { id: 'papers', label: 'Research Papers', icon: BookOpen, typeKey: 'paper', color: '#06b6d4' },
  { id: 'articles', label: 'Articles & News', icon: FileText, typeKey: 'article', color: '#10b981' },
  { id: 'reports', label: 'Policy Reports', icon: BarChart3, typeKey: 'report', color: '#f59e0b' },
  { id: 'sources', label: 'Web References', icon: Globe, typeKey: 'web', color: '#a855f7' },
];

interface ResearchTabsProps {
  sessionId: string;
  session: ResearchSession;
}

export function ResearchTabs({ sessionId, session }: ResearchTabsProps) {
  const { setActiveTab } = useResearchStore();
  const {
    sortBy,
    setSortBy,
    searchQuery,
    setSearchQuery,
    aiSelectedSourceIds,
    selectAllForAI,
    clearAllForAI,
    selectTopRelevantForAI,
  } = useUIStore();

  const countFor = (typeKey: string) => {
    if (typeKey === 'all') return session.sources.length;
    return session.sources.filter((s) => s.type === typeKey).length;
  };

  const currentTabSources = session.activeTab === 'overview'
    ? session.sources
    : session.sources.filter((s) => {
        const matchingTab = TABS.find((t) => t.id === session.activeTab);
        return matchingTab ? s.type === matchingTab.typeKey : true;
      });

  const selectedInCurrentTabCount = currentTabSources.filter((s) =>
    aiSelectedSourceIds.includes(s.id)
  ).length;

  return (
    <div
      className="flex-shrink-0 border-b z-20 backdrop-blur-xl"
      style={{ background: 'var(--glass-bg)', borderColor: 'var(--border)' }}
    >
      {/* Upper Tab Bar */}
      <div className="flex items-center justify-between px-4 sm:px-6 pt-2 overflow-x-auto no-scrollbar">
        <div className="flex items-center gap-1.5 min-w-max pb-2">
          {TABS.map((tab) => {
            const isActive = session.activeTab === tab.id;
            const count = countFor(tab.typeKey);
            const Icon = tab.icon;

            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(sessionId, tab.id)}
                className={`relative flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold transition-all duration-200 ${
                  isActive ? 'shadow-sm' : 'hover:bg-[var(--bg-hover)]'
                }`}
                style={{
                  background: isActive ? 'var(--bg-elevated)' : 'transparent',
                  color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                  border: isActive ? '1px solid var(--border)' : '1px solid transparent',
                }}
              >
                <Icon className="w-3.5 h-3.5" style={{ color: isActive ? tab.color : 'var(--text-muted)' }} />
                <span>{tab.label}</span>

                {count > 0 && (
                  <span
                    className="text-[10px] font-mono font-bold px-1.5 py-0.2 rounded-full"
                    style={{
                      background: isActive ? 'var(--accent-muted)' : 'var(--bg-active)',
                      color: isActive ? 'var(--accent)' : 'var(--text-muted)',
                    }}
                  >
                    {count}
                  </span>
                )}

                {isActive && (
                  <motion.div
                    layoutId="active-tab-glow"
                    className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full"
                    style={{ background: 'linear-gradient(90deg, #6366f1 0%, #a855f7 100%)' }}
                    transition={{ type: 'spring', bounce: 0.15, duration: 0.3 }}
                  />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Filter & AI Selection Sub-toolbar */}
      <div
        className="flex items-center justify-between gap-3 px-4 sm:px-6 py-2.5 border-t flex-wrap"
        style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-surface)' }}
      >
        {/* Search within sources */}
        <div
          className="flex items-center gap-2 flex-1 min-w-[200px] max-w-sm px-3 py-1.5 rounded-xl border transition-all focus-within:border-indigo-500/50"
          style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
        >
          <Search className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--text-muted)' }} />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search keywords, authors, or concepts..."
            className="bg-transparent text-xs outline-none flex-1 font-medium"
            style={{ color: 'var(--text-primary)' }}
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="text-[10px] px-1 rounded text-muted-foreground hover:text-foreground"
            >
              Clear
            </button>
          )}
        </div>

        {/* AI Selection Actions Toolbar */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Quick Selection Buttons */}
          <div className="flex items-center gap-1 p-0.5 rounded-xl border" style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}>
            <button
              onClick={() => selectTopRelevantForAI(session.sources, 5)}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg font-medium text-[var(--text-secondary)] hover:text-indigo-400 transition-colors"
              title="Select Top 5 by Relevance for AI"
            >
              <Sparkles className="w-3 h-3 text-indigo-400" />
              <span>Select Top 5</span>
            </button>

            <button
              onClick={() => selectAllForAI(currentTabSources.map((s) => s.id))}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg font-medium text-[var(--text-secondary)] hover:text-emerald-400 transition-colors"
              title="Select all sources in this view"
            >
              <CheckSquare className="w-3 h-3 text-emerald-400" />
              <span>Select All</span>
            </button>

            {aiSelectedSourceIds.length > 0 && (
              <button
                onClick={clearAllForAI}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg font-medium text-[var(--text-muted)] hover:text-rose-400 transition-colors"
                title="Clear all AI selections"
              >
                <X className="w-3 h-3 text-rose-400" />
                <span>Clear</span>
              </button>
            )}
          </div>

          {/* AI Selected Counter Badge */}
          {aiSelectedSourceIds.length > 0 && (
            <span className="text-[11px] font-semibold px-2.5 py-1 rounded-xl flex items-center gap-1.5 shadow-sm" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
              <CheckCheck className="w-3.5 h-3.5" />
              <span>{aiSelectedSourceIds.length} for AI</span>
            </span>
          )}

          {/* Sort selector */}
          <div className="flex items-center p-0.5 rounded-xl border" style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}>
            {(['relevance', 'date'] as const).map((s) => {
              const active = sortBy === s;
              return (
                <button
                  key={s}
                  onClick={() => setSortBy(s)}
                  className={`text-xs px-2.5 py-1 rounded-lg font-medium transition-all capitalize ${
                    active ? 'shadow-sm' : 'hover:text-white'
                  }`}
                  style={{
                    background: active ? 'var(--accent-muted)' : 'transparent',
                    color: active ? 'var(--accent)' : 'var(--text-muted)',
                  }}
                >
                  {s}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
