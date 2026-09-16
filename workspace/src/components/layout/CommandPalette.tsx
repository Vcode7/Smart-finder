'use client';

import { useEffect, useCallback } from 'react';
import { Command } from 'cmdk';
import { AnimatePresence, motion } from 'framer-motion';
import { useUIStore } from '@/store/ui';
import { useResearchStore } from '@/store/research';
import { useRouter } from 'next/navigation';
import {
  Search, FileText, Video, Globe, BookOpen, Plus,
  Moon, Sun, Bookmark, Layers, Settings,
} from 'lucide-react';

export function CommandPalette() {
  const { commandPaletteOpen, setCommandPaletteOpen, theme, setTheme } = useUIStore();
  const { sessions } = useResearchStore();
  const router = useRouter();

  const close = useCallback(() => setCommandPaletteOpen(false), [setCommandPaletteOpen]);

  const go = useCallback((path: string) => {
    router.push(path);
    close();
  }, [router, close]);

  return (
    <AnimatePresence>
      {commandPaletteOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 px-4">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0"
            style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
            onClick={close}
          />

          {/* Panel */}
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -8 }}
            transition={{ type: 'spring', bounce: 0.15, duration: 0.25 }}
            className="relative w-full max-w-lg rounded-xl overflow-hidden shadow-2xl"
            style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
          >
            <Command className="w-full" label="Command Palette" shouldFilter>
              {/* Input */}
              <div className="flex items-center gap-3 px-4 border-b" style={{ borderColor: 'var(--border)' }}>
                <Search className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--text-muted)' }} />
                <Command.Input
                  placeholder="Search sessions, actions..."
                  className="flex-1 py-3.5 bg-transparent text-sm outline-none"
                  style={{ color: 'var(--text-primary)' }}
                  autoFocus
                />
                <kbd
                  className="text-xs px-1.5 py-0.5 rounded font-mono"
                  style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}
                >
                  Esc
                </kbd>
              </div>

              {/* Results */}
              <Command.List className="max-h-80 overflow-y-auto p-2">
                <Command.Empty className="py-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
                  No results found
                </Command.Empty>

                {/* Actions */}
                <Command.Group heading={
                  <span className="text-xs font-medium px-2 py-1 block" style={{ color: 'var(--text-muted)' }}>Actions</span>
                }>
                  <CmdItem icon={Plus} label="New Research" onSelect={() => go('/')} />
                  <CmdItem
                    icon={theme === 'dark' ? Sun : Moon}
                    label={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
                    onSelect={() => { setTheme(theme === 'dark' ? 'light' : 'dark'); close(); }}
                  />
                </Command.Group>

                {/* Recent sessions */}
                {sessions.length > 0 && (
                  <Command.Group heading={
                    <span className="text-xs font-medium px-2 py-1 block" style={{ color: 'var(--text-muted)' }}>Recent Research</span>
                  }>
                    {sessions.slice(0, 6).map((session) => (
                      <CmdItem
                        key={session.id}
                        icon={BookOpen}
                        label={session.topic}
                        subtitle={`${session.sources.length} sources`}
                        onSelect={() => go(`/research/${session.id}`)}
                      />
                    ))}
                  </Command.Group>
                )}
              </Command.List>

              {/* Footer */}
              <div className="flex items-center gap-4 px-4 py-2 border-t" style={{ borderColor: 'var(--border)' }}>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  <kbd className="font-mono">↑↓</kbd> navigate · <kbd className="font-mono">↵</kbd> select · <kbd className="font-mono">Esc</kbd> close
                </span>
              </div>
            </Command>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

function CmdItem({
  icon: Icon, label, subtitle, onSelect,
}: {
  icon: React.ElementType;
  label: string;
  subtitle?: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer text-sm transition-colors data-[selected]:bg-[var(--bg-active)]"
      style={{ color: 'var(--text-primary)' }}
    >
      <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'var(--bg-base)' }}>
        <Icon className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
      </div>
      <div className="flex-1 min-w-0">
        <span className="truncate block">{label}</span>
        {subtitle && <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{subtitle}</span>}
      </div>
    </Command.Item>
  );
}
