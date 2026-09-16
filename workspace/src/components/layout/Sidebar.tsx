'use client';
// src/components/layout/Sidebar.tsx — Persistent sidebar with chat history, admin controls

import { useState, useEffect, useCallback } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles, Plus, MessageSquare, Clock, Trash2,
  Pencil, Check, X, Upload, LogOut, User, Shield,
  PanelLeftClose, PanelLeftOpen, Globe, Database, Layers, Search,
  Sun, Moon, Settings
} from 'lucide-react';
import { useAuthStore } from '@/store/auth';
import { useChatStore } from '@/store/chat';
import { useUIStore } from '@/store/ui';
import { SettingsModal } from '@/components/modals/SettingsModal';
import { toast } from 'sonner';

import { formatDistanceToNow } from '@/lib/utils/date';

export function Sidebar({ sessionId }: { sessionId?: string } = {}) {
  const [collapsed, setCollapsed] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const router = useRouter();
  const pathname = usePathname();

  const { user, logout } = useAuthStore();
  const { theme, setTheme, setSettingsModalOpen } = useUIStore();
  const { chats, activeChatId, setActiveChatId, setMessages, setChats, updateChatTitle, removeChat, setLoading, setActiveContext, clearContext } = useChatStore();


  const isAdmin = user?.role === 'admin';

  const loadChats = useCallback(async () => {
    try {
      const res = await fetch('/api/chats');
      if (res.ok) {
        const data = await res.json();
        setChats(data.chats || []);
      }
    } catch {
      // silent
    }
  }, [setChats]);

  useEffect(() => {
    loadChats();
  }, [loadChats]);

  const handleNewChat = async () => {
    try {
      const res = await fetch('/api/chats', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Chat' }),
      });
      if (res.ok) {
        const data = await res.json();
        setActiveChatId(data.chat.id);
        setMessages([]);
        clearContext();
        setChats([data.chat, ...chats]);
        router.push('/');
      }
    } catch {
      toast.error('Failed to create new chat');
    }
  };

  const handleChatClick = async (chatId: string) => {
    if (chatId === activeChatId) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/chats/${chatId}`);
      if (res.ok) {
        const data = await res.json();
        setActiveChatId(chatId);
        if (data.contextItems && Array.isArray(data.contextItems)) {
          setActiveContext(data.contextItems);
        } else {
          clearContext();
        }
        setMessages(data.messages.map((m: { id: string; role: 'user' | 'assistant'; content: string; citations_json: string; created_at: string }) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          citations: JSON.parse(m.citations_json || '[]'),
          createdAt: m.created_at,
        })));
        router.push('/');
      }
    } catch {
      toast.error('Failed to load chat');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (chatId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await fetch(`/api/chats/${chatId}`, { method: 'DELETE' });
      if (res.ok) {
        removeChat(chatId);
        toast.success('Chat deleted');
      }
    } catch {
      toast.error('Failed to delete chat');
    }
  };

  const handleRename = async (chatId: string) => {
    if (!editTitle.trim()) { setEditingId(null); return; }
    try {
      await fetch(`/api/chats/${chatId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: editTitle.trim() }),
      });
      updateChatTitle(chatId, editTitle.trim());
      setEditingId(null);
      toast.success('Chat renamed');
    } catch {
      toast.error('Failed to rename chat');
    }
  };

  const startEdit = (chatId: string, currentTitle: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(chatId);
    setEditTitle(currentTitle);
  };

  return (
    <motion.aside
      initial={false}
      animate={{ width: collapsed ? 64 : 280 }}
      transition={{ type: 'spring', bounce: 0.1, duration: 0.4 }}
      className="flex-shrink-0 h-screen flex flex-col relative z-30 overflow-hidden"
      style={{
        background: 'var(--bg-elevated)',
        borderRight: '1px solid var(--border)',
      }}
    >
      {/* ─── Header ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-4 flex-shrink-0"
        style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0 shadow-md"
          style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)', boxShadow: '0 0 16px rgba(99,102,241,0.3)' }}>
          <Sparkles className="w-4 h-4 text-white" />
        </div>

        <AnimatePresence>
          {!collapsed && (
            <motion.div initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }}
              className="flex-1 min-w-0">
              <span className="font-bold text-sm tracking-tight" style={{ color: 'var(--text-primary)' }}>
                Smart Finder
              </span>
              <span className="ml-1.5 text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                style={{ background: 'var(--accent-muted)', color: 'var(--accent)' }}>AI</span>
            </motion.div>
          )}
        </AnimatePresence>

        <button onClick={() => setCollapsed(!collapsed)}
          className="p-1.5 rounded-lg transition-colors hover:bg-[var(--bg-hover)] flex-shrink-0"
          style={{ color: 'var(--text-muted)' }}>
          {collapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
        </button>
      </div>

      {/* ─── Actions ────────────────────────────────────────────── */}
      <div className="px-3 py-3 space-y-1 flex-shrink-0">
        {/* New Chat */}
        <motion.button
          onClick={handleNewChat}
          whileHover={{ scale: 1.01 }}
          whileTap={{ scale: 0.98 }}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl font-semibold text-sm text-white transition-all shadow-md"
          style={{
            background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
            boxShadow: '0 4px 12px rgba(99,102,241,0.3)',
            justifyContent: collapsed ? 'center' : 'flex-start',
          }}
        >
          <Plus className="w-4 h-4 flex-shrink-0" />
          <AnimatePresence>
            {!collapsed && (
              <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                New Chat
              </motion.span>
            )}
          </AnimatePresence>
        </motion.button>

        {/* Admin: Create/Update Repository */}
        {isAdmin && (
          <button
            onClick={() => router.push('/admin')}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-medium transition-all hover:bg-[var(--bg-hover)]"
            style={{
              color: '#f59e0b',
              justifyContent: collapsed ? 'center' : 'flex-start',
            }}
          >
            <Upload className="w-4 h-4 flex-shrink-0" />
            <AnimatePresence>
              {!collapsed && (
                <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  📚 Create/Update Repository
                </motion.span>
              )}
            </AnimatePresence>
          </button>
        )}

        {/* Smart Finder Multimodal Search */}
        <button
          onClick={() => router.push('/search')}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm font-medium transition-all hover:bg-[var(--bg-hover)]"
          style={{
            color: pathname === '/search' ? 'var(--accent)' : 'var(--text-secondary)',
            background: pathname === '/search' ? 'rgba(99,102,241,0.1)' : 'transparent',
            border: pathname === '/search' ? '1px solid rgba(99,102,241,0.2)' : '1px solid transparent',
            justifyContent: collapsed ? 'center' : 'flex-start',
          }}
        >
          <Search className="w-4 h-4 flex-shrink-0" style={{ color: pathname === '/search' ? 'var(--accent)' : undefined }} />
          <AnimatePresence>
            {!collapsed && (
              <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                Smart Finder
              </motion.span>
            )}
          </AnimatePresence>
        </button>

        {/* Browse Knowledge */}
        <button
          onClick={() => router.push('/knowledge')}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm font-medium transition-all hover:bg-[var(--bg-hover)]"
          style={{
            color: pathname === '/knowledge' ? 'var(--accent)' : 'var(--text-secondary)',
            background: pathname === '/knowledge' ? 'rgba(99,102,241,0.1)' : 'transparent',
            border: pathname === '/knowledge' ? '1px solid rgba(99,102,241,0.2)' : '1px solid transparent',
            justifyContent: collapsed ? 'center' : 'flex-start',
          }}
        >
          <Database className="w-4 h-4 flex-shrink-0" />
          <AnimatePresence>
            {!collapsed && (
              <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                Knowledge Base
              </motion.span>
            )}
          </AnimatePresence>
        </button>
      </div>

      {/* ─── Chat History ───────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-3 pb-2 min-h-0">
        <AnimatePresence>
          {!collapsed && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="flex items-center gap-2 px-1 py-2 mb-1">
                <Clock className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
                <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                  Chat History
                </span>
              </div>

              {chats.length === 0 ? (
                <div className="text-center py-8 px-4">
                  <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-30" style={{ color: 'var(--text-muted)' }} />
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>No chats yet. Start a new one!</p>
                </div>
              ) : (
                <div className="space-y-0.5">
                  {chats.map((chat) => (
                    <motion.div
                      key={chat.id}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      className={`group relative flex items-start gap-2 px-3 py-2.5 rounded-xl cursor-pointer transition-all ${
                        activeChatId === chat.id ? 'bg-[var(--bg-active)]' : 'hover:bg-[var(--bg-hover)]'
                      }`}
                      onClick={() => handleChatClick(chat.id)}
                    >
                      <div className="flex-1 min-w-0">
                        {editingId === chat.id ? (
                          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                            <input
                              value={editTitle}
                              onChange={(e) => setEditTitle(e.target.value)}
                              onKeyDown={(e) => { if (e.key === 'Enter') handleRename(chat.id); if (e.key === 'Escape') setEditingId(null); }}
                              autoFocus
                              className="flex-1 text-xs bg-transparent outline-none border-b"
                              style={{ borderColor: 'var(--accent)', color: 'var(--text-primary)' }}
                            />
                            <button onClick={() => handleRename(chat.id)} className="p-0.5 text-emerald-400"><Check className="w-3.5 h-3.5" /></button>
                            <button onClick={() => setEditingId(null)} style={{ color: 'var(--text-muted)' }}><X className="w-3.5 h-3.5" /></button>
                          </div>
                        ) : (
                          <>
                            <p className="text-xs font-medium truncate leading-5" style={{ color: 'var(--text-primary)' }}>
                              {chat.title}
                            </p>
                            <div className="flex items-center gap-1.5 mt-0.5">
                              {chat.searchMode === 'local' && <Database className="w-2.5 h-2.5" style={{ color: 'var(--accent)' }} />}
                              {chat.searchMode === 'internet' && <Globe className="w-2.5 h-2.5" style={{ color: '#10b981' }} />}
                              {chat.searchMode === 'both' && <Layers className="w-2.5 h-2.5" style={{ color: 'var(--accent-ai)' }} />}
                              <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                                {formatDistanceToNow(chat.updatedAt)}
                              </p>
                            </div>
                          </>
                        )}
                      </div>

                      {editingId !== chat.id && (
                        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                          <button onClick={(e) => startEdit(chat.id, chat.title, e)}
                            className="p-1 rounded-lg hover:bg-[var(--bg-active)]" style={{ color: 'var(--text-muted)' }}>
                            <Pencil className="w-3 h-3" />
                          </button>
                          <button onClick={(e) => handleDelete(chat.id, e)}
                            className="p-1 rounded-lg hover:bg-red-500/20 hover:text-red-400" style={{ color: 'var(--text-muted)' }}>
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      )}
                    </motion.div>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Collapsed: icon-only chat list */}
        {collapsed && chats.slice(0, 8).map((chat) => (
          <button key={chat.id} onClick={() => handleChatClick(chat.id)} title={chat.title}
            className={`w-full flex items-center justify-center p-2.5 rounded-xl my-0.5 transition-all ${
              activeChatId === chat.id ? 'bg-[var(--bg-active)]' : 'hover:bg-[var(--bg-hover)]'
            }`}>
            <MessageSquare className="w-4 h-4" style={{ color: activeChatId === chat.id ? 'var(--accent)' : 'var(--text-muted)' }} />
          </button>
        ))}
      </div>

      {/* ─── Bottom: Theme & User Profile ───────────────────────── */}
      <div className="flex-shrink-0 px-3 pb-4 pt-2 space-y-1.5" style={{ borderTop: '1px solid var(--border)' }}>
        {/* Theme Switch Button */}
        <button
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all hover:bg-[var(--bg-hover)] ${
            collapsed ? 'justify-center px-0' : ''
          }`}
          style={{
            color: 'var(--text-secondary)',
            border: '1px solid var(--border)',
            background: 'var(--bg-surface, var(--bg-base))',
          }}
          title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
          aria-label="Toggle Light/Dark Theme"
        >
          {theme === 'dark' ? (
            <Sun className="w-4 h-4 text-amber-400 flex-shrink-0" />
          ) : (
            <Moon className="w-4 h-4 text-indigo-500 flex-shrink-0" />
          )}

          <AnimatePresence>
            {!collapsed && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center justify-between flex-1 min-w-0"
              >
                <span className="font-medium text-[11px]" style={{ color: 'var(--text-primary)' }}>
                  {theme === 'dark' ? 'Switch to Light' : 'Switch to Dark'}
                </span>
                <span
                  className="text-[9px] px-1.5 py-0.5 rounded font-mono uppercase font-semibold"
                  style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}
                >
                  {theme === 'dark' ? 'Dark' : 'Light'}
                </span>
              </motion.div>
            )}
          </AnimatePresence>
        </button>

        {/* Settings Button — Positioned directly below Light/Dark theme switch */}
        <button
          onClick={() => setSettingsModalOpen(true)}
          className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all hover:bg-[var(--bg-hover)] ${
            collapsed ? 'justify-center px-0' : ''
          }`}
          style={{
            color: 'var(--text-secondary)',
            border: '1px solid var(--border)',
            background: 'var(--bg-surface, var(--bg-base))',
          }}
          title="Open Settings"
          aria-label="Settings"
        >
          <Settings className="w-4 h-4 text-indigo-400 flex-shrink-0" />

          <AnimatePresence>
            {!collapsed && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center justify-between flex-1 min-w-0"
              >
                <span className="font-medium text-[11px]" style={{ color: 'var(--text-primary)' }}>
                  Settings
                </span>
                <span
                  className="text-[9px] px-1.5 py-0.5 rounded font-mono uppercase font-semibold"
                  style={{ background: 'var(--bg-active)', color: 'var(--accent)' }}
                >
                  Ollama
                </span>
              </motion.div>
            )}
          </AnimatePresence>
        </button>

        {/* User Profile */}
        <div className={`flex items-center gap-3 px-3 py-2 rounded-xl ${collapsed ? 'justify-center' : ''}`}>

          <div className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0 font-bold text-xs text-white shadow-sm"
            style={{ background: isAdmin ? 'linear-gradient(135deg, #f59e0b, #ef4444)' : 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
            {user?.username?.charAt(0).toUpperCase() || <User className="w-4 h-4" />}
          </div>

          <AnimatePresence>
            {!collapsed && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <p className="text-xs font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
                    {user?.username || 'User'}
                  </p>
                  {isAdmin && (
                    <span className="flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0"
                      style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b' }}>
                      <Shield className="w-2.5 h-2.5" />ADMIN
                    </span>
                  )}
                </div>
                <p className="text-[10px] truncate" style={{ color: 'var(--text-muted)' }}>{user?.email}</p>
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {!collapsed && (
              <motion.button initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                onClick={logout}
                className="p-1.5 rounded-lg transition-colors hover:bg-red-500/10 flex-shrink-0"
                style={{ color: 'var(--text-muted)' }} title="Logout">
                <LogOut className="w-3.5 h-3.5" />
              </motion.button>
            )}
          </AnimatePresence>
        </div>
      </div>

      <SettingsModal />
    </motion.aside>
  );
}

export default Sidebar;
