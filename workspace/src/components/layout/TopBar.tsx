'use client';

import { motion } from 'framer-motion';
import { useUIStore } from '@/store/ui';
import { useResearchStore } from '@/store/research';
import { useRouter } from 'next/navigation';
import {
  Moon, Sun, Search, Download, Layers, ArrowLeft, Sparkles, Command,
  PanelLeft, PanelLeftClose, Zap, Share2
} from 'lucide-react';
import type { ResearchSession } from '@/types/research';

interface TopBarProps {
  session: ResearchSession | null;
}

export function TopBar({ session }: TopBarProps) {
  const { theme, setTheme, sidebarOpen, toggleSidebar, setCommandPaletteOpen, setWorkspaceModalOpen } = useUIStore();
  const router = useRouter();

  const toggleTheme = () => setTheme(theme === 'dark' ? 'light' : 'dark');

  return (
    <header
      className="flex items-center justify-between px-4 border-b flex-shrink-0 z-30 sticky top-0 backdrop-blur-xl"
      style={{
        height: 'var(--topbar-height)',
        background: 'var(--glass-bg)',
        borderColor: 'var(--border)',
      }}
    >
      {/* Left section: Sidebar toggle + Back + Breadcrumb */}
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <button
          onClick={toggleSidebar}
          className="p-1.5 rounded-lg transition-all hover:bg-[var(--bg-hover)]"
          style={{ color: 'var(--text-secondary)', border: '1px solid var(--border)' }}
          title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
        >
          {sidebarOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeft className="w-4 h-4" />}
        </button>

        <button
          onClick={() => router.push('/')}
          className="p-1.5 rounded-lg transition-all hover:bg-[var(--bg-hover)]"
          style={{ color: 'var(--text-secondary)' }}
          title="Return to Home"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>

        {session && (
          <div className="flex items-center gap-2 min-w-0 pr-4">
            <div className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 shadow-sm shadow-indigo-500/20" style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }}>
              <Sparkles className="w-3.5 h-3.5 text-white" />
            </div>

            <div className="min-w-0">
              <h1 className="text-xs sm:text-sm font-semibold truncate leading-tight" style={{ color: 'var(--text-primary)' }}>
                {session.topic}
              </h1>
            </div>

            <div className="hidden md:flex items-center gap-1.5 flex-shrink-0 ml-1">
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full flex items-center gap-1" style={{ background: 'var(--accent-muted)', color: 'var(--accent)' }}>
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
                {session.sources.length} sources
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full flex items-center gap-1" style={{ background: 'rgba(16, 185, 129, 0.12)', color: '#10b981' }}>
                <Zap className="w-2.5 h-2.5" />
                Groq Qwen 3.6 27B
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Right section: Multi-View button, Command palette, theme toggle */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {session && (
          <button
            onClick={() => setWorkspaceModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition-all hover:scale-105 shadow-sm"
            style={{
              background: 'linear-gradient(135deg, rgba(99,102,241,0.2) 0%, rgba(168,85,247,0.2) 100%)',
              border: '1px solid rgba(99,102,241,0.4)',
              color: 'var(--text-primary)',
            }}
            title="Launch Full-Screen Multi-View Workspace (2×2)"
          >
            <Layers className="w-3.5 h-3.5 text-indigo-400" />
            <span className="hidden sm:inline">Multi-View (2×2)</span>
          </button>
        )}

        <button
          onClick={() => setCommandPaletteOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-medium transition-all hover:border-indigo-500/40"
          style={{
            color: 'var(--text-secondary)',
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)'
          }}
        >
          <Command className="w-3.5 h-3.5" style={{ color: 'var(--accent)' }} />
          <span className="hidden sm:inline">Search</span>
          <kbd className="text-[10px] font-mono px-1 py-0.5 rounded" style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}>⌘K</kbd>
        </button>

        <button
          onClick={toggleTheme}
          className="p-2 rounded-xl transition-all hover:bg-[var(--bg-hover)]"
          style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
          aria-label="Toggle Theme"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-indigo-500" />}
        </button>
      </div>
    </header>
  );
}
