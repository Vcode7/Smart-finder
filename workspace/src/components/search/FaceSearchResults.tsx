'use client';
// src/components/search/FaceSearchResults.tsx — Displays face and identity match results

import { motion } from 'framer-motion';
import { UserCheck, Clock, MessageSquarePlus, Sparkles } from 'lucide-react';
import { useChatStore, ContextItem } from '@/store/chat';
import { toast } from 'sonner';

export interface FaceMatchItem {
  id: string;
  sourceId: string;
  sourceName?: string;
  timestamp?: number;
  confidence: number;
  similarity: number;
}

interface FaceSearchResultsProps {
  matches: FaceMatchItem[];
  onOpenChatWithMatch?: (match: FaceMatchItem) => void;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function FaceSearchResults({ matches, onOpenChatWithMatch }: FaceSearchResultsProps) {
  const { addContextItem } = useChatStore();

  const handleAddToContext = (match: FaceMatchItem) => {
    const timeStr = match.timestamp !== undefined ? ` at timestamp ${formatTime(match.timestamp)}` : '';
    const item: ContextItem = {
      id: match.id,
      type: 'video',
      title: `Face Match: ${match.sourceName || 'Video Source'}`,
      snippet: `Identified face match with ${Math.round(match.similarity * 100)}% confidence in ${match.sourceName || 'source'}${timeStr}.`,
      relevanceScore: match.similarity,
      metadata: {
        sourceId: match.sourceId,
        timestamp: match.timestamp !== undefined ? formatTime(match.timestamp) : undefined,
      },
    };
    addContextItem(item);
    toast.success('Added match context to active chat');
  };

  if (matches.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
        <Sparkles className="w-3.5 h-3.5" style={{ color: 'var(--accent)' }} />
        <span>Face & Identity Matches ({matches.length})</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {matches.map((match) => (
          <motion.div
            key={match.id}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="p-4 rounded-2xl flex flex-col justify-between gap-3 transition-all"
            style={{
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
            }}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 font-bold text-white shadow-sm"
                  style={{ background: 'linear-gradient(135deg, #ec4899, #8b5cf6)' }}
                >
                  <UserCheck className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
                    {match.sourceName || 'Visual Match'}
                  </h4>
                  <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                    {match.timestamp !== undefined && (
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" /> {formatTime(match.timestamp)}
                      </span>
                    )}
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono text-emerald-400" style={{ background: 'rgba(16,185,129,0.1)' }}>
                      {Math.round(match.similarity * 100)}% similarity
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <button
              onClick={() => {
                handleAddToContext(match);
                onOpenChatWithMatch?.(match);
              }}
              className="flex items-center justify-center gap-2 w-full py-2 rounded-xl text-xs font-medium transition-all"
              style={{
                background: 'rgba(99,102,241,0.1)',
                color: 'var(--accent)',
                border: '1px solid rgba(99,102,241,0.2)',
              }}
            >
              <MessageSquarePlus className="w-3.5 h-3.5" />
              <span>Discuss in Chat</span>
            </button>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

export default FaceSearchResults;
