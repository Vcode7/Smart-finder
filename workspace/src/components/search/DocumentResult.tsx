'use client';
// src/components/search/DocumentResult.tsx — Search result item for documents with metadata inspection

import { useState } from 'react';
import { motion } from 'framer-motion';
import { FileText, Plus, Check, Info, ExternalLink } from 'lucide-react';
import { useChatStore, ContextItem } from '@/store/chat';
import DocumentMetadataModal from '@/components/modals/DocumentMetadataModal';

interface DocumentResultProps {
  document: {
    id: string;
    sourceId: string;
    docId?: string;
    title: string;
    sourceName?: string;
    fileType?: string;
    sectionTitle?: string;
    snippet: string;
    fullContext?: string;
    pageNum?: number;
    relevanceScore?: number;
  };
}

export function DocumentResult({ document }: DocumentResultProps) {
  const [showModal, setShowModal] = useState(false);
  const { activeContext, addContextItem, removeContextItem } = useChatStore();
  const isAdded = activeContext.some((c) => c.id === document.id || c.metadata?.sourceId === document.sourceId);

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isAdded) {
      removeContextItem(document.id);
    } else {
      const item: ContextItem = {
        id: document.id,
        type: 'document',
        title: document.title,
        snippet: document.fullContext || document.snippet,
        relevanceScore: document.relevanceScore,
        metadata: {
          sourceId: document.sourceId,
          sectionTitle: document.sectionTitle,
          pageNum: document.pageNum,
          fileType: document.fileType,
        },
      };
      addContextItem(item);
    }
  };

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        onClick={() => setShowModal(true)}
        className="p-4 rounded-2xl transition-all duration-200 cursor-pointer group hover:shadow-md"
        style={{
          background: 'var(--bg-elevated)',
          border: isAdded ? '1px solid var(--accent)' : '1px solid var(--border)',
        }}
      >
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex items-center gap-2.5 min-w-0">
            <div
              className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0 transition-transform group-hover:scale-105"
              style={{ background: 'rgba(99,102,241,0.1)', color: 'var(--accent)' }}
            >
              <FileText className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <h4 className="text-sm font-semibold truncate transition-colors group-hover:text-[var(--accent)]" style={{ color: 'var(--text-primary)' }}>
                {document.title}
              </h4>
              <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                {document.sectionTitle && <span>§ {document.sectionTitle}</span>}
                {document.pageNum && <span>p. {document.pageNum}</span>}
                {document.relevanceScore !== undefined && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-mono" style={{ background: 'var(--bg-active)' }}>
                    {Math.round(document.relevanceScore * 100)}% match
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1.5 flex-shrink-0">
            <button
              onClick={(e) => {
                e.stopPropagation();
                setShowModal(true);
              }}
              className="p-1.5 rounded-xl text-xs transition-colors hover:bg-[var(--bg-active)] text-zinc-400 hover:text-zinc-200"
              title="View Document Metadata & Chunks"
            >
              <Info className="w-3.5 h-3.5" />
            </button>

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
        </div>

        <p className="text-xs leading-relaxed line-clamp-3" style={{ color: 'var(--text-secondary)' }}>
          {document.snippet}
        </p>

        <div className="mt-2 pt-2 flex items-center justify-between text-[11px]" style={{ borderTop: '1px solid rgba(255,255,255,0.04)', color: 'var(--text-muted)' }}>
          <span className="flex items-center gap-1 group-hover:text-[var(--accent)] transition-colors">
            Click card to view full metadata & structure
          </span>
          <span className="font-mono uppercase text-[10px]">{document.fileType || 'PDF'}</span>
        </div>
      </motion.div>

      {/* Full Document Metadata Modal */}
      <DocumentMetadataModal
        sourceId={document.sourceId}
        isOpen={showModal}
        onClose={() => setShowModal(false)}
      />
    </>
  );
}

export default DocumentResult;
