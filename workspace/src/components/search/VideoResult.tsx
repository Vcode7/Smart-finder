'use client';
// src/components/search/VideoResult.tsx — Search result item for local/online videos

import { motion } from 'framer-motion';
import { Video, Plus, Check, Clock } from 'lucide-react';
import { useChatStore, ContextItem } from '@/store/chat';

interface VideoResultProps {
  video: {
    id: string;
    sourceId?: string;
    videoId?: string;
    title: string;
    startTime?: number;
    endTime?: number;
    snippet: string;
    fullContext?: string;
    relevanceScore?: number;
  };
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function VideoResult({ video }: VideoResultProps) {
  const { activeContext, addContextItem, removeContextItem } = useChatStore();
  const isAdded = activeContext.some((c) => c.id === video.id);

  const timestampStr = video.startTime !== undefined ? formatTime(video.startTime) : undefined;

  const handleToggle = () => {
    if (isAdded) {
      removeContextItem(video.id);
    } else {
      const item: ContextItem = {
        id: video.id,
        type: 'video',
        title: video.title,
        snippet: video.fullContext || video.snippet,
        relevanceScore: video.relevanceScore,
        metadata: {
          sourceId: video.sourceId,
          videoId: video.videoId,
          timestamp: timestampStr,
          startTime: video.startTime,
          endTime: video.endTime,
        },
      };
      addContextItem(item);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="p-4 rounded-2xl transition-all duration-200"
      style={{
        background: 'var(--bg-elevated)',
        border: isAdded ? '1px solid var(--accent)' : '1px solid var(--border)',
      }}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0"
            style={{ background: 'rgba(244,63,94,0.1)', color: '#f43f5e' }}
          >
            <Video className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
              {video.title}
            </h4>
            <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
              {timestampStr && (
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" /> {timestampStr}
                </span>
              )}
              {video.relevanceScore !== undefined && (
                <span className="text-[10px] px-1.5 py-0.5 rounded font-mono" style={{ background: 'var(--bg-active)' }}>
                  {Math.round(video.relevanceScore * 100)}% match
                </span>
              )}
            </div>
          </div>
        </div>

        <button
          onClick={handleToggle}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-medium transition-all"
          style={{
            background: isAdded ? 'var(--accent)' : 'var(--bg-surface, var(--bg-base))',
            color: isAdded ? '#fff' : 'var(--text-secondary)',
            border: isAdded ? 'none' : '1px solid var(--border)',
          }}
        >
          {isAdded ? (
            <>
              <Check className="w-3.5 h-3.5" />
              <span>In Chat</span>
            </>
          ) : (
            <>
              <Plus className="w-3.5 h-3.5" />
              <span>Add to Chat</span>
            </>
          )}
        </button>
      </div>

      <p className="text-xs leading-relaxed line-clamp-3" style={{ color: 'var(--text-secondary)' }}>
        {video.snippet}
      </p>
    </motion.div>
  );
}

export default VideoResult;
