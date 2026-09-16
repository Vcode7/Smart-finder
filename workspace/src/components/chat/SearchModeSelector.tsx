'use client';
// src/components/chat/SearchModeSelector.tsx — Radio group for search source selection

import { motion } from 'framer-motion';
import { Globe, Database, Layers } from 'lucide-react';
import { useChatStore, type SearchMode } from '@/store/chat';

const MODES: { value: SearchMode; label: string; desc: string; icon: typeof Globe; color: string }[] = [
  { value: 'internet', label: 'Internet', desc: 'Search the web in real-time', icon: Globe, color: '#10b981' },
  { value: 'local', label: 'Local Knowledge', desc: 'Search uploaded documents & videos', icon: Database, color: '#6366f1' },
  { value: 'both', label: 'Both', desc: 'Hybrid local + internet search', icon: Layers, color: '#a855f7' },
];

export default function SearchModeSelector() {
  const { searchMode, setSearchMode } = useChatStore();

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {MODES.map((mode) => {
        const Icon = mode.icon;
        const isActive = searchMode === mode.value;
        return (
          <motion.button
            key={mode.value}
            onClick={() => setSearchMode(mode.value)}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
            style={{
              background: isActive ? `${mode.color}18` : 'var(--bg-elevated)',
              border: isActive ? `1px solid ${mode.color}55` : '1px solid var(--border)',
              color: isActive ? mode.color : 'var(--text-secondary)',
            }}
            title={mode.desc}
          >
            <Icon className="w-3.5 h-3.5" />
            {mode.label}
          </motion.button>
        );
      })}
    </div>
  );
}
