// src/components/workspace/FullScreenWorkspace.tsx
// Dedicated Full-Screen 2x2 Multi-View Research Workspace Overlay with Framer Motion and Esc Handler

'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useResearchStore } from '@/store/research';
import { useUIStore } from '@/store/ui';
import { SourcePane } from './SourcePane';
import {
  X, Maximize2, Minimize2, Grid2X2, Columns2, Columns3,
  Square, Zap, Layers, Sparkles, Moon, Sun
} from 'lucide-react';
import type { ResearchSession, WorkspaceLayout, WorkspacePane as WorkspacePaneType } from '@/types/research';

const LAYOUT_OPTIONS: Array<{ value: WorkspaceLayout; label: string; icon: React.ElementType; desc: string }> = [
  { value: '4', label: '2×2 Quad Matrix (4 Panes)', icon: Grid2X2, desc: 'Default 2×2 grid' },
  { value: '2', label: 'Dual View (2 Panes)', icon: Columns2, desc: 'Side-by-side comparison' },
  { value: '3', label: 'Triple View (3 Panes)', icon: Columns3, desc: '3-column analysis' },
  { value: '1', label: 'Single Focus (1 Pane)', icon: Square, desc: 'Focused full viewport' },
];

interface FullScreenWorkspaceProps {
  session: ResearchSession;
  sessionId: string;
  onClose: () => void;
}

export function FullScreenWorkspace({ session, sessionId, onClose }: FullScreenWorkspaceProps) {
  const { setWorkspaceLayout, updatePane } = useResearchStore();
  const { theme, setTheme } = useUIStore();
  const layout = session.workspaceLayout || '4';
  const panes = session.workspacePanes || [];

  // Check if any pane is currently maximized
  const maximizedPane = panes.find((p) => p.isMaximized);

  // Lock body scroll and register Escape key listener
  useEffect(() => {
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (maximizedPane) {
          // If a pane is maximized, ESC restores 2x2 first
          updatePane(sessionId, maximizedPane.id, { isMaximized: false });
        } else {
          onClose();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [onClose, maximizedPane, sessionId, updatePane]);

  // Determine grid layout classes
  const getGridClasses = () => {
    if (maximizedPane) return 'grid-cols-1 grid-rows-1';
    switch (layout) {
      case '1':
        return 'grid-cols-1 grid-rows-1';
      case '2':
        return 'grid-cols-1 md:grid-cols-2 grid-rows-1';
      case '3':
        return 'grid-cols-1 md:grid-cols-3 grid-rows-1';
      case '4':
      default:
        return 'grid-cols-1 md:grid-cols-2 grid-rows-2';
    }
  };

  const displayedPanes = maximizedPane
    ? [maximizedPane]
    : panes.slice(0, parseInt(layout, 10) || 4);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.98 }}
        transition={{ type: 'spring', bounce: 0, duration: 0.25 }}
        className="fixed inset-0 z-50 flex flex-col overflow-hidden backdrop-blur-3xl"
        style={{
          background: 'var(--bg-base)',
          color: 'var(--text-primary)',
        }}
      >
        {/* Full-Screen Workspace Header Bar */}
        <header
          className="flex-shrink-0 flex items-center justify-between px-4 sm:px-6 py-2.5 border-b backdrop-blur-2xl z-30"
          style={{
            background: 'var(--glass-bg)',
            borderColor: 'var(--border)',
          }}
        >
          {/* Left: Branding & Topic info */}
          <div className="flex items-center gap-3 min-w-0">
            <div
              className="w-8 h-8 rounded-xl flex items-center justify-center shadow-md shadow-indigo-500/25 flex-shrink-0"
              style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}
            >
              <Grid2X2 className="w-4 h-4 text-white" />
            </div>

            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-extrabold text-xs sm:text-sm tracking-tight truncate">
                  Multi-View Intelligence Workspace
                </span>
                <span
                  className="hidden md:inline-flex text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full"
                  style={{ background: 'var(--accent-muted)', color: 'var(--accent)' }}
                >
                  {session.sources.length} sources
                </span>
                <span
                  className="hidden lg:inline-flex text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full"
                  style={{ background: 'rgba(16, 185, 129, 0.12)', color: '#10b981' }}
                >
                  <Zap className="w-2.5 h-2.5 mr-1" />
                  Groq Qwen 3.6 27B
                </span>
              </div>
              <p className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }}>
                {session.topic}
              </p>
            </div>
          </div>

          {/* Center: Layout Controls (Hidden if pane is maximized) */}
          {!maximizedPane && (
            <div
              className="hidden sm:flex items-center p-1 rounded-xl border gap-1"
              style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
            >
              {LAYOUT_OPTIONS.map((opt) => {
                const Icon = opt.icon;
                const isActive = layout === opt.value;
                return (
                  <button
                    key={opt.value}
                    onClick={() => setWorkspaceLayout(sessionId, opt.value)}
                    className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                      isActive ? 'shadow-sm text-white' : 'hover:text-white'
                    }`}
                    title={opt.desc}
                    style={{
                      background: isActive ? 'var(--accent)' : 'transparent',
                      color: isActive ? '#ffffff' : 'var(--text-muted)',
                    }}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    <span>{opt.value === '4' ? '2×2 Grid' : `${opt.value} Panes`}</span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Right: Maximized indicator + Theme + Exit Button */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {maximizedPane && (
              <button
                onClick={() => updatePane(sessionId, maximizedPane.id, { isMaximized: false })}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition-all shadow-sm"
                style={{ background: 'var(--accent-muted)', color: 'var(--accent)', border: '1px solid var(--accent)' }}
              >
                <Minimize2 className="w-3.5 h-3.5" />
                <span>Restore 2×2 Layout</span>
              </button>
            )}

            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-xl transition-all hover:bg-[var(--bg-hover)]"
              style={{ border: '1px solid var(--border)', color: 'var(--text-muted)' }}
              aria-label="Toggle Theme"
            >
              {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-indigo-500" />}
            </button>

            {/* Prominent Exit Button */}
            <button
              onClick={onClose}
              className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all hover:bg-rose-500/15 hover:border-rose-500/40 hover:text-rose-400 shadow-sm"
              style={{
                background: 'var(--bg-elevated)',
                borderColor: 'var(--border)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border)',
              }}
              title="Exit Full-Screen Workspace (Esc)"
            >
              <X className="w-4 h-4" />
              <span>Exit Workspace</span>
              <kbd className="text-[10px] px-1.5 py-0.5 rounded font-mono font-bold ml-0.5" style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}>
                ESC
              </kbd>
            </button>
          </div>
        </header>

        {/* Full-Screen Pane Grid (2x2 equal viewport fill) */}
        <main className="flex-1 p-2 overflow-hidden">
          <div className={`grid h-full w-full gap-2 ${getGridClasses()}`}>
            {displayedPanes.map((pane) => (
              <SourcePane
                key={pane.id}
                pane={pane}
                session={session}
                sessionId={sessionId}
                isFullScreen
              />
            ))}
          </div>
        </main>
      </motion.div>
    </AnimatePresence>
  );
}
