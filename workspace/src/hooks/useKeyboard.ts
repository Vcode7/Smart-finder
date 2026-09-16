// src/hooks/useKeyboard.ts
'use client';

import { useEffect } from 'react';
import { useUIStore } from '@/store/ui';

export function useKeyboard() {
  const { setCommandPaletteOpen } = useUIStore();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;

      // Cmd/Ctrl+K — command palette
      if (meta && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(true);
      }

      // Escape — close command palette
      if (e.key === 'Escape') {
        setCommandPaletteOpen(false);
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [setCommandPaletteOpen]);
}
