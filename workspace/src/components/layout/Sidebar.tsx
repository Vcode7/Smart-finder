'use client';
// src/components/layout/Sidebar.tsx — app navigation, chat and search history, theme, settings and account.
// Desktop: a column that collapses to icons (remembered across pages). Phones: a top bar
// with a menu button that opens the same content as a drawer.

import { useState, useEffect, useSyncExternalStore } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  Sparkles, Plus, MessageSquare, Trash2, Pencil, Check, X, LogOut, User, Shield,
  PanelLeftClose, PanelLeftOpen, Globe, Database, Layers, Search, Sun, Moon, Settings,
  Library, Users, Menu, FolderCog, UserCog, History,
} from 'lucide-react';
import { useAuthStore } from '@/store/auth';
import { useChatStore, type ChatSummary } from '@/store/chat';
import { useSearchHistoryStore, type SearchHistoryItem } from '@/store/searchHistory';
import { useUIStore } from '@/store/ui';
import { SettingsModal } from '@/components/modals/SettingsModal';
import { toast } from 'sonner';
import { formatDistanceToNow } from '@/lib/utils/date';

const DESKTOP_QUERY = '(min-width: 768px)';

function useIsDesktop(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia(DESKTOP_QUERY);
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    },
    () => window.matchMedia(DESKTOP_QUERY).matches,
    () => true,
  );
}

/** Chats or searches bucketed by their last activity, newest bucket first. */
function groupByRecency<T extends { updatedAt: string }>(entries: T[]): { label: string; items: T[] }[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const DAY = 86_400_000;
  const groups = [
    { label: 'Today', from: today.getTime(), items: [] as T[] },
    { label: 'Yesterday', from: today.getTime() - DAY, items: [] as T[] },
    { label: 'Previous 7 days', from: today.getTime() - 7 * DAY, items: [] as T[] },
    { label: 'Older', from: -Infinity, items: [] as T[] },
  ];
  for (const entry of entries) {
    const t = new Date(entry.updatedAt).getTime();
    (groups.find((g) => t >= g.from) || groups[3]).items.push(entry);
  }
  return groups.filter((g) => g.items.length > 0);
}

const MODE_ICON = {
  local: { icon: Database, color: 'var(--accent)', label: 'Local sources' },
  internet: { icon: Globe, color: 'var(--accent-emerald)', label: 'Internet sources' },
  both: { icon: Layers, color: 'var(--accent-ai)', label: 'Local and internet sources' },
} as const;

const CATALOG_NAME: Record<string, string> = { koha: 'Koha', dspace: 'DSpace' };

