'use client';
// src/app/page.tsx — Main chat application page

import { motion } from 'framer-motion';
import { Search } from 'lucide-react';
import { useAuthStore } from '@/store/auth';
import { useUIStore } from '@/store/ui';
import { useShortcutLabel } from '@/hooks/useKeyboard';
import Sidebar from '@/components/layout/Sidebar';
import ChatInterface from '@/components/chat/ChatInterface';

export default function HomePage() {
  const { isLoading } = useAuthStore();
  const { setCommandPaletteOpen } = useUIStore();
  const shortcut = useShortcutLabel();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-dvh" style={{ background: 'var(--bg-base)' }}>
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
    <div className="flex flex-col md:flex-row h-dvh overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      <Sidebar />

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="hidden md:flex flex-shrink-0 items-center justify-between gap-4 px-5 h-14"
          style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-elevated)' }}>
          <div className="flex items-baseline gap-2 min-w-0 text-sm">
            <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>AI Chat</span>
            <span className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
              Answers from your libraries and the web, using your configured model (Ollama or Groq)
            </span>
          </div>

          <button
            onClick={() => setCommandPaletteOpen(true)}
            className="flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-xl text-xs font-medium transition-colors hover:bg-[var(--bg-hover)] flex-shrink-0"
            style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
            aria-label="Open command palette"
          >
            <Search className="w-3.5 h-3.5" />
            <span>Jump to…</span>
            <kbd className="text-[10px] px-1.5 py-0.5 rounded font-mono" style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}>
              {shortcut}
            </kbd>
          </button>
        </header>

        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1 min-h-0 overflow-hidden">
          <ChatInterface />
        </motion.div>
      </div>
    </div>
  );
}
