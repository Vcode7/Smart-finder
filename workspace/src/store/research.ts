// src/store/research.ts
'use client';

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type {
  ResearchSession,
  Source,
  TabType,
  WorkspaceLayout,
  WorkspacePane,
  ResearchCollection,
  OverallBriefing,
  ComparisonResult,
  ResearchReport,
  KnowledgeGraph,
  TimelineEvent,
  ChatMessage,
  AIInsights,
} from '@/types/research';
import { generateId } from '@/lib/utils/scoring';
import { isoNow } from '@/lib/utils/date';

interface ResearchState {
  sessions: ResearchSession[];
  activeSessionId: string | null;

  // Active session helpers
  activeSession: () => ResearchSession | null;
  getSources: () => Source[];

  // Session management
  createSession: (topic: string) => string;
  deleteSession: (id: string) => void;
  setActiveSession: (id: string) => void;
  updateSession: (id: string, updates: Partial<ResearchSession>) => void;

  // Sources & Providers
  setSources: (sessionId: string, sources: Partial<ResearchSession['sources']> | ResearchSession['sources']) => void;
  setProviderStatuses: (sessionId: string, statuses: Record<string, import('@/types/research').ProviderResult>) => void;
  addSources: (sessionId: string, sources: Source[]) => void;
  updateSource: (sessionId: string, sourceId: string, updates: Partial<Source>) => void;
  toggleSaveSource: (sessionId: string, sourceId: string) => void;
  toggleBookmarkSource: (sessionId: string, sourceId: string) => void;

  // AI data
  setAIInsights: (sessionId: string, sourceId: string, insights: AIInsights) => void;
  setBriefing: (sessionId: string, briefing: OverallBriefing) => void;
  setKnowledgeGraph: (sessionId: string, graph: KnowledgeGraph) => void;
  setTimeline: (sessionId: string, events: TimelineEvent[]) => void;
  addComparison: (sessionId: string, comparison: ComparisonResult) => void;
  addReport: (sessionId: string, report: ResearchReport) => void;

  // Chat
  addChatMessage: (sessionId: string, sourceId: string, message: ChatMessage) => void;

  // Collections
  createCollection: (sessionId: string, name: string) => string;
  deleteCollection: (sessionId: string, collectionId: string) => void;
  renameCollection: (sessionId: string, collectionId: string, name: string) => void;
  addToCollection: (sessionId: string, collectionId: string, sourceId: string) => void;
  removeFromCollection: (sessionId: string, collectionId: string, sourceId: string) => void;

  // Tab & workspace
  setActiveTab: (sessionId: string, tab: TabType) => void;
  setWorkspaceLayout: (sessionId: string, layout: WorkspaceLayout) => void;
  updatePane: (sessionId: string, paneId: string, updates: Partial<WorkspacePane>) => void;
  setPaneSource: (sessionId: string, paneId: string, sourceId: string | undefined) => void;
  setPaneContentType: (sessionId: string, paneId: string, contentType: import('@/types/research').PaneContentType) => void;
}

const DEFAULT_PANE_TYPES: import('@/types/research').PaneContentType[] = ['insights', 'video', 'paper', 'timeline'];

function getDefaultPanes(layout: WorkspaceLayout): WorkspacePane[] {
  const count = parseInt(layout, 10);
  return Array.from({ length: count }, (_, i) => ({
    id: `pane-${i}`,
    contentType: DEFAULT_PANE_TYPES[i] || 'source',
    sourceId: undefined,
    isMinimized: false,
    isMaximized: false,
    chatOpen: false,
    insightsOpen: false,
  }));
}

