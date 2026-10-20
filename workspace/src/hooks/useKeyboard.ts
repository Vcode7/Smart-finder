// src/hooks/useKeyboard.ts
'use client';

import { useEffect, useSyncExternalStore } from 'react';
import { useUIStore } from '@/store/ui';

/**
 * Ctrl/Cmd+K opens the command palette. CommandPalette (mounted in the root layout)
 * registers this on every page; calling it again elsewhere is harmless.
 */
export function useKeyboard(enabled = true) {
  const { setCommandPaletteOpen } = useUIStore();

  useEffect(() => {
    if (!enabled) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!useUIStore.getState().commandPaletteOpen);
      } else if (e.key === 'Escape' && useUIStore.getState().commandPaletteOpen) {
        setCommandPaletteOpen(false);
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [enabled, setCommandPaletteOpen]);
}

const noSubscribe = () => () => {};

/** "⌘K" on Apple devices, "Ctrl K" elsewhere (server render: "Ctrl K"). */
export function useShortcutLabel(): string {
  return useSyncExternalStore(
    noSubscribe,
    () => (/Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘K' : 'Ctrl K'),
    () => 'Ctrl K',
  );
}
