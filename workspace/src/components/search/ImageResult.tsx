'use client';
// src/components/search/ImageResult.tsx — Search result item for images and OCR text

import { motion } from 'framer-motion';
import { Image as ImageIcon, Plus, Check } from 'lucide-react';
import { useChatStore, ContextItem } from '@/store/chat';

interface ImageResultProps {
  image: {
    id: string;
    sourceId: string;
    title: string;
    description?: string;
    ocrText?: string;
    relevanceScore?: number;
  };
}

export function ImageResult({ image }: ImageResultProps) {
  const { activeContext, addContextItem, removeContextItem } = useChatStore();
  const isAdded = activeContext.some((c) => c.id === image.id);

  const snippetText = image.description || image.ocrText || 'Image uploaded to knowledge base';

  const handleToggle = () => {
    if (isAdded) {
      removeContextItem(image.id);
    } else {
      const item: ContextItem = {
        id: image.id,
        type: 'image',
        title: image.title,
        snippet: snippetText,
        relevanceScore: image.relevanceScore,
        metadata: {
          sourceId: image.sourceId,
          description: image.description,
          ocrText: image.ocrText,
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
            style={{ background: 'rgba(16,185,129,0.1)', color: '#10b981' }}
          >
            <ImageIcon className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
              {image.title}
            </h4>
            <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
              <span>Visual Media</span>
              {image.relevanceScore !== undefined && (
                <span className="text-[10px] px-1.5 py-0.5 rounded font-mono" style={{ background: 'var(--bg-active)' }}>
                  {Math.round(image.relevanceScore * 100)}% match
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
        {snippetText}
      </p>
    </motion.div>
  );
}

export default ImageResult;
