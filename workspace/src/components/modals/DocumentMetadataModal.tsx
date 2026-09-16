'use client';
// src/components/modals/DocumentMetadataModal.tsx — Full metadata & media player inspector for Local & Internet sources

import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, FileText, Video, Image as ImageIcon, CheckCircle, Clock,
  Loader2, XCircle, Copy, Check, Plus, Database, Sparkles,
  Layers, FileCode, ChevronRight, User, Calendar, HardDrive, RefreshCw,
  Play, Pause, Volume2, Maximize2, ExternalLink, Cpu, Music, BookOpen, Newspaper, Globe,
  Terminal, AlertCircle, ScanFace, Activity, Search, ShieldCheck, Workflow
} from 'lucide-react';
import { useChatStore, ContextItem } from '@/store/chat';
import { toast } from 'sonner';

export interface ProcessingLogEntry {
  timestamp: string;
  prefix: string;
  message: string;
}

export interface ProcessingCounts {
  text_chars?: number;
  text_chunks?: number;
  text_chunks_embedded?: number;
  pages_processed?: number;
  images_extracted?: number;
  image_embeddings_stored?: number;
  frames_sampled?: number;
  ocr_chars?: number;
  ocr_chunks?: number;
  faces_detected?: number;
  face_embeddings_stored?: number;
  transcripts_generated?: number;
}

export interface ProcessingStorageInfo {
  sqlite_tables?: string[];
  faiss_indexes?: string[];
  file_directories?: string[];
}

export interface ProcessingInfo {
  source_id?: string;
  filename?: string;
  file_type?: string;
  file_size?: number;
  processing_status?: string;
  error_message?: string;
  processing_time_seconds?: number;
  methods_used?: Record<string, string>;
  models_used?: Record<string, string>;
  counts?: ProcessingCounts;
  storage_info?: ProcessingStorageInfo;
  logs?: ProcessingLogEntry[];
}

export interface InternetItemDetail {
  id: string;
  category: 'web' | 'news' | 'paper' | 'video' | 'image';
  title: string;
  url: string;
  snippet: string;
  domain: string;
  publishedDate?: string;
  author?: string;
  thumbnail?: string;
  relevanceScore?: number;
}

export interface KeyframeDetail {
  id: string;
  timestamp: number;
  frame_number: number;
  scene_id: number;
  frame_path: string;
  visual_description?: string;
}

export interface DocumentMetadataModalProps {
  sourceId: string | null;
  initialTimestamp?: number;
  internetItem?: InternetItemDetail | null;
  isOpen: boolean;
  onClose: () => void;
  onReprocess?: (id: string) => void;
  onFindSimilar?: (sourceId: string, itemTitle?: string) => void;
}

interface SourceDetail {
  id: string;
  filename: string;
  original_name: string;
  file_type: string;
  file_size: number;
  file_path: string;
  upload_date: string;
  processing_status: 'uploaded' | 'processing' | 'indexing' | 'completed' | 'failed';
  error_message?: string;
  chunk_count: number;
  transcript_count: number;
  face_count: number;
  frame_count?: number;
  duration_seconds?: number;
  page_count?: number;
  uploader_name?: string;
  uploader_email?: string;
  metadata_json?: string;
}

interface SectionItem {
  id: string;
  section_title: string;
  page_num: number;
  order_idx: number;
  char_count: number;
}

interface ChunkItem {
  id: string;
  chunk_order: number;
  page_num: number;
  char_count: number;
  chunk_text: string;
}

interface TranscriptItem {
  id: string;
  start_time: number;
  end_time: number;
  text: string;
}

