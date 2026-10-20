'use client';
// src/store/chat.ts — Zustand store for chat sessions and active context

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type SearchMode = 'local' | 'internet' | 'both';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  createdAt: string;
}

export interface Citation {
  type: 'document' | 'video' | 'audio' | 'image' | 'web';
  title: string;
  url?: string;
  sourceId?: string;
  timestamp?: string;
  page?: string;
  section?: string;
  snippet?: string;
}

export interface ContextItem {
  id: string;
  type: 'document' | 'video' | 'audio' | 'image' | 'web';
  title: string;
  snippet?: string;
  relevanceScore?: number;
  metadata?: Record<string, unknown>;
}

export interface ChatSummary {
  id: string;
  title: string;
  searchMode: SearchMode;
  createdAt: string;
  updatedAt: string;
  lastMessage?: string;
}

interface ChatState {
  activeChatId: string | null;
  chats: ChatSummary[];
  messages: ChatMessage[];
  activeContext: ContextItem[];
  chatContexts: Record<string, ContextItem[]>;
  searchMode: SearchMode;
  enableInternetSources: boolean;
  isSmartSearchEnabled: boolean;
  isLoading: boolean;
  isSending: boolean;
  /** Chat whose message is waiting for its answer (null when none). */
  sendingChatId: string | null;

  setActiveChatId: (id: string | null) => void;
  setChats: (chats: ChatSummary[]) => void;
  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (msg: ChatMessage) => void;
  setActiveContext: (context: ContextItem[]) => void;
  setChatContext: (chatId: string, items: ContextItem[]) => void;
  addContextItem: (item: ContextItem) => void;
  removeContextItem: (id: string) => void;
  clearContext: () => void;
  setSearchMode: (mode: SearchMode) => void;
  setEnableInternetSources: (enabled: boolean) => void;
  setIsSmartSearchEnabled: (enabled: boolean) => void;
  setLoading: (v: boolean) => void;
  setSending: (v: boolean, chatId?: string | null) => void;
  updateChatTitle: (id: string, title: string) => void;
  removeChat: (id: string) => void;
  /** Reload the chat list (titles and order change on the server after each answer). */
  refreshChats: () => Promise<void>;
  /** Create a chat on the server and list it first. Throws when the request fails. */
  createChat: (title: string, searchMode?: SearchMode) => Promise<ChatSummary>;
  /** Show an empty chat; the server chat is created with its first message. */
  startNewChat: () => void;
  /** Forget everything about the signed-in user's chats (logout). */
  reset: () => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      activeChatId: null,
      chats: [],
      messages: [],
      activeContext: [],
      chatContexts: {},
      // Local-only by default: the internet is searched only after the user turns it on,
      // and that choice lasts for the current visit (it is not persisted)
      searchMode: 'local',
      enableInternetSources: false,
      isSmartSearchEnabled: true,
      isLoading: false,
      isSending: false,
      sendingChatId: null,

      setActiveChatId: (activeChatId) => {
        const stored = activeChatId ? get().chatContexts[activeChatId] || [] : [];
        // Switching chats must not keep showing the previous chat's messages
        const messages = activeChatId === get().activeChatId ? get().messages : [];
        set({ activeChatId, activeContext: stored, messages });
      },
      setChats: (chats) => set({ chats }),
      setMessages: (messages) => set({ messages }),
      addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
      setActiveContext: (activeContext) =>
        set((s) => {
          const nextContexts = s.activeChatId
            ? { ...s.chatContexts, [s.activeChatId]: activeContext }
            : s.chatContexts;
          return { activeContext, chatContexts: nextContexts };
        }),
      setChatContext: (chatId, items) =>
        set((s) => ({
          chatContexts: { ...s.chatContexts, [chatId]: items },
          activeContext: s.activeChatId === chatId ? items : s.activeContext,
        })),
      addContextItem: (item) =>
        set((s) => {
          const exists = s.activeContext.some((c) => c.id === item.id);
          const nextContext = exists ? s.activeContext : [...s.activeContext, item];
          const nextContexts = s.activeChatId
            ? { ...s.chatContexts, [s.activeChatId]: nextContext }
            : s.chatContexts;
          return { activeContext: nextContext, chatContexts: nextContexts };
        }),
      removeContextItem: (id) =>
        set((s) => {
          const nextContext = s.activeContext.filter((c) => c.id !== id);
          const nextContexts = s.activeChatId
            ? { ...s.chatContexts, [s.activeChatId]: nextContext }
            : s.chatContexts;
          return { activeContext: nextContext, chatContexts: nextContexts };
        }),
      clearContext: () =>
        set((s) => {
          const nextContexts = s.activeChatId
            ? { ...s.chatContexts, [s.activeChatId]: [] }
            : s.chatContexts;
          return { activeContext: [], chatContexts: nextContexts };
        }),
      setSearchMode: (searchMode) => set({ searchMode }),
      setEnableInternetSources: (enableInternetSources) => set({ enableInternetSources }),
      setIsSmartSearchEnabled: (isSmartSearchEnabled) => set({ isSmartSearchEnabled }),
      setLoading: (isLoading) => set({ isLoading }),
      setSending: (isSending, chatId = null) => set({ isSending, sendingChatId: isSending ? chatId : null }),
      updateChatTitle: (id, title) =>
        set((s) => ({
          chats: s.chats.map((c) => (c.id === id ? { ...c, title } : c)),
        })),
      removeChat: (id) =>
        set((s) => {
          const nextChatContexts = { ...s.chatContexts };
          delete nextChatContexts[id];
          return {
            chats: s.chats.filter((c) => c.id !== id),
            chatContexts: nextChatContexts,
            activeChatId: s.activeChatId === id ? null : s.activeChatId,
            messages: s.activeChatId === id ? [] : s.messages,
            activeContext: s.activeChatId === id ? [] : s.activeContext,
          };
        }),
      refreshChats: async () => {
        try {
          const res = await fetch('/api/chats');
          if (res.ok) {
            const data = await res.json();
            set({ chats: data.chats || [] });
          }
        } catch {
          // Backend unreachable: keep the current list
        }
      },
      createChat: async (title, searchMode) => {
        const res = await fetch('/api/chats', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: title.trim().slice(0, 60) || 'New Chat', searchMode: searchMode ?? get().searchMode }),
        });
        if (!res.ok) throw new Error('Failed to create chat');
        const chat = (await res.json()).chat as ChatSummary;
        set((s) => ({ chats: [chat, ...s.chats.filter((c) => c.id !== chat.id)] }));
        return chat;
      },
      startNewChat: () => set({ activeChatId: null, messages: [], activeContext: [] }),
      reset: () =>
        set({
          activeChatId: null, chats: [], messages: [], activeContext: [], chatContexts: {},
          isLoading: false, isSending: false, sendingChatId: null,
        }),
    }),
    {
      name: 'sf-chat',
      // Not persisted: the chat list (loaded from the server on every visit; a stored copy
      // would show the previous account's chats to the next one to sign in) and the
      // internet/search-mode choice (every visit starts with local search only).
      version: 2,
      migrate: (persisted) => {
        const state = { ...((persisted as Record<string, unknown>) || {}) };
        delete state.chats;
        delete state.searchMode;
        delete state.enableInternetSources;
        return state as Pick<ChatState, 'isSmartSearchEnabled' | 'chatContexts'>;
      },
      partialize: (state) => ({
        isSmartSearchEnabled: state.isSmartSearchEnabled,
        chatContexts: state.chatContexts,
      }),
    }
  )
);
