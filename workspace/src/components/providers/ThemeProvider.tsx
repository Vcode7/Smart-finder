'use client';

import { useEffect } from 'react';
import { useUIStore } from '@/store/ui';

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const { theme } = useUIStore();

  useEffect(() => {
    const root = document.documentElement;
    const isDark =
      theme === 'system'
        ? window.matchMedia('(prefers-color-scheme: dark)').matches
        : theme === 'dark';

    root.classList.toggle('dark', isDark);
    root.classList.toggle('light', !isDark);
    root.style.colorScheme = isDark ? 'dark' : 'light';
  }, [theme]);

  return <>{children}</>;
}

