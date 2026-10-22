'use client';
// src/components/layout/CommandPalette.tsx — Ctrl/Cmd+K: go to a page, run an action or reopen a chat

import { useCallback } from 'react';
import { Command } from 'cmdk';
import { AnimatePresence, motion } from 'framer-motion';
import { useRouter } from 'next/navigation';
import {
  Search, Plus, Moon, Sun, Settings, MessageSquare, Database, Library, Users, FolderCog, UserCog,
} from 'lucide-react';
import { useUIStore } from '@/store/ui';
import { useChatStore } from '@/store/chat';
import { useAuthStore } from '@/store/auth';
import { useKeyboard } from '@/hooks/useKeyboard';

export function CommandPalette() {
  const { commandPaletteOpen, setCommandPaletteOpen, theme, setTheme, setSettingsModalOpen } = useUIStore();
  const { chats, setActiveChatId, startNewChat } = useChatStore();
  const { user } = useAuthStore();
  const router = useRouter();
  useKeyboard(Boolean(user));

  const close = useCallback(() => setCommandPaletteOpen(false), [setCommandPaletteOpen]);
  const go = useCallback((path: string) => {
    router.push(path);
    close();
  }, [router, close]);

  // Signed-out pages (login/signup) have nothing to navigate to
  if (!user) return null;

  const pages = [
    { path: '/', label: 'Chat', icon: MessageSquare },
    { path: '/search', label: 'Smart Finder search', icon: Search, keywords: ['find', 'image', 'face', 'voice'] },
    { path: '/knowledge', label: 'Knowledge Base', icon: Database, keywords: ['documents', 'files'] },
    { path: '/libraries', label: 'Libraries & Uploads', icon: Library, keywords: ['folders', 'indexing', 'upload'] },
    { path: '/people', label: 'People', icon: Users, keywords: ['faces', 'names'] },
    ...(user.role === 'admin' ? [
      { path: '/admin', label: 'Repository', icon: FolderCog, keywords: ['scrape', 'internet', 'inventory'] },
      { path: '/admin/users', label: 'Users', icon: UserCog, keywords: ['accounts', 'admin', 'share', 'access'] },
    ] : []),
  ];

  return (
    <AnimatePresence>
      {commandPaletteOpen && (
        <div className="fixed inset-0 z-[60] flex items-start justify-center pt-[12vh] px-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0"
            style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(4px)' }}
            onClick={close}
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.97, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -8 }}
            transition={{ type: 'spring', bounce: 0.15, duration: 0.25 }}
            className="relative w-full max-w-lg rounded-2xl overflow-hidden shadow-2xl"
            style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
          >
            <Command className="w-full" label="Command palette" loop>
              <div className="flex items-center gap-3 px-4 border-b" style={{ borderColor: 'var(--border)' }}>
                <Search className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--text-muted)' }} />
                <Command.Input
                  placeholder="Go to a page, run an action or find a chat…"
                  className="flex-1 py-3.5 bg-transparent text-sm outline-none"
                  style={{ color: 'var(--text-primary)' }}
                  autoFocus
                />
                <kbd className="text-xs px-1.5 py-0.5 rounded font-mono"
                  style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}>
                  Esc
                </kbd>
              </div>

              <Command.List className="max-h-[min(60vh,420px)] overflow-y-auto p-2">
                <Command.Empty className="py-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
                  No results found
                </Command.Empty>

                <Group heading="Actions">
                  <CmdItem icon={Plus} label="New chat" onSelect={() => { startNewChat(); go('/'); }} />
                  <CmdItem icon={Settings} label="Settings" keywords={['password', 'model', 'ollama']}
                    onSelect={() => { close(); setSettingsModalOpen(true); }} />
                  <CmdItem
                    icon={theme === 'dark' ? Sun : Moon}
                    label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
                    keywords={['theme']}
                    onSelect={() => { setTheme(theme === 'dark' ? 'light' : 'dark'); close(); }}
                  />
                </Group>

                <Group heading="Go to">
                  {pages.map((p) => (
                    <CmdItem key={p.path} icon={p.icon} label={p.label} keywords={p.keywords} onSelect={() => go(p.path)} />
                  ))}
                </Group>

                {chats.length > 0 && (
                  <Group heading="Recent chats">
                    {chats.slice(0, 8).map((chat) => (
                      <CmdItem
                        key={chat.id}
                        value={`chat-${chat.id} ${chat.title}`}
                        icon={MessageSquare}
                        label={chat.title}
                        onSelect={() => { setActiveChatId(chat.id); go('/'); }}
                      />
                    ))}
                  </Group>
                )}
              </Command.List>

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

function Group({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <Command.Group
      heading={heading}
      className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-[var(--text-muted)]"
    >
      {children}
    </Command.Group>
  );
}

function CmdItem({
  icon: Icon, label, value, keywords, onSelect,
}: {
  icon: React.ElementType;
  label: string;
  value?: string;
  keywords?: string[];
  onSelect: () => void;
}) {
  return (
    <Command.Item
      value={value ?? label}
      keywords={keywords}
      onSelect={onSelect}
      className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer text-sm transition-colors data-[selected=true]:bg-[var(--bg-active)]"
      style={{ color: 'var(--text-primary)' }}
    >
      <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'var(--bg-base)' }}>
        <Icon className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
      </div>
      <span className="truncate">{label}</span>
    </Command.Item>
  );
}
