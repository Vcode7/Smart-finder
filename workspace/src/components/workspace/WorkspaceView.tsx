// src/components/workspace/WorkspaceView.tsx
// Workspace Launch Card and Full-Screen Workspace Trigger

'use client';

import { useResearchStore } from '@/store/research';
import { useUIStore } from '@/store/ui';
import { Grid2X2, Maximize2, Zap, Video, BookOpen, GitBranch, Sparkles } from 'lucide-react';
import type { ResearchSession } from '@/types/research';

interface WorkspaceViewProps {
  session: ResearchSession;
  sessionId: string;
}

export function WorkspaceView({ session, sessionId }: WorkspaceViewProps) {
  const { setWorkspaceModalOpen } = useUIStore();

  return (
    <div
      className="rounded-3xl p-8 sm:p-12 text-center border shadow-xl relative overflow-hidden"
      style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
    >
      <div className="absolute top-0 right-0 w-72 h-72 rounded-full blur-3xl opacity-20 pointer-events-none" style={{ background: 'var(--accent)' }} />

      <div
        className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5 shadow-lg shadow-indigo-500/25"
        style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}
      >
        <Grid2X2 className="w-8 h-8 text-white" />
      </div>

      <h3 className="text-xl sm:text-2xl font-extrabold mb-2" style={{ color: 'var(--text-primary)' }}>
        Multi-View Intelligence Workspace
      </h3>

      <p className="text-xs sm:text-sm max-w-xl mx-auto mb-8 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
        Open a dedicated 2×2 full-screen quad workspace. Simultaneously analyze AI Briefings, Video Lectures, Academic Papers, and Research Timelines with independent pane controls.
      </p>

      {/* 2x2 Default Panes Preview Showcase */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-2xl mx-auto mb-8 text-left">
        {[
          { label: 'Pane 1: AI Insights', icon: Zap, color: '#a855f7', desc: 'Qwen 3.6 Synthesis' },
          { label: 'Pane 2: Video Lecture', icon: Video, color: '#f43f5e', desc: 'Video & Transcripts' },
          { label: 'Pane 3: Academic Paper', icon: BookOpen, color: '#06b6d4', desc: 'Abstracts & Findings' },
          { label: 'Pane 4: Research Timeline', icon: GitBranch, color: '#10b981', desc: 'Chronological Nodes' },
        ].map((item, idx) => {
          const Icon = item.icon;
          return (
            <div
              key={idx}
              className="p-3.5 rounded-2xl border text-xs relative overflow-hidden"
              style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <Icon className="w-4 h-4" style={{ color: item.color }} />
                <span className="font-bold text-[11px] truncate" style={{ color: 'var(--text-primary)' }}>
                  {item.label}
                </span>
              </div>
              <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{item.desc}</p>
            </div>
          );
        })}
      </div>

      {/* Launch Button */}
      <button
        onClick={() => setWorkspaceModalOpen(true)}
        className="inline-flex items-center gap-2.5 px-8 py-3.5 rounded-2xl font-bold text-sm text-white shadow-xl shadow-indigo-500/25 transition-all hover:scale-105 active:scale-95"
        style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}
      >
        <Maximize2 className="w-4 h-4" />
        <span>Launch Full-Screen Multi-View (2×2)</span>
      </button>
    </div>
  );
}
