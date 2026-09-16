'use client';
// src/app/page.tsx — Main chat application page (redesigned)

import { useEffect } from 'react';
import { motion } from 'framer-motion';
import { useAuthStore } from '@/store/auth';
import Sidebar from '@/components/layout/Sidebar';
import ChatInterface from '@/components/chat/ChatInterface';
import { Sun, Moon, Command } from 'lucide-react';
import { useUIStore } from '@/store/ui';
import { useKeyboard } from '@/hooks/useKeyboard';

export default function HomePage() {
  const { user, isLoading } = useAuthStore();
  const { theme, setTheme, setCommandPaletteOpen } = useUIStore();
  useKeyboard();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen" style={{ background: 'var(--bg-base)' }}>
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}>
            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          </div>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Loading Smart Finder...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      {/* Sidebar */}
      <Sidebar />

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top bar */}
        <header className="flex-shrink-0 flex items-center justify-between px-5 py-3"
          style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-elevated)' }}>
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
            <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>AI Chat</span>
            <span>—</span>
            <span className="text-xs">Powered by Groq Qwen 3.6 27B</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setCommandPaletteOpen(true)}
              className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium transition-all hover:border-indigo-500/40"
              style={{ background: 'var(--bg-surface, var(--bg-base))', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
            >
              <Command className="w-3.5 h-3.5" style={{ color: 'var(--accent)' }} />
              <span>Search</span>
              <kbd className="text-[10px] px-1.5 py-0.5 rounded font-mono" style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}>⌘K</kbd>
            </button>

            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-medium transition-all hover:bg-[var(--bg-hover)] cursor-pointer"
              style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'var(--bg-surface, var(--bg-base))' }}
              title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
              aria-label="Toggle Theme"
            >
              {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-indigo-500" />}
              <span className="hidden sm:inline font-medium text-[11px]">{theme === 'dark' ? 'Light Mode' : 'Dark Mode'}</span>
            </button>
          </div>
        </header>

        {/* Chat Area */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex-1 min-h-0 overflow-hidden"
        >
          <ChatInterface />
        </motion.div>
      </div>
    </div>
  );
}
