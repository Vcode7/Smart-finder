'use client';
// src/components/providers/AuthProvider.tsx
// Initializes auth state on app load by fetching /api/auth/me

import { useEffect } from 'react';
import { useAuthStore } from '@/store/auth';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { fetchMe, isInitialized } = useAuthStore();

  useEffect(() => {
    if (!isInitialized) {
      fetchMe();
    }
  }, [fetchMe, isInitialized]);

  return <>{children}</>;
}