export const useResearchStore = create<ResearchState>()(
  persist(
    (set, get) => ({
      sessions: [],
      activeSessionId: null,

      activeSession: () => {
        const { sessions, activeSessionId } = get();
        return sessions.find(s => s.id === activeSessionId) || null;
      },

      getSources: () => {
        const session = get().activeSession();
        return session?.sources || [];
      },

      createSession: (topic) => {
        const id = generateId();
        const session: ResearchSession = {
          id,
          topic,
          sources: [],
          collections: [],
          reports: [],
          comparisons: [],
          createdAt: isoNow(),
          updatedAt: isoNow(),
          activeTab: 'overview',
          workspacePanes: getDefaultPanes('4'),
          workspaceLayout: '4',
        };
        set(state => ({
          sessions: [session, ...state.sessions],
          activeSessionId: id,
        }));
        return id;
      },

      deleteSession: (id) => {
        set(state => ({
          sessions: state.sessions.filter(s => s.id !== id),
          activeSessionId: state.activeSessionId === id
            ? (state.sessions[0]?.id || null)
            : state.activeSessionId,
        }));
      },

      setActiveSession: (id) => set({ activeSessionId: id }),

      updateSession: (id, updates) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === id ? { ...s, ...updates, updatedAt: isoNow() } : s
          ),
        }));
      },

      setSources: (sessionId, sources) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId ? { ...s, sources: sources as Source[], updatedAt: isoNow() } : s
          ),
        }));
      },

      setProviderStatuses: (sessionId, statuses) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId ? { ...s, providerStatuses: statuses, updatedAt: isoNow() } : s
          ),
        }));
      },

      addSources: (sessionId, newSources) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? { ...s, sources: [...s.sources, ...newSources], updatedAt: isoNow() }
              : s
          ),
        }));
      },

      updateSource: (sessionId, sourceId, updates) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? {
                  ...s,
                  sources: s.sources.map(src => src.id === sourceId ? { ...src, ...updates } : src),
                  updatedAt: isoNow(),
                }
              : s
          ),
        }));
      },

      toggleSaveSource: (sessionId, sourceId) => {
        const session = get().sessions.find(s => s.id === sessionId);
        const source = session?.sources.find(s => s.id === sourceId);
        if (source) get().updateSource(sessionId, sourceId, { isSaved: !source.isSaved });
      },

      toggleBookmarkSource: (sessionId, sourceId) => {
        const session = get().sessions.find(s => s.id === sessionId);
        const source = session?.sources.find(s => s.id === sourceId);
        if (source) get().updateSource(sessionId, sourceId, { isBookmarked: !source.isBookmarked });
      },

      setAIInsights: (sessionId, sourceId, insights) => {
        get().updateSource(sessionId, sourceId, { aiInsights: insights });
      },

      setBriefing: (sessionId, briefing) => {
        get().updateSession(sessionId, { overallBriefing: briefing });
      },

      setKnowledgeGraph: (sessionId, graph) => {
        get().updateSession(sessionId, { knowledgeGraph: graph });
      },

      setTimeline: (sessionId, events) => {
        get().updateSession(sessionId, { timeline: events });
      },

      addComparison: (sessionId, comparison) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? { ...s, comparisons: [...s.comparisons, comparison], updatedAt: isoNow() }
              : s
          ),
        }));
      },

      addReport: (sessionId, report) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? { ...s, reports: [...s.reports, report], updatedAt: isoNow() }
              : s
          ),
        }));
      },

      addChatMessage: (sessionId, sourceId, message) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? {
                  ...s,
                  sources: s.sources.map(src =>
                    src.id === sourceId
                      ? { ...src, chatHistory: [...src.chatHistory, message] }
                      : src
                  ),
                  updatedAt: isoNow(),
                }
              : s
          ),
        }));
      },

      createCollection: (sessionId, name) => {
        const id = generateId();
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? {
                  ...s,
                  collections: [...s.collections, {
                    id, name, sourceIds: [], createdAt: isoNow(), updatedAt: isoNow(),
                  }],
                  updatedAt: isoNow(),
                }
              : s
          ),
        }));
        return id;
      },

      deleteCollection: (sessionId, collectionId) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? { ...s, collections: s.collections.filter(c => c.id !== collectionId), updatedAt: isoNow() }
              : s
          ),
        }));
      },

      renameCollection: (sessionId, collectionId, name) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? {
                  ...s,
                  collections: s.collections.map(c =>
                    c.id === collectionId ? { ...c, name, updatedAt: isoNow() } : c
                  ),
                  updatedAt: isoNow(),
                }
              : s
          ),
        }));
      },

      addToCollection: (sessionId, collectionId, sourceId) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? {
                  ...s,
                  collections: s.collections.map(c =>
                    c.id === collectionId && !c.sourceIds.includes(sourceId)
                      ? { ...c, sourceIds: [...c.sourceIds, sourceId], updatedAt: isoNow() }
                      : c
                  ),
                  sources: s.sources.map(src =>
                    src.id === sourceId && !src.collectionIds.includes(collectionId)
                      ? { ...src, collectionIds: [...src.collectionIds, collectionId] }
                      : src
                  ),
                  updatedAt: isoNow(),
                }
              : s
          ),
        }));
      },

      removeFromCollection: (sessionId, collectionId, sourceId) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? {
                  ...s,
                  collections: s.collections.map(c =>
                    c.id === collectionId
                      ? { ...c, sourceIds: c.sourceIds.filter(id => id !== sourceId), updatedAt: isoNow() }
                      : c
                  ),
                  sources: s.sources.map(src =>
                    src.id === sourceId
                      ? { ...src, collectionIds: src.collectionIds.filter(id => id !== collectionId) }
                      : src
                  ),
                  updatedAt: isoNow(),
                }
              : s
          ),
        }));
      },

      setActiveTab: (sessionId, tab) => {
        get().updateSession(sessionId, { activeTab: tab });
      },

      setWorkspaceLayout: (sessionId, layout) => {
        get().updateSession(sessionId, {
          workspaceLayout: layout,
          workspacePanes: getDefaultPanes(layout),
        });
      },

      updatePane: (sessionId, paneId, updates) => {
        set(state => ({
          sessions: state.sessions.map(s =>
            s.id === sessionId
              ? {
                  ...s,
                  workspacePanes: s.workspacePanes.map(p => p.id === paneId ? { ...p, ...updates } : p),
                  updatedAt: isoNow(),
                }
              : s
          ),
        }));
      },

      setPaneSource: (sessionId, paneId, sourceId) => {
        get().updatePane(sessionId, paneId, { sourceId, contentType: 'source' });
      },

      setPaneContentType: (sessionId, paneId, contentType) => {
        get().updatePane(sessionId, paneId, { contentType });
      },
    }),
    {
      name: 'ai-research-workspace',
      partialize: (state) => ({
        sessions: state.sessions,
        activeSessionId: state.activeSessionId,
      }),
    }
  )
);
