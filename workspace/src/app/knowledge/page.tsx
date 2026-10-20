'use client';
// src/app/knowledge/page.tsx — Knowledge Base browser for all authenticated users

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Database, Search, FileText, Video, Image, Music,
  Loader2, Sparkles
} from 'lucide-react';
import Sidebar from '@/components/layout/Sidebar';
import DocumentMetadataModal from '@/components/modals/DocumentMetadataModal';
import { useChatStore } from '@/store/chat';
import { toast } from 'sonner';

interface KnowledgeSource {
  id: string;
  original_name: string;
  file_type: string;
  file_size: number;
  upload_date: string;
  processing_status: string;
  chunk_count: number;
}

const TYPE_ICONS: Record<string, typeof FileText> = {
  pdf: FileText, docx: FileText, doc: FileText, txt: FileText, md: FileText,
  csv: FileText, xlsx: FileText, xls: FileText, json: FileText, pptx: FileText,
  jpg: Image, jpeg: Image, png: Image, webp: Image, gif: Image, bmp: Image, heic: Image, tiff: Image,
  mp4: Video, avi: Video, mov: Video, mkv: Video, webm: Video,
  mp3: Music, wav: Music, m4a: Music, ogg: Music, flac: Music, aac: Music, opus: Music,
};

type ResultCategory = 'document' | 'video' | 'image' | 'audio';

interface LocalResult {
  id: string;
  sourceId: string;
  title: string;
  snippet: string;
  category: ResultCategory;
  relevanceScore: number;
  startTime?: number | null;
  thumbnail?: string;
}

interface LocalResults {
  documents: LocalResult[];
  videos: LocalResult[];
  images: LocalResult[];
  audio: LocalResult[];
}

const CATEGORY_STYLE: Record<ResultCategory, { icon: typeof FileText; color: string; label: string }> = {
  document: { icon: FileText, color: 'var(--accent)', label: 'Document' },
  video: { icon: Video, color: '#f43f5e', label: 'Video' },
  image: { icon: Image, color: '#10b981', label: 'Image' },
  audio: { icon: Music, color: '#f59e0b', label: 'Audio' },
};

function formatTime(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}