export function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const isDesktop = useIsDesktop();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');

  const { user, logout } = useAuthStore();
  const { theme, setTheme, setSettingsModalOpen, sidebarOpen, toggleSidebar } = useUIStore();
  const {
    chats, activeChatId, setActiveChatId, updateChatTitle, removeChat, refreshChats, startNewChat,
  } = useChatStore();

  const {
    searches, refresh: refreshSearches, remove: removeSearch, clear: clearSearches, runAgain,
  } = useSearchHistoryStore();
  // The history list shows either chats or Smart Finder searches
  const [listTab, setListTab] = useState<'chats' | 'searches'>('chats');

  const isAdmin = user?.role === 'admin';
  // Icon-only mode exists on desktop; the phone drawer always shows labels
  const collapsed = isDesktop && !sidebarOpen;

  useEffect(() => {
    refreshChats();
  }, [refreshChats]);

  useEffect(() => {
    refreshSearches();
  }, [refreshSearches]);

  // Escape closes the phone drawer
  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMobileOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mobileOpen]);

  const go = (path: string) => {
    setMobileOpen(false);
    if (pathname !== path) router.push(path);
  };

  const handleNewChat = () => {
    startNewChat();
    go('/');
  };

  // ChatInterface loads the messages and saved sources of the active chat
  const openChat = (chatId: string) => {
    if (chatId !== activeChatId) setActiveChatId(chatId);
    go('/');
  };

  const handleDelete = async (chat: ChatSummary) => {
    if (!window.confirm(`Delete “${chat.title}”? Its messages and sources are removed for good.`)) return;
    try {
      const res = await fetch(`/api/chats/${chat.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error();
      removeChat(chat.id);
      toast.success('Chat deleted');
    } catch {
      toast.error('Failed to delete chat');
    }
  };

  const openSearch = (item: SearchHistoryItem) => {
    runAgain(item);
    go('/search');
  };

  const handleDeleteSearch = async (item: SearchHistoryItem) => {
    try {
      await removeSearch(item.id);
    } catch {
      toast.error('Failed to delete search');
    }
  };

  const handleClearSearches = async () => {
    if (!window.confirm('Clear your whole search history?')) return;
    try {
      await clearSearches();
      toast.success('Search history cleared');
    } catch {
      toast.error('Failed to clear search history');
    }
  };

  const handleRename = async (chatId: string) => {
    const title = editTitle.trim();
    if (!title) { setEditingId(null); return; }
    try {
      const res = await fetch(`/api/chats/${chatId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      });
      if (!res.ok) throw new Error();
      updateChatTitle(chatId, title);
      setEditingId(null);
    } catch {
      toast.error('Failed to rename chat');
    }
  };

  const nav = [
    { path: '/', label: 'Chat', icon: MessageSquare },
    { path: '/search', label: 'Smart Finder', icon: Search },
    { path: '/knowledge', label: 'Knowledge Base', icon: Database },
    { path: '/libraries', label: 'Libraries & Uploads', icon: Library },
    { path: '/people', label: 'People', icon: Users },
    ...(isAdmin ? [
      { path: '/admin', label: 'Repository', icon: FolderCog },
      { path: '/admin/users', label: 'Users', icon: UserCog },
    ] : []),
  ];

  return (
    <>
      {/* Phone top bar */}
      <div
        className="md:hidden flex items-center gap-2 h-12 px-2 flex-shrink-0"
        style={{ background: 'var(--bg-elevated)', borderBottom: '1px solid var(--border)' }}
      >
        <button onClick={() => setMobileOpen(true)} aria-label="Open menu" aria-expanded={mobileOpen}
          className="p-2 rounded-lg hover:bg-[var(--bg-hover)]" style={{ color: 'var(--text-secondary)' }}>
          <Menu className="w-5 h-5" />
        </button>
        <Logo />
        <span className="font-bold text-sm flex-1 truncate" style={{ color: 'var(--text-primary)' }}>
          {nav.find((n) => n.path === pathname)?.label || 'Smart Finder'}
        </span>
        <button onClick={handleNewChat} aria-label="New chat"
          className="p-2 rounded-lg hover:bg-[var(--bg-hover)]" style={{ color: 'var(--accent)' }}>
          <Plus className="w-5 h-5" />
        </button>
      </div>

      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-40 bg-black/50 backdrop-blur-[2px]"
          onClick={() => setMobileOpen(false)} aria-hidden />
      )}

      <aside
        aria-label="Main navigation"
        className={`fixed inset-y-0 left-0 z-50 w-[280px] flex flex-col overflow-hidden flex-shrink-0
          transition-[transform,width] duration-300 ease-out
          md:relative md:z-30 md:translate-x-0 md:w-[var(--sidebar-w)]
          ${mobileOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full'}`}
        style={{
          '--sidebar-w': collapsed ? '64px' : '272px',
          background: 'var(--bg-elevated)',
          borderRight: '1px solid var(--border)',
        } as React.CSSProperties}
      >
        {/* Header */}
        <div className={`flex items-center gap-3 h-14 flex-shrink-0 ${collapsed ? 'justify-center px-2' : 'px-4'}`}
          style={{ borderBottom: '1px solid var(--border)' }}>
          {!collapsed && (
            <>
              <Logo />
              <div className="flex-1 min-w-0 flex items-center gap-1.5">
                <span className="font-bold text-sm tracking-tight truncate" style={{ color: 'var(--text-primary)' }}>
                  Smart Finder
                </span>
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                  style={{ background: 'var(--accent-muted)', color: 'var(--accent)' }}>AI</span>
              </div>
            </>
          )}
          <button
            onClick={() => (isDesktop ? toggleSidebar() : setMobileOpen(false))}
            className="p-1.5 rounded-lg transition-colors hover:bg-[var(--bg-hover)] flex-shrink-0"
            style={{ color: 'var(--text-muted)' }}
            aria-label={!isDesktop ? 'Close menu' : collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={!isDesktop ? 'Close menu' : collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {!isDesktop ? <X className="w-4 h-4" />
              : collapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
          </button>
        </div>

        {/* New chat + navigation */}
        <div className="px-3 pt-3 pb-2 space-y-0.5 flex-shrink-0">
          <button
            onClick={handleNewChat}
            title={collapsed ? 'New chat' : undefined}
            aria-label={collapsed ? 'New chat' : undefined}
            className={`w-full flex items-center gap-2.5 px-3 py-2.5 mb-2 rounded-xl font-semibold text-sm text-white
              transition-[filter,transform] hover:brightness-110 active:scale-[0.98] ${collapsed ? 'justify-center' : ''}`}
            style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)', boxShadow: '0 4px 12px rgba(99,102,241,0.3)' }}
          >
            <Plus className="w-4 h-4 flex-shrink-0" />
            {!collapsed && <span>New Chat</span>}
          </button>

          <nav className="space-y-0.5">
            {nav.map((item) => {
              const active = pathname === item.path;
              const Icon = item.icon;
              return (
                <button
                  key={item.path}
                  onClick={() => go(item.path)}
                  aria-current={active ? 'page' : undefined}
                  title={collapsed ? item.label : undefined}
                  aria-label={collapsed ? item.label : undefined}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm font-medium transition-colors
                    ${collapsed ? 'justify-center' : ''} ${active ? '' : 'hover:bg-[var(--bg-hover)]'}`}
                  style={{
                    color: active ? 'var(--accent)' : 'var(--text-secondary)',
                    background: active ? 'var(--accent-muted)' : 'transparent',
                  }}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Chat history */}
        <div className="flex-1 overflow-y-auto px-3 pb-2 min-h-0" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          {!collapsed && (
            <div role="tablist" aria-label="History" className="flex gap-1 mt-3 p-0.5 rounded-xl"
              style={{ background: 'var(--bg-hover)' }}>
              {([['chats', 'Chats', MessageSquare], ['searches', 'Searches', History]] as const).map(([id, label, Icon]) => (
                <button key={id} role="tab" aria-selected={listTab === id} onClick={() => setListTab(id)}
                  className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-[11px] font-semibold transition-colors"
                  style={{
                    background: listTab === id ? 'var(--bg-elevated)' : 'transparent',
                    color: listTab === id ? 'var(--accent)' : 'var(--text-muted)',
                  }}>
                  <Icon className="w-3 h-3" />{label}
                </button>
              ))}
            </div>
          )}
          {!collapsed && listTab === 'searches' ? (
            searches.length === 0 ? (
              <div className="text-center py-8 px-4">
                <History className="w-8 h-8 mx-auto mb-2 opacity-30" style={{ color: 'var(--text-muted)' }} />
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  No searches yet. Your Smart Finder searches appear here.
                </p>
              </div>
            ) : (
              <>
                {groupByRecency(searches).map((group) => (
                  <div key={group.label} className="pt-3">
                    <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                      {group.label}
                    </p>
                    <ul className="space-y-0.5">
                      {group.items.map((item) => {
                        const mode = item.internet ? MODE_ICON.both : MODE_ICON.local;
                        const catalogs = (item.sources ?? []).map((s) => CATALOG_NAME[s]).filter(Boolean);
                        return (
                          <li key={item.id}
                            className="group relative flex items-center gap-1 rounded-xl transition-colors hover:bg-[var(--bg-hover)]">
                            <button onClick={() => openSearch(item)} title={`Search again: ${item.query}`}
                              className="flex-1 min-w-0 text-left px-3 py-2">
                              <span className="block text-xs font-medium truncate leading-5" style={{ color: 'var(--text-secondary)' }}>
                                {item.query}
                              </span>
                              <span className="flex items-center gap-1.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                                <mode.icon className="w-2.5 h-2.5" style={{ color: mode.color }} aria-label={mode.label} />
                                {item.resultCount} {item.resultCount === 1 ? 'result' : 'results'}
                                {catalogs.length > 0 && <> · <Library className="w-2.5 h-2.5" aria-hidden />{catalogs.join(', ')}</>}
                                {' '}· {formatDistanceToNow(item.updatedAt)}
                              </span>
                            </button>
                            <div className="pr-1.5 flex-shrink-0 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100 transition-opacity">
                              <button onClick={() => handleDeleteSearch(item)}
                                aria-label={`Delete search ${item.query}`} title="Delete"
                                className="p-1 rounded-lg hover:bg-red-500/15 hover:text-red-400" style={{ color: 'var(--text-muted)' }}>
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
                <button onClick={handleClearSearches}
                  className="w-full mt-3 py-1.5 rounded-lg text-[11px] font-medium hover:bg-[var(--bg-hover)] hover:text-red-400 transition-colors"
                  style={{ color: 'var(--text-muted)' }}>
                  Clear search history
                </button>
              </>
            )
          ) : collapsed ? (
            chats.slice(0, 8).map((chat) => (
              <button key={chat.id} onClick={() => openChat(chat.id)} title={chat.title} aria-label={chat.title}
                className={`w-full flex items-center justify-center p-2.5 rounded-xl my-0.5 transition-colors ${
                  activeChatId === chat.id ? 'bg-[var(--bg-active)]' : 'hover:bg-[var(--bg-hover)]'
                }`}>
                <MessageSquare className="w-4 h-4" style={{ color: activeChatId === chat.id ? 'var(--accent)' : 'var(--text-muted)' }} />
              </button>
            ))
          ) : chats.length === 0 ? (
            <div className="text-center py-8 px-4">
              <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-30" style={{ color: 'var(--text-muted)' }} />
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>No chats yet. Start a new one!</p>
            </div>
          ) : (
            groupByRecency(chats).map((group) => (
              <div key={group.label} className="pt-3">
                <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                  {group.label}
                </p>
                <ul className="space-y-0.5">
                  {group.items.map((chat) => {
                    const active = activeChatId === chat.id && pathname === '/';
                    const mode = MODE_ICON[chat.searchMode as keyof typeof MODE_ICON];
                    return (
                      <li key={chat.id}
                        className={`group relative flex items-center gap-1 rounded-xl transition-colors ${
                          active ? 'bg-[var(--bg-active)]' : 'hover:bg-[var(--bg-hover)]'
                        }`}>
                        {editingId === chat.id ? (
                          <form className="flex-1 flex items-center gap-1 px-2 py-2"
                            onSubmit={(e) => { e.preventDefault(); handleRename(chat.id); }}>
                            <input
                              value={editTitle}
                              onChange={(e) => setEditTitle(e.target.value)}
                              onKeyDown={(e) => { if (e.key === 'Escape') setEditingId(null); }}
                              autoFocus
                              aria-label="Chat title"
                              className="flex-1 min-w-0 text-xs bg-transparent outline-none border-b py-0.5"
                              style={{ borderColor: 'var(--accent)', color: 'var(--text-primary)' }}
                            />
                            <button type="submit" aria-label="Save title" className="p-1 rounded-md hover:bg-[var(--bg-active)]"
                              style={{ color: 'var(--success)' }}><Check className="w-3.5 h-3.5" /></button>
                            <button type="button" onClick={() => setEditingId(null)} aria-label="Cancel rename"
                              className="p-1 rounded-md hover:bg-[var(--bg-active)]" style={{ color: 'var(--text-muted)' }}>
                              <X className="w-3.5 h-3.5" /></button>
                          </form>
                        ) : (
                          <>
                            <button onClick={() => openChat(chat.id)} aria-current={active ? 'true' : undefined}
                              className="flex-1 min-w-0 text-left px-3 py-2">
                              <span className="block text-xs font-medium truncate leading-5"
                                style={{ color: active ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                                {chat.title}
                              </span>
                              <span className="flex items-center gap-1.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                                {mode && <mode.icon className="w-2.5 h-2.5" style={{ color: mode.color }} aria-label={mode.label} />}
                                {formatDistanceToNow(chat.updatedAt)}
                              </span>
                            </button>
                            {/* Always visible on touch screens; on desktop on hover or keyboard focus */}
                            <div className="flex items-center gap-0.5 pr-1.5 flex-shrink-0 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100 transition-opacity">
                              <button onClick={() => { setEditingId(chat.id); setEditTitle(chat.title); }}
                                aria-label={`Rename ${chat.title}`} title="Rename"
                                className="p-1 rounded-lg hover:bg-[var(--bg-active)]" style={{ color: 'var(--text-muted)' }}>
                                <Pencil className="w-3 h-3" />
                              </button>
                              <button onClick={() => handleDelete(chat)}
                                aria-label={`Delete ${chat.title}`} title="Delete"
                                className="p-1 rounded-lg hover:bg-red-500/15 hover:text-red-400" style={{ color: 'var(--text-muted)' }}>
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                          </>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))
          )}
        </div>

        {/* Theme, settings, account */}
        <div className="flex-shrink-0 px-3 pb-3 pt-2 space-y-1" style={{ borderTop: '1px solid var(--border)' }}>
          <FooterButton
            collapsed={collapsed}
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            icon={theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-indigo-500" />}
            label={theme === 'dark' ? 'Light mode' : 'Dark mode'}
          />
          <FooterButton
            collapsed={collapsed}
            onClick={() => { setMobileOpen(false); setSettingsModalOpen(true); }}
            icon={<Settings className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />}
            label="Settings"
          />

          <div className={`flex items-center gap-3 px-2 pt-2 ${collapsed ? 'flex-col' : ''}`}>
            <div className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0 font-bold text-xs text-white"
              title={collapsed ? `${user?.username || 'User'} — ${user?.email || ''}` : undefined}
              style={{ background: isAdmin ? 'linear-gradient(135deg, #f59e0b, #ef4444)' : 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
              {user?.username?.charAt(0).toUpperCase() || <User className="w-4 h-4" />}
            </div>
            {!collapsed && (
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <p className="text-xs font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
                    {user?.username || 'User'}
                  </p>
                  {isAdmin && (
                    <span className="flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0"
                      style={{ background: 'var(--warning-muted)', color: 'var(--warning)' }}>
                      <Shield className="w-2.5 h-2.5" />ADMIN
                    </span>
                  )}
                </div>
                <p className="text-[10px] truncate" style={{ color: 'var(--text-muted)' }}>{user?.email}</p>
              </div>
            )}
            <button onClick={logout} aria-label="Sign out" title="Sign out"
              className="p-1.5 rounded-lg transition-colors hover:bg-red-500/10 hover:text-red-400 flex-shrink-0"
              style={{ color: 'var(--text-muted)' }}>
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </aside>

      <SettingsModal />
    </>
  );
}

function Logo() {
  return (
    <div className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0"
      style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)', boxShadow: '0 0 16px rgba(99,102,241,0.3)' }}>
      <Sparkles className="w-4 h-4 text-white" />
    </div>
  );
}

function FooterButton({ collapsed, onClick, icon, label }: {
  collapsed: boolean; onClick: () => void; icon: React.ReactNode; label: string;
}) {
  return (
    <button
      onClick={onClick}
      title={collapsed ? label : undefined}
      aria-label={collapsed ? label : undefined}
      className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-colors hover:bg-[var(--bg-hover)] ${
        collapsed ? 'justify-center px-0' : ''
      }`}
      style={{ color: 'var(--text-secondary)' }}
    >
      <span className="flex-shrink-0">{icon}</span>
      {!collapsed && <span>{label}</span>}
    </button>
  );
}

export default Sidebar;