function formatBytes(bytes?: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatSeconds(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function formatDuration(seconds?: number): string {
  if (!seconds) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s}s`;
}

function extractYouTubeId(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.hostname.includes('youtube.com')) return u.searchParams.get('v');
    if (u.hostname.includes('youtu.be')) return u.pathname.slice(1);
  } catch {
    // ignore
  }
  return null;
}

function getPrefixBadgeStyle(prefix: string) {
  switch (prefix) {
    case '[Ingestion]':
      return { bg: 'rgba(99, 102, 241, 0.15)', text: '#818cf8', border: 'rgba(99, 102, 241, 0.3)' };
    case '[OCR]':
      return { bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24', border: 'rgba(245, 158, 11, 0.3)' };
    case '[Embedding]':
      return { bg: 'rgba(168, 85, 247, 0.15)', text: '#c084fc', border: 'rgba(168, 85, 247, 0.3)' };
    case '[FAISS]':
      return { bg: 'rgba(6, 182, 212, 0.15)', text: '#22d3ee', border: 'rgba(6, 182, 212, 0.3)' };
    case '[Face]':
      return { bg: 'rgba(244, 63, 94, 0.15)', text: '#fb7185', border: 'rgba(244, 63, 94, 0.3)' };
    case '[Whisper]':
      return { bg: 'rgba(16, 185, 129, 0.15)', text: '#34d399', border: 'rgba(16, 185, 129, 0.3)' };
    case '[Storage]':
      return { bg: 'rgba(20, 184, 166, 0.15)', text: '#2dd4bf', border: 'rgba(20, 184, 166, 0.3)' };
    default:
      return { bg: 'rgba(255, 255, 255, 0.08)', text: 'var(--text-secondary)', border: 'var(--border)' };
  }
}

export function DocumentMetadataModal({
  sourceId,
  initialTimestamp,
  internetItem,
  isOpen,
  onClose,
  onReprocess,
  onFindSimilar,
}: DocumentMetadataModalProps) {
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'player' | 'keyframes' | 'transcripts' | 'sections' | 'chunks' | 'logs' | 'raw'>('overview');
  const [source, setSource] = useState<SourceDetail | null>(null);
  const [processingInfo, setProcessingInfo] = useState<ProcessingInfo | null>(null);
  const [logSearch, setLogSearch] = useState('');
  const [logFilterPrefix, setLogFilterPrefix] = useState<string>('all');
  const [sections, setSections] = useState<SectionItem[]>([]);
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [transcripts, setTranscripts] = useState<TranscriptItem[]>([]);
  const [frames, setFrames] = useState<KeyframeDetail[]>([]);
  const [copied, setCopied] = useState(false);

  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const { activeContext, addContextItem, removeContextItem } = useChatStore();

  useEffect(() => {
    if (!isOpen) return;

    if (internetItem) {
      // Internet item view
      setActiveTab(internetItem.category === 'video' || internetItem.category === 'image' ? 'player' : 'overview');
      return;
    }

    if (!sourceId) {
      setSource(null);
      setProcessingInfo(null);
      return;
    }

    let isMounted = true;
    setLoading(true);

    fetch(`/api/knowledge/${sourceId}`)
      .then((res) => res.json())
      .then((data) => {
        if (!isMounted) return;
        if (data.source) {
          setSource(data.source);
          setSections(data.sections || []);
          setChunks(data.chunks || []);
          setTranscripts(data.transcripts || []);
          setFrames(data.frames || []);

          let pInfo: ProcessingInfo | null = data.processing_info || null;
          if (!pInfo && data.source.metadata_json) {
            try {
              const meta = JSON.parse(data.source.metadata_json);
              pInfo = meta.processing_info || null;
            } catch {}
          }
          setProcessingInfo(pInfo);

          const ext = (data.source.file_type || '').toLowerCase();
          const isMedia = ['mp4', 'webm', 'mov', 'avi', 'mkv', 'mp3', 'wav', 'm4a', 'ogg', 'jpg', 'png', 'webp'].includes(ext);
          if (isMedia) {
            setActiveTab('player');
          } else {
            setActiveTab('overview');
          }

          // Initial timestamp seek
          if (initialTimestamp !== undefined && initialTimestamp > 0) {
            setTimeout(() => {
              seekMedia(initialTimestamp);
            }, 300);
          }
        }
      })
      .catch(() => {
        if (isMounted) toast.error('Failed to load document metadata');
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, sourceId, initialTimestamp, internetItem]);

  if (!isOpen) return null;

  // Handle local context addition/removal
  const currentId = internetItem ? internetItem.id : source?.id;
  const isAddedToChat = currentId
    ? activeContext.some((c) => c.id === currentId || c.metadata?.sourceId === currentId)
    : false;

  const handleToggleChatContext = () => {
    if (internetItem) {
      if (isAddedToChat) {
        removeContextItem(internetItem.id);
        toast.info('Removed internet source from chat context');
      } else {
        const item: ContextItem = {
          id: internetItem.id,
          type: internetItem.category === 'video' ? 'video' : internetItem.category === 'image' ? 'image' : 'web',
          title: internetItem.title,
          snippet: internetItem.snippet,
          relevanceScore: internetItem.relevanceScore,
          metadata: { url: internetItem.url, domain: internetItem.domain },
        };
        addContextItem(item);
        toast.success('Added internet source to chat context');
      }
      return;
    }

    if (!source) return;

    if (isAddedToChat) {
      removeContextItem(source.id);
      toast.info('Removed from active chat context');
    } else {
      const firstChunkSnippet = chunks.length > 0 ? chunks[0].chunk_text : `${source.original_name} (${source.file_type.toUpperCase()})`;
      const item: ContextItem = {
        id: source.id,
        type: ['mp4', 'mov', 'webm'].includes(source.file_type) ? 'video' : ['jpg', 'png', 'webp'].includes(source.file_type) ? 'image' : 'document',
        title: source.original_name,
        snippet: firstChunkSnippet.slice(0, 500),
        metadata: {
          sourceId: source.id,
          fileType: source.file_type,
          pageCount: source.page_count,
        },
      };
      addContextItem(item);
      toast.success('Added document to active chat context');
    }
  };

  const handleCopyJson = () => {
    const payload = internetItem ? { internetItem } : { source, processing_info: processingInfo, sections, chunks, transcripts, frames };
    navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    setCopied(true);
    toast.success('Metadata copied to clipboard');
    setTimeout(() => setCopied(false), 2000);
  };

  const seekMedia = (seconds: number) => {
    if (mediaRef.current) {
      mediaRef.current.currentTime = seconds;
      mediaRef.current.play().catch(() => {});
    }
  };

  // Local Type Checks
  const fileExt = (source?.file_type || '').toLowerCase();
  const isVideo = ['mp4', 'mov', 'webm', 'avi', 'mkv'].includes(fileExt);
  const isAudio = ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac'].includes(fileExt);
  const isImage = ['jpg', 'png', 'webp', 'jpeg', 'gif', 'bmp'].includes(fileExt);
  const isDocument = ['pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx', 'xls', 'json'].includes(fileExt);

  // Parse custom metadata for internet sources
  let sourceMetadata: Record<string, unknown> = {};
  if (source?.metadata_json) {
    try {
      sourceMetadata = JSON.parse(source.metadata_json);
    } catch {}
  }
  const sourceUrl = (sourceMetadata.url || sourceMetadata.original_url || (source?.file_path?.startsWith('http') ? source.file_path : undefined)) as string | undefined;

  // AI Model attribution for local source
  const aiModelName = isVideo || isAudio
    ? 'Groq Whisper Large v3 (Audio & Video Transcription) + CLIP Keyframe Visual Embeddings'
    : isImage
    ? 'Groq Vision (Visual OCR & Scene Extraction) + CLIP Image Embeddings'
    : isDocument
    ? 'PDFParse v2 + MiniLM Text Vector Embeddings + FTS5 Section Chunker'
    : sourceUrl
    ? 'Web Scraper & Multi-Vector Text Embedding Pipeline'
    : 'Groq Ingestion Pipeline';

  const modelsList = processingInfo?.models_used
    ? Object.values(processingInfo.models_used).join(' · ')
    : null;
  const displayAiModelName = modelsList || aiModelName;

  const filteredLogs = (processingInfo?.logs || []).filter((item) => {
    if (logFilterPrefix !== 'all' && item.prefix !== logFilterPrefix) return false;
    if (logSearch.trim()) {
      const q = logSearch.toLowerCase();
      return item.message.toLowerCase().includes(q) || item.prefix.toLowerCase().includes(q);
    }
    return true;
  });

  const ytVideoId = internetItem?.url ? extractYouTubeId(internetItem.url) : sourceUrl ? extractYouTubeId(sourceUrl) : null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 overflow-hidden">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="absolute inset-0 bg-black/75 backdrop-blur-md"
        />

        {/* Modal Container */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 16 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 16 }}
          transition={{ type: 'spring', duration: 0.35, bounce: 0.15 }}
          className="relative w-full max-w-4xl max-h-[92vh] flex flex-col rounded-3xl overflow-hidden shadow-2xl z-10"
          style={{
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            boxShadow: '0 25px 60px rgba(0,0,0,0.6), 0 0 0 1px rgba(99,102,241,0.15)',
          }}
        >
          {/* Header Bar */}
          <div
            className="p-5 flex items-center justify-between gap-4 flex-shrink-0"
            style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-surface, var(--bg-elevated))' }}
          >
            <div className="flex items-center gap-3 min-w-0">
              <div
                className="w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0 shadow-sm"
                style={{
                  background: isVideo || internetItem?.category === 'video'
                    ? 'rgba(244,63,94,0.15)'
                    : isAudio
                    ? 'rgba(245,158,11,0.15)'
                    : isImage || internetItem?.category === 'image'
                    ? 'rgba(16,185,129,0.15)'
                    : 'rgba(99,102,241,0.15)',
                  color: isVideo || internetItem?.category === 'video'
                    ? '#f43f5e'
                    : isAudio
                    ? '#f59e0b'
                    : isImage || internetItem?.category === 'image'
                    ? '#10b981'
                    : 'var(--accent)',
                }}
              >
                {isVideo || internetItem?.category === 'video' ? (
                  <Video className="w-5 h-5" />
                ) : isAudio ? (
                  <Music className="w-5 h-5" />
                ) : isImage || internetItem?.category === 'image' ? (
                  <ImageIcon className="w-5 h-5" />
                ) : internetItem?.category === 'news' ? (
                  <Newspaper className="w-5 h-5" />
                ) : internetItem?.category === 'paper' ? (
                  <BookOpen className="w-5 h-5" />
                ) : (
                  <FileText className="w-5 h-5" />
                )}
              </div>

              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-bold truncate" style={{ color: 'var(--text-primary)' }}>
                    {internetItem ? internetItem.title : source?.original_name || 'Source Details'}
                  </h2>
                  <span
                    className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full flex-shrink-0"
                    style={{ background: 'var(--bg-active)', color: 'var(--text-secondary)' }}
                  >
                    {internetItem ? internetItem.category : source?.file_type || 'SOURCE'}
                  </span>
                </div>
                <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                  {internetItem ? internetItem.domain : `Source ID: ${source?.id || sourceId}`}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              {source && onFindSimilar && (
                <button
                  onClick={() => {
                    onFindSimilar(source.id, source.original_name);
                    onClose();
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all hover:bg-cyan-500/20 text-cyan-400"
                  style={{ border: '1px solid rgba(6,182,212,0.3)', background: 'rgba(6,182,212,0.1)' }}
                  title="Discover similar sources across the knowledge base"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>Find Similar</span>
                </button>
              )}
              <button
                onClick={handleCopyJson}
                className="p-2 rounded-xl text-xs transition-colors hover:bg-[var(--bg-hover)]"
                style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                title="Copy raw metadata"
              >
                {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
              </button>
              <button
                onClick={onClose}
                className="p-2 rounded-xl transition-colors hover:bg-[var(--bg-hover)]"
                style={{ border: '1px solid var(--border)', color: 'var(--text-muted)' }}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div
            className="flex items-center gap-1 px-5 py-2 flex-shrink-0 overflow-x-auto"
            style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-base)' }}
          >
            {[
              { id: 'overview', label: 'Overview & Metadata', icon: Database, show: true },
              { id: 'player', label: isVideo || internetItem?.category === 'video' ? 'Video Player' : isAudio ? 'Audio Player' : 'Media Preview', icon: Play, show: isVideo || isAudio || isImage || Boolean(internetItem?.category === 'video' || internetItem?.category === 'image') },
              { id: 'keyframes', label: `Keyframes (${frames.length})`, icon: ImageIcon, show: isVideo && frames.length > 0 },
              { id: 'transcripts', label: `Transcripts (${transcripts.length})`, icon: Clock, show: (isVideo || isAudio) && transcripts.length > 0 },
              { id: 'sections', label: `Sections (${sections.length})`, icon: Layers, show: isDocument && sections.length > 0 },
              { id: 'chunks', label: `Indexed Chunks (${chunks.length || source?.chunk_count || 0})`, icon: Sparkles, show: Boolean(source) },
              { id: 'logs', label: `Ingestion Logs (${processingInfo?.logs?.length || 0})`, icon: Terminal, show: Boolean(processingInfo?.logs && processingInfo.logs.length > 0) },
              { id: 'raw', label: 'Raw JSON', icon: FileCode, show: true },
            ]
              .filter((t) => t.show)
              .map((tab) => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id as typeof activeTab)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex-shrink-0"
                    style={{
                      background: isActive ? 'var(--bg-elevated)' : 'transparent',
                      color: isActive ? 'var(--accent)' : 'var(--text-muted)',
                      border: isActive ? '1px solid var(--border)' : '1px solid transparent',
                    }}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    <span>{tab.label}</span>
                  </button>
                );
              })}
          </div>

          {/* Body Content */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {loading ? (
              <div className="flex flex-col items-center justify-center py-20 gap-3">
                <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--accent)' }} />
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Loading source details...</p>
              </div>
            ) : internetItem ? (
              /* ─── INTERNET ITEM VIEW ─── */
              <div className="space-y-6">
                {/* Embedded Player / Image if applicable */}
                {activeTab === 'player' && ytVideoId && (
                  <div className="aspect-video w-full rounded-2xl overflow-hidden bg-black shadow-lg border border-[var(--border)]">
                    <iframe
                      src={`https://www.youtube-nocookie.com/embed/${ytVideoId}?autoplay=1`}
                      title={internetItem.title}
                      className="w-full h-full border-0"
                      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                      allowFullScreen
                    />
                  </div>
                )}

                {activeTab === 'player' && internetItem.category === 'image' && internetItem.url && (
                  <div className="w-full max-h-[400px] flex items-center justify-center rounded-2xl overflow-hidden bg-black/40 border border-[var(--border)] p-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={internetItem.url} alt={internetItem.title} className="max-h-[380px] object-contain rounded-xl" />
                  </div>
                )}

                {/* Metadata Card */}
                <div className="p-4 rounded-2xl space-y-4" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-cyan-400">Internet Intelligence Source</span>
                    <a
                      href={internetItem.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 transition-colors"
                    >
                      <span>Open Original Web Page</span>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  </div>

                  <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{internetItem.title}</h3>
                  <p className="text-xs leading-relaxed select-text" style={{ color: 'var(--text-secondary)' }}>{internetItem.snippet}</p>

                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-2">
                    <div className="p-3 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                      <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Publisher / Domain</span>
                      <p className="text-xs font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{internetItem.domain}</p>
                    </div>
                    {internetItem.author && (
                      <div className="p-3 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                        <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Author</span>
                        <p className="text-xs font-bold mt-0.5 truncate" style={{ color: 'var(--text-primary)' }}>{internetItem.author}</p>
                      </div>
                    )}
                    {internetItem.publishedDate && (
                      <div className="p-3 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                        <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Date</span>
                        <p className="text-xs font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{internetItem.publishedDate}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : source ? (
              /* ─── LOCAL SOURCE VIEW ─── */
              <div className="space-y-6">
                {/* Media Player Tab */}
                {activeTab === 'player' && (
                  <div className="space-y-4">
                    {isVideo && (
                      <div className="aspect-video w-full rounded-2xl overflow-hidden bg-black shadow-xl border border-[var(--border)] relative">
                        <video
                          ref={mediaRef as React.RefObject<HTMLVideoElement>}
                          controls
                          className="w-full h-full object-contain"
                          src={`/api/knowledge/${source.id}/file`}
                          onLoadedMetadata={() => {
                            if (initialTimestamp !== undefined && initialTimestamp > 0 && mediaRef.current) {
                              mediaRef.current.currentTime = initialTimestamp;
                              mediaRef.current.play().catch(() => {});
                            }
                          }}
                        />
                      </div>
                    )}

                    {isAudio && (
                      <div className="p-6 rounded-2xl flex flex-col items-center justify-center gap-4 text-center shadow-lg"
                        style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                        <div className="w-14 h-14 rounded-2xl flex items-center justify-center shadow-md"
                          style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b' }}>
                          <Music className="w-7 h-7" />
                        </div>
                        <div>
                          <h4 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{source.original_name}</h4>
                          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{formatDuration(source.duration_seconds)} · {formatBytes(source.file_size)}</p>
                        </div>
                        <audio
                          ref={mediaRef as React.RefObject<HTMLAudioElement>}
                          controls
                          className="w-full max-w-md mt-2"
                          src={`/api/knowledge/${source.id}/file`}
                          onLoadedMetadata={() => {
                            if (initialTimestamp !== undefined && initialTimestamp > 0 && mediaRef.current) {
                              mediaRef.current.currentTime = initialTimestamp;
                              mediaRef.current.play().catch(() => {});
                            }
                          }}
                        />
                      </div>
                    )}

                    {isImage && (
                      <div className="w-full max-h-[400px] flex items-center justify-center rounded-2xl overflow-hidden bg-black/30 border border-[var(--border)] p-2">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={`/api/knowledge/${source.id}/file`} alt={source.original_name} className="max-h-[380px] object-contain rounded-xl" />
                      </div>
                    )}

                    {isDocument && (
                      <div className="p-8 rounded-2xl flex items-center justify-between gap-4"
                        style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                        <div className="flex items-center gap-3">
                          <FileText className="w-8 h-8 text-indigo-400" />
                          <div>
                            <h4 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{source.original_name}</h4>
                            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{source.page_count || 1} Pages · {formatBytes(source.file_size)}</p>
                          </div>
                        </div>
                        <a
                          href={`/api/knowledge/${source.id}/file`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 transition-colors"
                        >
                          <span>Open File</span>
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      </div>
                    )}
                  </div>
                )}

                {/* Keyframes Tab */}
                {activeTab === 'keyframes' && (
                  <div className="space-y-4">
                    <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
                      Keyframes extracted via scene-change detection & indexed with multimodal visual embeddings:
                    </p>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 max-h-[420px] overflow-y-auto pr-1">
                      {frames.map((frame) => (
                        <div
                          key={frame.id}
                          onClick={() => {
                            setActiveTab('player');
                            seekMedia(frame.timestamp);
                          }}
                          className="p-2 rounded-2xl group cursor-pointer transition-all hover:scale-[1.02] relative"
                          style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}
                        >
                          <div className="aspect-video w-full rounded-xl overflow-hidden bg-black/60 relative mb-2">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={`/api/knowledge/${source.id}/frames/${frame.id}`}
                              alt={`Scene ${frame.scene_id}`}
                              className="w-full h-full object-cover group-hover:opacity-90 transition-opacity"
                            />
                            <div className="absolute top-1.5 left-1.5 px-2 py-0.5 rounded-md bg-black/70 backdrop-blur-sm text-[10px] font-bold text-white flex items-center gap-1">
                              <span>Scene #{frame.scene_id}</span>
                            </div>
                            <div className="absolute bottom-1.5 right-1.5 px-2 py-0.5 rounded-md bg-rose-500/90 text-white text-[10px] font-mono font-bold flex items-center gap-1 shadow-sm">
                              <Play className="w-2.5 h-2.5" />
                              <span>{formatSeconds(frame.timestamp)}</span>
                            </div>
                          </div>
                          <p className="text-[11px] font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
                            Timestamp: {formatSeconds(frame.timestamp)}
                          </p>
                          {frame.visual_description && (
                            <p className="text-[10px] line-clamp-1 mt-0.5" style={{ color: 'var(--text-muted)' }}>
                              {frame.visual_description}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Transcripts Tab with Seek Action */}
                {activeTab === 'transcripts' && (
                  <div className="space-y-3">
                    <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
                      Click any timestamp to seek and play that exact moment in the media player:
                    </p>
                    <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
                      {transcripts.map((t) => (
                        <div
                          key={t.id}
                          onClick={() => {
                            setActiveTab('player');
                            seekMedia(t.start_time);
                          }}
                          className="p-3 rounded-xl flex items-start gap-3 cursor-pointer hover:border-indigo-500/40 transition-all group"
                          style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}
                        >
                          <button
                            type="button"
                            className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] font-mono font-bold flex-shrink-0 group-hover:bg-indigo-500 group-hover:text-white transition-colors"
                            style={{ background: 'var(--bg-active)', color: 'var(--accent)' }}
                          >
                            <Play className="w-3 h-3" />
                            <span>{formatSeconds(t.start_time)}</span>
                          </button>
                          <p className="text-xs leading-relaxed select-text" style={{ color: 'var(--text-secondary)' }}>
                            {t.text}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Overview & Metadata Tab */}
                {(activeTab === 'overview' || activeTab === 'player') && (
                  <div className="space-y-4">
                    {/* AI Model Attribution Card */}
                    <div
                      className="p-4 rounded-2xl flex items-center justify-between gap-3 shadow-sm"
                      style={{ background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.18)' }}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-xl flex items-center justify-center"
                          style={{ background: 'var(--accent)', color: '#fff' }}>
                          <Cpu className="w-4 h-4" />
                        </div>
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--accent)' }}>
                            AI Processing Engine / Models Used
                          </p>
                          <p className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
                            {displayAiModelName}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {processingInfo?.processing_time_seconds !== undefined && (
                          <span className="text-[10px] font-mono px-2 py-1 rounded-lg flex items-center gap-1"
                            style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                            <Clock className="w-3 h-3 text-emerald-400" />
                            <span>{processingInfo.processing_time_seconds}s</span>
                          </span>
                        )}
                        <span className="text-[10px] font-mono px-2 py-1 rounded-lg"
                          style={{
                            background: source.processing_status === 'failed' ? 'rgba(244,63,94,0.15)' : 'var(--bg-elevated)',
                            color: source.processing_status === 'failed' ? '#fb7185' : 'var(--text-muted)'
                          }}>
                          Status: {source.processing_status.toUpperCase()}
                        </span>
                      </div>
                    </div>

                    {/* Metadata Grid */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                      <div className="p-3.5 rounded-2xl" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                        <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>File Size</span>
                        <p className="text-sm font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{formatBytes(source.file_size)}</p>
                      </div>

                      <div className="p-3.5 rounded-2xl" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                        <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Format</span>
                        <p className="text-sm font-bold mt-0.5 uppercase" style={{ color: 'var(--text-primary)' }}>{source.file_type}</p>
                      </div>

                      {source.duration_seconds ? (
                        <div className="p-3.5 rounded-2xl" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                          <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Duration</span>
                          <p className="text-sm font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{formatDuration(source.duration_seconds)}</p>
                        </div>
                      ) : (
                        <div className="p-3.5 rounded-2xl" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                          <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Pages</span>
                          <p className="text-sm font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{source.page_count || 1}</p>
                        </div>
                      )}

                      <div className="p-3.5 rounded-2xl" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                        <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Indexed Chunks</span>
                        <p className="text-sm font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{source.chunk_count || chunks.length || 0}</p>
                      </div>
                    </div>

                    {sourceUrl && (
                      <div className="p-4 rounded-2xl flex items-center justify-between gap-3"
                        style={{ background: 'rgba(6,182,212,0.08)', border: '1px solid rgba(6,182,212,0.25)' }}>
                        <div className="flex items-center gap-3 min-w-0">
                          <Globe className="w-5 h-5 text-cyan-400 flex-shrink-0" />
                          <div className="min-w-0">
                            <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-400">Original Internet Source URL</span>
                            <p className="text-xs font-medium text-[var(--text-primary)] truncate">{sourceUrl}</p>
                          </div>
                        </div>
                        <a
                          href={sourceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 text-xs font-bold flex-shrink-0 transition-colors"
                        >
                          <span>Visit Source</span>
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      </div>
                    )}

                    {/* Processing Error Notice */}
                    {(source.processing_status === 'failed' || processingInfo?.error_message) && (
                      <div
                        className="p-4 rounded-2xl flex items-start gap-3 shadow-sm"
                        style={{ background: 'rgba(244,63,94,0.1)', border: '1px solid rgba(244,63,94,0.3)' }}
                      >
                        <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
                        <div className="min-w-0">
                          <p className="text-xs font-bold text-rose-300 uppercase tracking-wider">Processing Error Notice</p>
                          <p className="text-xs text-rose-200 mt-1 font-mono break-words select-text">
                            {processingInfo?.error_message || source.error_message || 'An error occurred during file ingestion.'}
                          </p>
                          {onReprocess && (
                            <button
                              onClick={() => onReprocess(source.id)}
                              className="mt-2.5 flex items-center gap-1.5 px-3 py-1 rounded-xl text-xs font-semibold bg-rose-500/20 text-rose-300 hover:bg-rose-500/30 transition-colors border border-rose-500/40"
                            >
                              <RefreshCw className="w-3.5 h-3.5" />
                              <span>Retry Reprocessing</span>
                            </button>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Extended Ingestion & Processing Details */}
                    {processingInfo && (
                      <div className="space-y-4 pt-1">
                        {/* Processing Methods Used */}
                        {processingInfo.methods_used && Object.keys(processingInfo.methods_used).length > 0 && (
                          <div className="p-3.5 rounded-2xl space-y-2.5" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                            <div className="flex items-center gap-1.5">
                              <Workflow className="w-3.5 h-3.5 text-indigo-400" />
                              <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-primary)' }}>
                                Processing Methods Used
                              </span>
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                              {Object.entries(processingInfo.methods_used).map(([mKey, mVal]) => (
                                <div
                                  key={mKey}
                                  className="px-3 py-2 rounded-xl flex items-start justify-between gap-2"
                                  style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
                                >
                                  <div>
                                    <span className="text-[10px] uppercase font-semibold text-[var(--text-muted)] block">
                                      {mKey.replace(/_/g, ' ')}
                                    </span>
                                    <span className="text-xs font-semibold text-[var(--text-primary)]">
                                      {mVal}
                                    </span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Models Used */}
                        {processingInfo.models_used && Object.keys(processingInfo.models_used).length > 0 && (
                          <div className="p-3.5 rounded-2xl space-y-2.5" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                            <div className="flex items-center gap-1.5">
                              <Cpu className="w-3.5 h-3.5 text-purple-400" />
                              <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-primary)' }}>
                                Models Executed
                              </span>
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                              {Object.entries(processingInfo.models_used).map(([modelKey, modelVal]) => (
                                <div
                                  key={modelKey}
                                  className="px-3 py-2 rounded-xl flex flex-col justify-between"
                                  style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
                                >
                                  <span className="text-[10px] uppercase font-semibold text-purple-300">
                                    {modelKey.replace(/_/g, ' ')}
                                  </span>
                                  <span className="text-xs font-mono font-medium truncate mt-0.5 text-[var(--text-primary)]" title={modelVal}>
                                    {modelVal}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Pipeline Statistics & Counts */}
                        {processingInfo.counts && (
                          <div className="p-3.5 rounded-2xl space-y-2.5" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                            <div className="flex items-center gap-1.5">
                              <Activity className="w-3.5 h-3.5 text-emerald-400" />
                              <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-primary)' }}>
                                Pipeline Statistics & Counts
                              </span>
                            </div>
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                              {processingInfo.counts.text_chars !== undefined && processingInfo.counts.text_chars > 0 && (
                                <div className="p-2.5 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Text Extracted</span>
                                  <p className="text-xs font-bold font-mono mt-0.5 text-[var(--text-primary)]">
                                    {processingInfo.counts.text_chars.toLocaleString()} chars
                                  </p>
                                </div>
                              )}
                              {processingInfo.counts.text_chunks !== undefined && (
                                <div className="p-2.5 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Text Chunks</span>
                                  <p className="text-xs font-bold font-mono mt-0.5 text-[var(--text-primary)]">
                                    {processingInfo.counts.text_chunks} created
                                  </p>
                                </div>
                              )}
                              {processingInfo.counts.text_chunks_embedded !== undefined && (
                                <div className="p-2.5 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Embedded Chunks</span>
                                  <p className="text-xs font-bold font-mono mt-0.5 text-indigo-400">
                                    {processingInfo.counts.text_chunks_embedded} stored
                                  </p>
                                </div>
                              )}
                              {processingInfo.counts.pages_processed !== undefined && processingInfo.counts.pages_processed > 0 && (
                                <div className="p-2.5 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Pages Processed</span>
                                  <p className="text-xs font-bold font-mono mt-0.5 text-[var(--text-primary)]">
                                    {processingInfo.counts.pages_processed} pages
                                  </p>
                                </div>
                              )}
                              {processingInfo.counts.images_extracted !== undefined && processingInfo.counts.images_extracted > 0 && (
                                <div className="p-2.5 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Images Extracted</span>
                                  <p className="text-xs font-bold font-mono mt-0.5 text-[var(--text-primary)]">
                                    {processingInfo.counts.images_extracted} images
                                  </p>
                                </div>
                              )}
                              {processingInfo.counts.frames_sampled !== undefined && processingInfo.counts.frames_sampled > 0 && (
                                <div className="p-2.5 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Frames Sampled</span>
                                  <p className="text-xs font-bold font-mono mt-0.5 text-[var(--text-primary)]">
                                    {processingInfo.counts.frames_sampled} frames
                                  </p>
                                </div>
                              )}
                              {processingInfo.counts.ocr_chars !== undefined && processingInfo.counts.ocr_chars > 0 && (
                                <div className="p-2.5 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>OCR Characters</span>
                                  <p className="text-xs font-bold font-mono mt-0.5 text-amber-400">
                                    {processingInfo.counts.ocr_chars.toLocaleString()} chars
                                  </p>
                                </div>
                              )}
                              {processingInfo.counts.faces_detected !== undefined && (
                                <div className="p-2.5 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Faces Detected</span>
                                  <p className="text-xs font-bold font-mono mt-0.5 text-rose-400">
                                    {processingInfo.counts.faces_detected} faces
                                  </p>
                                </div>
                              )}
                              {processingInfo.counts.face_embeddings_stored !== undefined && processingInfo.counts.face_embeddings_stored > 0 && (
                                <div className="p-2.5 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Face Embeddings</span>
                                  <p className="text-xs font-bold font-mono mt-0.5 text-rose-400">
                                    {processingInfo.counts.face_embeddings_stored} indexed
                                  </p>
                                </div>
                              )}
                              {processingInfo.counts.transcripts_generated !== undefined && processingInfo.counts.transcripts_generated > 0 && (
                                <div className="p-2.5 rounded-xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Transcripts</span>
                                  <p className="text-xs font-bold font-mono mt-0.5 text-emerald-400">
                                    {processingInfo.counts.transcripts_generated} segments
                                  </p>
                                </div>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Storage & FAISS Index Destinations */}
                        {processingInfo.storage_info && (
                          <div className="p-3.5 rounded-2xl space-y-3" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                            <div className="flex items-center gap-1.5">
                              <HardDrive className="w-3.5 h-3.5 text-cyan-400" />
                              <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-primary)' }}>
                                Storage & Vector Index Destinations
                              </span>
                            </div>

                            <div className="space-y-2">
                              {processingInfo.storage_info.sqlite_tables && processingInfo.storage_info.sqlite_tables.length > 0 && (
                                <div>
                                  <span className="text-[10px] uppercase font-semibold text-[var(--text-muted)] block mb-1">
                                    SQLite Tables
                                  </span>
                                  <div className="flex flex-wrap gap-1.5">
                                    {processingInfo.storage_info.sqlite_tables.map((tbl) => (
                                      <span key={tbl} className="text-[11px] font-mono px-2 py-0.5 rounded-lg"
                                        style={{ background: 'rgba(99,102,241,0.12)', color: '#818cf8', border: '1px solid rgba(99,102,241,0.25)' }}>
                                        {tbl}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {processingInfo.storage_info.faiss_indexes && processingInfo.storage_info.faiss_indexes.length > 0 && (
                                <div>
                                  <span className="text-[10px] uppercase font-semibold text-[var(--text-muted)] block mb-1">
                                    FAISS Vector Indexes
                                  </span>
                                  <div className="flex flex-wrap gap-1.5">
                                    {processingInfo.storage_info.faiss_indexes.map((idx) => (
                                      <span key={idx} className="text-[11px] font-mono px-2 py-0.5 rounded-lg"
                                        style={{ background: 'rgba(6,182,212,0.12)', color: '#22d3ee', border: '1px solid rgba(6,182,212,0.25)' }}>
                                        {idx}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Step-by-Step Ingestion Logs (Card) */}
                        {processingInfo.logs && processingInfo.logs.length > 0 && (
                          <div className="p-3.5 rounded-2xl space-y-2.5" style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-1.5">
                                <Terminal className="w-3.5 h-3.5 text-indigo-400" />
                                <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-primary)' }}>
                                  Step-by-Step Ingestion Logs ({processingInfo.logs.length})
                                </span>
                              </div>
                              <button
                                onClick={() => setActiveTab('logs')}
                                className="text-[11px] font-semibold text-indigo-400 hover:text-indigo-300 transition-colors"
                              >
                                Open Full Log View →
                              </button>
                            </div>

                            <div className="max-h-56 overflow-y-auto space-y-1.5 pr-1 font-mono text-[11px] p-2.5 rounded-xl bg-black/40 border border-[var(--border)]">
                              {processingInfo.logs.map((logItem, idx) => {
                                const bStyle = getPrefixBadgeStyle(logItem.prefix);
                                return (
                                  <div key={idx} className="flex items-start gap-2 leading-relaxed select-text">
                                    {logItem.timestamp && (
                                      <span className="text-zinc-500 flex-shrink-0 text-[10px]">
                                        {logItem.timestamp}
                                      </span>
                                    )}
                                    <span
                                      className="px-1.5 py-0.2 rounded text-[10px] font-bold flex-shrink-0"
                                      style={{ background: bStyle.bg, color: bStyle.text, border: `1px solid ${bStyle.border}` }}
                                    >
                                      {logItem.prefix}
                                    </span>
                                    <span className="text-zinc-200 break-words min-w-0">
                                      {logItem.message}
                                    </span>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Sections Tab */}
                {activeTab === 'sections' && (
                  <div className="space-y-3">
                    {sections.map((sec, idx) => (
                      <div key={sec.id} className="p-3.5 rounded-2xl flex items-center justify-between gap-3"
                        style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                        <div className="flex items-center gap-3">
                          <span className="w-6 h-6 rounded-lg flex items-center justify-center text-xs font-bold font-mono"
                            style={{ background: 'var(--bg-active)', color: 'var(--accent)' }}>
                            {idx + 1}
                          </span>
                          <div>
                            <p className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>{sec.section_title || 'Section'}</p>
                            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>Page {sec.page_num} · {sec.char_count} chars</p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Chunks Tab */}
                {activeTab === 'chunks' && (
                  <div className="space-y-3 max-h-[400px] overflow-y-auto">
                    {chunks.map((chk) => (
                      <div key={chk.id} className="p-3.5 rounded-2xl space-y-1"
                        style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                        <div className="flex items-center justify-between text-[11px]" style={{ color: 'var(--text-muted)' }}>
                          <span className="font-mono font-semibold">Chunk #{chk.chunk_order + 1}</span>
                          <span>Page {chk.page_num}</span>
                        </div>
                        <p className="text-xs leading-relaxed font-mono select-text" style={{ color: 'var(--text-secondary)' }}>{chk.chunk_text}</p>
                      </div>
                    ))}
                  </div>
                )}

                {/* Dedicated Ingestion Logs Tab */}
                {activeTab === 'logs' && (
                  <div className="space-y-4">
                    <div className="p-3.5 rounded-2xl flex flex-col sm:flex-row items-center justify-between gap-3"
                      style={{ background: 'var(--bg-base)', border: '1px solid var(--border)' }}>
                      {/* Prefix filter buttons */}
                      <div className="flex items-center gap-1 overflow-x-auto max-w-full pb-1 sm:pb-0">
                        {['all', '[Ingestion]', '[OCR]', '[Embedding]', '[FAISS]', '[Face]', '[Whisper]', '[Storage]'].map((pfx) => {
                          const isActive = logFilterPrefix === pfx;
                          return (
                            <button
                              key={pfx}
                              onClick={() => setLogFilterPrefix(pfx)}
                              className="px-2.5 py-1 rounded-lg text-xs font-semibold transition-all flex-shrink-0"
                              style={{
                                background: isActive ? 'var(--accent)' : 'var(--bg-elevated)',
                                color: isActive ? '#fff' : 'var(--text-muted)',
                                border: isActive ? '1px solid var(--accent)' : '1px solid var(--border)'
                              }}
                            >
                              {pfx === 'all' ? 'All Logs' : pfx}
                            </button>
                          );
                        })}
                      </div>

                      {/* Search box */}
                      <div className="w-full sm:w-60 relative">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-400" />
                        <input
                          type="text"
                          value={logSearch}
                          onChange={(e) => setLogSearch(e.target.value)}
                          placeholder="Filter logs..."
                          className="w-full pl-8 pr-3 py-1 rounded-lg text-xs outline-none font-mono"
                          style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                        />
                      </div>
                    </div>

                    {/* Logs Stream */}
                    <div className="p-4 rounded-2xl font-mono text-xs max-h-[460px] overflow-y-auto space-y-2 bg-black/50 border border-[var(--border)] select-text">
                      {filteredLogs.length === 0 ? (
                        <p className="text-zinc-500 py-6 text-center">No logs match the current filter.</p>
                      ) : (
                        filteredLogs.map((logItem, idx) => {
                          const bStyle = getPrefixBadgeStyle(logItem.prefix);
                          return (
                            <div key={idx} className="flex items-start gap-2.5 leading-relaxed py-0.5 border-b border-white/[0.04] last:border-b-0">
                              {logItem.timestamp && (
                                <span className="text-zinc-500 text-[10px] flex-shrink-0 pt-0.5">
                                  {logItem.timestamp}
                                </span>
                              )}
                              <span
                                className="px-1.5 py-0.5 rounded text-[10px] font-bold flex-shrink-0"
                                style={{ background: bStyle.bg, color: bStyle.text, border: `1px solid ${bStyle.border}` }}
                              >
                                {logItem.prefix}
                              </span>
                              <span className="text-zinc-200 break-words min-w-0">
                                {logItem.message}
                              </span>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                )}

                {/* Raw JSON */}
                {activeTab === 'raw' && (
                  <pre className="p-4 rounded-2xl text-xs font-mono overflow-x-auto select-all"
                    style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                    {JSON.stringify({ source, processing_info: processingInfo, sections, chunks, transcripts, frames }, null, 2)}
                  </pre>
                )}
              </div>
            ) : null}
          </div>

          {/* Footer Action Bar */}
          <div
            className="p-4 flex items-center justify-between gap-3 flex-shrink-0"
            style={{ borderTop: '1px solid var(--border)', background: 'var(--bg-surface, var(--bg-elevated))' }}
          >
            <div className="flex items-center gap-2">
              <button
                onClick={handleToggleChatContext}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all shadow-sm"
                style={{
                  background: isAddedToChat ? 'var(--accent)' : 'rgba(99,102,241,0.12)',
                  color: isAddedToChat ? '#fff' : 'var(--accent)',
                  border: isAddedToChat ? 'none' : '1px solid rgba(99,102,241,0.25)',
                }}
              >
                {isAddedToChat ? (
                  <>
                    <Check className="w-4 h-4" />
                    <span>Active in Chat Context</span>
                  </>
                ) : (
                  <>
                    <Plus className="w-4 h-4" />
                    <span>Include in Chat Context</span>
                  </>
                )}
              </button>

              {source && onFindSimilar && (
                <button
                  onClick={() => {
                    onFindSimilar(source.id, source.original_name);
                    onClose();
                  }}
                  className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold transition-all hover:bg-cyan-500/20 text-cyan-400 shadow-sm"
                  style={{
                    background: 'rgba(6,182,212,0.12)',
                    border: '1px solid rgba(6,182,212,0.3)',
                  }}
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>Find Similar Sources</span>
                </button>
              )}
            </div>

            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-medium transition-colors hover:bg-[var(--bg-hover)]"
              style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
            >
              Close
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}

export default DocumentMetadataModal;