function formatBytes(bytes?: number | null): string {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function KnowledgePage() {
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [results, setResults] = useState<LocalResults | null>(null);
  const [searching, setSearching] = useState(false);
  const [inspect, setInspect] = useState<{ id: string; t?: number } | null>(null);
  const { setSearchMode, addContextItem } = useChatStore();

  useEffect(() => {
    let current = true;
    fetch('/api/knowledge')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => { if (current && data) setSources(data.sources || []); })
      .catch(() => { if (current) toast.error('Could not load knowledge sources'); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, []);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const res = await fetch('/api/search/local', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery }),
      });
      if (res.ok) {
        const data = await res.json();
        setResults({
          documents: data.documents || [],
          videos: data.videos || [],
          images: data.images || [],
          audio: data.audio || [],
        });
      } else {
        toast.error('Search failed');
      }
    } catch {
      toast.error('Search failed');
    } finally {
      setSearching(false);
    }
  };

  const addToChat = (item: LocalResult) => {
    addContextItem({
      id: item.id,
      type: item.category,
      title: item.title,
      snippet: item.snippet,
      relevanceScore: item.relevanceScore,
      metadata: { sourceId: item.sourceId, startTime: item.startTime ?? undefined },
    });
    setSearchMode('local');
    toast.success('Added to chat context');
  };

  const allResults: LocalResult[] = results
    ? [...results.documents, ...results.videos, ...results.images, ...results.audio]
        .sort((a, b) => b.relevanceScore - a.relevanceScore)
    : [];

  const filteredSources = sources.filter((s) =>
    s.original_name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex flex-col md:flex-row h-dvh overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      <Sidebar />
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-8">
          <div className="mb-8">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-2xl flex items-center justify-center"
                style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}>
                <Database className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>Knowledge Base</h1>
                <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>Search across documents, images, videos and audio</p>
              </div>
            </div>

            {/* Search */}
            <form onSubmit={handleSearch}>
              <div className="flex gap-3">
                <div className="flex-1 relative">
                  <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: 'var(--text-muted)' }} />
                  <input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search documents, videos, and more..."
                    className="w-full pl-10 pr-4 py-3 rounded-xl text-sm outline-none"
                    style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                    onFocus={(e) => { e.target.style.borderColor = 'var(--accent)'; }}
                    onBlur={(e) => { e.target.style.borderColor = 'var(--border)'; }}
                  />
                </div>
                <motion.button type="submit" disabled={searching || !searchQuery.trim()}
                  whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                  className="px-6 py-3 rounded-xl font-semibold text-sm text-white disabled:opacity-50"
                  style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
                  {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Search'}
                </motion.button>
              </div>
            </form>
          </div>

          {/* Search Results */}
          {results && (
            <div className="mb-8">
              <h2 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-secondary)' }}>
                Search Results for &quot;{searchQuery}&quot;
              </h2>
              {allResults.length === 0 ? (
                <p className="text-sm" style={{ color: 'var(--text-muted)' }}>No results found. Try different keywords.</p>
              ) : (
                <div className="space-y-3">
                  {allResults.map((item) => {
                    const style = CATEGORY_STYLE[item.category] || CATEGORY_STYLE.document;
                    const Icon = style.icon;
                    return (
                      <motion.div key={item.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                        className="p-4 rounded-2xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                        <div className="flex items-start justify-between gap-3">
                          {item.thumbnail && item.category !== 'audio' && (
                            /* eslint-disable-next-line @next/next/no-img-element */
                            <img src={item.thumbnail} alt="" loading="lazy"
                              className="w-16 h-16 rounded-xl object-cover flex-shrink-0"
                              style={{ background: 'var(--bg-active)' }}
                              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }} />
                          )}
                          <button type="button" className="flex-1 min-w-0 text-left group"
                            onClick={() => setInspect({ id: item.sourceId, t: item.startTime ?? undefined })}>
                            <div className="flex items-center gap-2 mb-1">
                              <Icon className="w-4 h-4 flex-shrink-0" style={{ color: style.color }} />
                              <span className="font-semibold text-sm truncate group-hover:underline" style={{ color: 'var(--text-primary)' }}>{item.title}</span>
                              {typeof item.startTime === 'number' && (
                                <span className="text-[11px] px-2 py-0.5 rounded-full font-mono"
                                  style={{ background: 'var(--bg-active)', color: style.color }}>
                                  {formatTime(item.startTime)}
                                </span>
                              )}
                            </div>
                            <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>{item.snippet}</p>
                          </button>
                          <button onClick={() => addToChat(item)}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium flex-shrink-0 transition-all hover:bg-[var(--accent-muted)]"
                            style={{ border: '1px solid var(--border)', color: 'var(--accent)' }}>
                            + Context
                          </button>
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Source List */}
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--accent)' }} />
            </div>
          ) : (
            <div>
              <h2 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--text-secondary)' }}>
                <Database className="w-4 h-4" />
                All Knowledge Sources ({filteredSources.length})
              </h2>
              {filteredSources.length === 0 ? (
                <div className="text-center py-16">
                  <Sparkles className="w-10 h-10 mx-auto mb-3 opacity-30" style={{ color: 'var(--text-muted)' }} />
                  <p className="text-sm" style={{ color: 'var(--text-muted)' }}>No knowledge sources available yet.</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {filteredSources.map((source, i) => {
                    const TypeIcon = TYPE_ICONS[source.file_type] || FileText;
                    return (
                      <motion.button key={source.id} type="button" onClick={() => setInspect({ id: source.id })}
                        initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: Math.min(i, 20) * 0.02 }}
                        className="w-full text-left flex items-center gap-3 p-4 rounded-2xl transition-all hover:bg-[var(--bg-hover)]"
                        style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                        <div className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
                          style={{ background: 'var(--accent-muted)' }}>
                          <TypeIcon className="w-4 h-4" style={{ color: 'var(--accent)' }} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate" style={{ color: 'var(--text-primary)' }}>{source.original_name}</p>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded"
                              style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}>{source.file_type}</span>
                            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                              {formatBytes(source.file_size)}
                            </span>
                            {source.chunk_count > 0 && (
                              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                                {source.chunk_count} chunks
                              </span>
                            )}
                          </div>
                        </div>
                        <span className={`text-[11px] font-semibold px-2 py-1 rounded-full ${
                          source.processing_status === 'completed' ? 'text-emerald-400' : 'text-amber-400'
                        }`} style={{
                          background: source.processing_status === 'completed' ? 'rgba(16,185,129,0.1)' : 'rgba(245,158,11,0.1)'
                        }}>
                          {source.processing_status === 'completed' ? 'Ready' : source.processing_status}
                        </span>
                      </motion.button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <DocumentMetadataModal sourceId={inspect?.id ?? null} initialTimestamp={inspect?.t}
        isOpen={Boolean(inspect)} onClose={() => setInspect(null)} />
    </div>
  );
}
