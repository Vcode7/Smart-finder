'use client';
// src/store/auth.ts — Zustand auth store with server-synced user state

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { useChatStore } from '@/store/chat';
import { withBase } from '@/lib/base-path';

export interface AuthUser {
  id: string;
  email: string;
  username: string;
  role: 'user' | 'admin';
}

interface AuthState {
  user: AuthUser | null;
  isLoading: boolean;
  isInitialized: boolean;

  setUser: (user: AuthUser | null) => void;
  setLoading: (loading: boolean) => void;
  setInitialized: (v: boolean) => void;
  logout: () => Promise<void>;
  fetchMe: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isLoading: false,
      isInitialized: false,

      setUser: (user) => set({ user }),
      setLoading: (isLoading) => set({ isLoading }),
      setInitialized: (isInitialized) => set({ isInitialized }),

      logout: async () => {
        try {
          await fetch('/api/auth/logout', { method: 'POST' });
        } catch {
          // Backend unreachable: still clear the local session
        }
        set({ user: null });
        useChatStore.getState().reset();
        // Full page load (not router.push): drops every in-memory store of the signed-out account
        window.location.replace(withBase('/auth/login'));
      },

      fetchMe: async () => {
        set({ isLoading: true });
        try {
          const res = await fetch('/api/auth/me');
          if (res.ok) {
            const data = await res.json();
            set({ user: data.user, isInitialized: true });
          } else {
            set({ user: null, isInitialized: true });
          }
        } catch {
          set({ user: null, isInitialized: true });
        } finally {
          set({ isLoading: false });
        }
      },
    }),
    {
      name: 'sf-auth',
      partialize: (state) => ({ user: state.user }),
    }
  )
);
