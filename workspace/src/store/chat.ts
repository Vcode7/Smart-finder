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
  type: 'document' | 'video' | 'image' | 'web';
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
  type: 'document' | 'video' | 'image' | 'web';
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
  setSending: (v: boolean) => void;
  updateChatTitle: (id: string, title: string) => void;
  removeChat: (id: string) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      activeChatId: null,
      chats: [],
      messages: [],
      activeContext: [],
      chatContexts: {},
      searchMode: 'both',
      enableInternetSources: true,
      isSmartSearchEnabled: true,
      isLoading: false,
      isSending: false,

      setActiveChatId: (activeChatId) => {
        const stored = activeChatId ? get().chatContexts[activeChatId] || [] : [];
        set({ activeChatId, activeContext: stored });
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
      setSending: (isSending) => set({ isSending }),
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
    }),
    {
      name: 'sf-chat',
      partialize: (state) => ({
        searchMode: state.searchMode,
        enableInternetSources: state.enableInternetSources,
        isSmartSearchEnabled: state.isSmartSearchEnabled,
        chats: state.chats,
        chatContexts: state.chatContexts,
      }),
    }
  )
);
