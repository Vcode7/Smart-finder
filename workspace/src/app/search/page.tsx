'use client';
// src/app/search/page.tsx — Multimodal Smart Finder Search:
// Universal File Upload (Image, Video, Audio, PDF, Article/Clipping) + Local Context Discovery + Enriched Internet Search

import { useState, useEffect, useRef, FormEvent, ChangeEvent, DragEvent } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search, Globe, Database, Sparkles, FileText, CheckCircle2,
  ExternalLink, Info, Loader2, Copy, Check, Plus, RefreshCw,
  X, ArrowRight, BookOpen, Newspaper, MessageSquare,
  Video as VideoIcon, Image as ImageIcon, Music, CheckSquare, Square,
  Layers, ChevronRight, Play, UploadCloud, Eye, Link as LinkIcon,
  UserCheck, Upload, Film, FileAudio
} from 'lucide-react';
import Sidebar from '@/components/layout/Sidebar';
import DocumentMetadataModal from '@/components/modals/DocumentMetadataModal';
import MarkdownMessage from '@/components/chat/MarkdownMessage';
import DiscoveryTrace from '@/components/search/DiscoveryTrace';
import { useChatStore, ContextItem } from '@/store/chat';
import { toast } from 'sonner';
import type { LocalCategorizedItem, InternetCategorizedItem } from '@/types/research';

const SUGGESTED_QUERIES = [
  'SSC Chairman Gopal Krishna',
  'neet scam',
  'ssc exam scam',
  'Climate change resilience & sustainability',
  'Deep learning and computer vision architectures',
];

const SEARCH_PHASES = [
  'Searching multimodal knowledge repository...',
  'Extracting reference embeddings & visual features...',
  'Analyzing cross-modal semantic signals...',
  'Calculating continuous neural similarity & ranking...',
  'Discovering files...',
];

export interface QueryFileState {
  file?: File;
  previewUrl?: string;
  name: string;
  type: 'image' | 'video' | 'audio' | 'document' | 'clipping';
}

function formatBytes(bytes?: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatSeconds(seconds?: number): string {
  if (seconds === undefined || seconds === null) return '00:00';
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

export default function SmartSearchPage() {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [queryFile, setQueryFile] = useState<QueryFileState | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [searchPhaseIndex, setSearchPhaseIndex] = useState(0);

  useEffect(() => {
    if (!searching) {
      setSearchPhaseIndex(0);
      return;
    }
    const interval = setInterval(() => {
      setSearchPhaseIndex((prev) => (prev + 1) % SEARCH_PHASES.length);
    }, 1500);
    return () => clearInterval(interval);
  }, [searching]);

  // Discovery Trace (Lineage linking)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [discoveryTrace, setDiscoveryTrace] = useState<any | null>(null);

  // Active View Filter (Internet first by default)
  const [domainFilter, setDomainFilter] = useState<'all' | 'internet' | 'local'>('all');
  const [localCategoryFilter, setLocalCategoryFilter] = useState<'all' | 'document' | 'video' | 'audio' | 'image'>('all');
  const [internetCategoryFilter, setInternetCategoryFilter] = useState<'all' | 'web' | 'news' | 'paper' | 'video' | 'image'>('all');

  // Categorized Internet Results (Priority 1)
  const [internetData, setInternetData] = useState<{
    web: InternetCategorizedItem[];
    news: InternetCategorizedItem[];
    papers: InternetCategorizedItem[];
    videos: InternetCategorizedItem[];
    images: InternetCategorizedItem[];
    total: number;
  }>({ web: [], news: [], papers: [], videos: [], images: [], total: 0 });

  // Categorized Local Results (Priority 2)
  const [localData, setLocalData] = useState<{
    documents: LocalCategorizedItem[];
    images: LocalCategorizedItem[];
    videos: LocalCategorizedItem[];
    audio: LocalCategorizedItem[];
    total: number;
  }>({ documents: [], images: [], videos: [], audio: [], total: 0 });

  // Selections
  const [selectedLocalIds, setSelectedLocalIds] = useState<Set<string>>(new Set());
  const [selectedInternetIds, setSelectedInternetIds] = useState<Set<string>>(new Set());

  // Synthesis
  const [synthesizing, setSynthesizing] = useState(false);
  const [synthesisResult, setSynthesisResult] = useState<string | null>(null);
  const [copiedSynthesis, setCopiedSynthesis] = useState(false);
  const [startingChat, setStartingChat] = useState(false);

  // Metadata Modal & Playback Seek
  const [inspectSourceId, setInspectSourceId] = useState<string | null>(null);
  const [inspectTimestamp, setInspectTimestamp] = useState<number | undefined>(undefined);
  const [inspectInternetItem, setInspectInternetItem] = useState<InternetCategorizedItem | null>(null);

  // Relative Similarity Threshold (Default 5%)
  const [relativeThreshold, setRelativeThreshold] = useState<number>(5);
  const [thresholdInfo, setThresholdInfo] = useState<{
    topScore?: number;
    relativeThreshold?: number;
    minScore?: number;
    resultsBefore?: number;
    resultsAfter?: number;
  } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const synthesisRef = useRef<HTMLDivElement>(null);
  const { addContextItem, enableInternetSources, setEnableInternetSources } = useChatStore();

  const allInternetItems: InternetCategorizedItem[] = [
    ...internetData.web,
    ...internetData.news,
    ...internetData.papers,
    ...internetData.videos,
    ...internetData.images,
  ];

  const allLocalItems: LocalCategorizedItem[] = [
    ...localData.documents,
    ...localData.videos,
    ...localData.audio,
    ...localData.images,
  ];

  const handleFileSelect = (file: File) => {
    const mime = file.type.toLowerCase();
    const ext = file.name.split('.').pop()?.toLowerCase() || '';

    let type: QueryFileState['type'] = 'document';
    if (mime.startsWith('image/') || ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'].includes(ext)) {
      type = 'image';
    } else if (mime.startsWith('video/') || ['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(ext)) {
      type = 'video';
    } else if (mime.startsWith('audio/') || ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac'].includes(ext)) {
      type = 'audio';
    } else if (['pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx'].includes(ext)) {
      type = 'document';
    }

    if (type === 'image') {
      const reader = new FileReader();
      reader.onload = (e) => {
        setQueryFile({
          file,
          previewUrl: e.target?.result as string,
          name: file.name,
          type: 'image',
        });
        toast.success(`Image "${file.name}" loaded for visual & face search`);
      };
      reader.readAsDataURL(file);
    } else {
      setQueryFile({
        file,
        name: file.name,
        type,
      });
      toast.success(`${type.toUpperCase()} file "${file.name}" loaded for smart search`);
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleSearch = async (searchQuery?: string, overrideThreshold?: number) => {
    const q = (searchQuery !== undefined ? searchQuery : query).trim();
    const hasFile = Boolean(queryFile);
    const effThresh = overrideThreshold !== undefined ? overrideThreshold : relativeThreshold;

    if (!q && !hasFile) return;
    if (searching) return;

    if (searchQuery !== undefined) setQuery(searchQuery);

    setSearching(true);
    setHasSearched(true);
    setSynthesisResult(null);

    try {
      let res: Response;

      if (queryFile?.file) {
        const formData = new FormData();
        formData.append('file', queryFile.file);
        if (q) formData.append('query', q);
        formData.append('enableInternet', enableInternetSources ? 'true' : 'false');
        formData.append('relativeThreshold', String(effThresh / 100));

        res = await fetch('/api/search/smart', {
          method: 'POST',
          body: formData,
        });
      } else {
        const payload: Record<string, unknown> = {
          enableInternet: enableInternetSources,
          relativeThreshold: effThresh / 100,
        };
        if (q) payload.query = q;
        if (queryFile?.previewUrl) payload.imageBase64 = queryFile.previewUrl;

        res = await fetch('/api/search/smart', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }

      if (!res.ok) {
        toast.error('Search failed. Please try again.');
        return;
      }

      const data = await res.json();
      const internet = data.internet || { web: [], news: [], papers: [], videos: [], images: [], total: 0 };
      const local = data.local || { documents: [], images: [], videos: [], audio: [], total: 0 };

      setInternetData(internet);
      setLocalData(local);
      setDiscoveryTrace(data.discoveryTrace || null);
      setThresholdInfo(data.thresholdInfo || null);

      if (!enableInternetSources) {
        setDomainFilter('local');
      } else {
        setDomainFilter('all');
      }

      // Pre-select top relevant items
      const preSelectedInternet = new Set<string>();
      if (internet.web.length > 0) preSelectedInternet.add(internet.web[0].id);
      if (internet.news.length > 0) preSelectedInternet.add(internet.news[0].id);
      if (internet.papers.length > 0) preSelectedInternet.add(internet.papers[0].id);
      setSelectedInternetIds(preSelectedInternet);

      const preSelectedLocal = new Set<string>();
      if (local.documents.length > 0) preSelectedLocal.add(local.documents[0].id);
      if (local.videos.length > 0) preSelectedLocal.add(local.videos[0].id);
      setSelectedLocalIds(preSelectedLocal);

      if (enableInternetSources) {
        toast.success(`Discovered ${internet.total} internet intelligence sources and ${local.total} local matches`);
      } else {
        toast.success(`Discovered ${local.total} local repository matches (Internet sources OFF)`);
      }
    } catch {
      toast.error('Search error. Please check connection.');
    } finally {
      setSearching(false);
    }
  };

  const handleFindSimilar = async (sourceId: string, sourceTitle?: string) => {
    if (!sourceId || searching) return;
    setSearching(true);
    setHasSearched(true);
    setSynthesisResult(null);
    const displayTitle = sourceTitle || 'Selected Source';
    setQuery(`Similar to: "${displayTitle}"`);
    setInspectSourceId(null);
    setInspectInternetItem(null);

    try {
      const res = await fetch('/api/search/similar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sourceId,
          relativeThreshold: relativeThreshold / 100,
        }),
      });

      if (!res.ok) {
        toast.error('Failed to find similar sources.');
        return;
      }

      const data = await res.json();
      const local = data.local || { documents: [], images: [], videos: [], audio: [], total: 0 };
      setLocalData(local);
      setInternetData({ web: [], news: [], papers: [], videos: [], images: [], total: 0 });
      setDiscoveryTrace(data.discoveryTrace || null);
      setThresholdInfo(data.thresholdInfo || null);
      setDomainFilter('local');

      // Pre-select top similar items
      const preSelectedLocal = new Set<string>();
      if (local.documents.length > 0) preSelectedLocal.add(local.documents[0].id);
      if (local.videos.length > 0) preSelectedLocal.add(local.videos[0].id);
      setSelectedLocalIds(preSelectedLocal);

      toast.success(`Discovered ${local.total} similar source(s) across existing indexes`);
    } catch {
      toast.error('Error finding similar sources. Please check connection.');
    } finally {
      setSearching(false);
    }
  };

  const openSourceWithSeek = (sourceId: string, timestamp?: number) => {
    setInspectSourceId(sourceId);
    setInspectTimestamp(timestamp);
    setInspectInternetItem(null);
  };

  const toggleLocalItem = (id: string) => {
    setSelectedLocalIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleInternetItem = (id: string) => {
    setSelectedInternetIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllLocal = () => {
    if (selectedLocalIds.size === allLocalItems.length) {
      setSelectedLocalIds(new Set());
    } else {
      setSelectedLocalIds(new Set(allLocalItems.map((d) => d.id)));
    }
  };

  const selectAllInternet = () => {
    if (selectedInternetIds.size === allInternetItems.length) {
      setSelectedInternetIds(new Set());
    } else {
      setSelectedInternetIds(new Set(allInternetItems.map((s) => s.id)));
    }
  };

  const selectAllGlobal = () => {
    const allLocalSelected = selectedLocalIds.size === allLocalItems.length;
    const allInternetSelected = selectedInternetIds.size === allInternetItems.length;
    if (allLocalSelected && allInternetSelected) {
      setSelectedLocalIds(new Set());
      setSelectedInternetIds(new Set());
    } else {
      setSelectedLocalIds(new Set(allLocalItems.map((d) => d.id)));
      setSelectedInternetIds(new Set(allInternetItems.map((s) => s.id)));
    }
  };

  const totalSelected = selectedLocalIds.size + selectedInternetIds.size;

  const handleSynthesize = async () => {
    if (totalSelected === 0 || synthesizing) return;

    setSynthesizing(true);
    setSynthesisResult(null);

    const chosenInternet = allInternetItems.filter((s) => selectedInternetIds.has(s.id));
    const chosenLocal = allLocalItems.filter((d) => selectedLocalIds.has(d.id));

    try {
      const res = await fetch('/api/search/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query || (queryFile?.name ? `Search for: ${queryFile.name}` : 'Multimodal Analysis'),
          selectedLocalDocs: chosenLocal,
          selectedInternetSources: chosenInternet,
        }),
      });

      if (!res.ok) {
        toast.error('AI synthesis failed.');
        return;
      }

      const data = await res.json();
      setSynthesisResult(data.summary);
      toast.success('Combined AI Summary generated!');

      setTimeout(() => {
        synthesisRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 100);
    } catch {
      toast.error('Synthesis failed. Please try again.');
    } finally {
      setSynthesizing(false);
    }
  };

  const handleCopySynthesis = () => {
    if (!synthesisResult) return;
    const clean = synthesisResult.replace(/<think>[\s\S]*?<\/think>/gi, '').trim() || synthesisResult;
    navigator.clipboard.writeText(clean);
    setCopiedSynthesis(true);
    toast.success('Summary copied to clipboard');
    setTimeout(() => setCopiedSynthesis(false), 2000);
  };

  // ═══════════════════════════════════════════════════════════════
  // SEND TO AI RESEARCH CHAT (DEDICATED SESSION WORKFLOW)
  // ═══════════════════════════════════════════════════════════════
  const handleSendToAIChat = async () => {
    const chosenLocal = allLocalItems.filter((d) => selectedLocalIds.has(d.id));
    const chosenInternet = allInternetItems.filter((s) => selectedInternetIds.has(s.id));
    const allChosen = [...chosenInternet, ...chosenLocal];

    if (allChosen.length === 0) {
      toast.error('Please select at least one source to send to AI Chat');
      return;
    }

    setStartingChat(true);

    const contextItems: ContextItem[] = [];

    for (const web of chosenInternet) {
      contextItems.push({
        id: web.id,
        type: web.category === 'video' ? 'video' : web.category === 'image' ? 'image' : 'web',
        title: web.title,
        snippet: web.snippet,
        relevanceScore: web.relevanceScore,
        metadata: { url: web.url, domain: web.domain, category: web.category },
      });
    }

    for (const doc of chosenLocal) {
      contextItems.push({
        id: doc.id,
        type: doc.category === 'video' ? 'video' : doc.category === 'image' ? 'image' : 'document',
        title: doc.title,
        snippet: doc.snippet,
        relevanceScore: doc.relevanceScore,
        metadata: {
          sourceId: doc.sourceId,
          fileType: doc.fileType,
          pageNum: doc.pageNum,
          timestamp: doc.startTime,
          duration: doc.duration,
        },
      });
    }

    const chatTitle = query ? `Research: ${query.slice(0, 45)}` : 'Research Session';

    try {
      const res = await fetch('/api/chats', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: chatTitle, searchMode: 'both' }),
      });

      if (!res.ok) {
        toast.error('Failed to create new chat session');
        return;
      }

      const data = await res.json();
      const newChatId = data.chat.id;

      // Update Chat store
      const store = useChatStore.getState();
      store.setActiveChatId(newChatId);
      store.setActiveContext(contextItems);
      store.setChats([data.chat, ...store.chats]);

      // Initial prompt to kickoff research discussion
      const initialPrompt = `Please synthesize the ${contextItems.length} retrieved research sources and provide an overview of findings for: "${query || 'the selected intelligence sources'}"`;

      store.addMessage({
        id: `user-init-${Date.now()}`,
        role: 'user',
        content: initialPrompt,
        createdAt: new Date().toISOString(),
      });

      // Send initial request to start the conversation
      fetch(`/api/chats/${newChatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: initialPrompt, contextItems }),
      }).then(async (mRes) => {
        if (mRes.ok) {
          const mData = await mRes.json();
          useChatStore.getState().setMessages([
            { id: mData.userMessage.id, role: 'user', content: mData.userMessage.content, createdAt: new Date().toISOString() },
            { id: mData.assistantMessage.id, role: 'assistant', content: mData.assistantMessage.content, createdAt: new Date().toISOString() },
          ]);
        }
      });

      toast.success(`Opening dedicated AI Research Workspace with ${contextItems.length} sources`);
      router.push('/');
    } catch {
      toast.error('Failed to start AI chat session');
    } finally {
      setStartingChat(false);
    }
  };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      {/* Sidebar */}
      <Sidebar />

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-y-auto">
        <div className="max-w-6xl w-full mx-auto px-4 sm:px-8 py-8 space-y-8">
          {/* Header Banner */}
          <div className="text-center space-y-2 max-w-2xl mx-auto">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold"
              style={{ background: 'rgba(6,182,212,0.12)', color: '#06b6d4', border: '1px solid rgba(6,182,212,0.25)' }}>
              <Sparkles className="w-3.5 h-3.5" />
              <span>Multimodal Smart Finder & Face-Based Video Search</span>
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight" style={{ color: 'var(--text-primary)' }}>
              Smart Finder Multimodal Search
            </h1>
            <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
              Upload any reference material—image, face portrait, video, audio, PDF, or clipping—and automatically discover local context with optional enriched internet intelligence.
            </p>
          </div>

          {/* Multimodal Search Bar & Settings */}
          <div className="max-w-3xl mx-auto space-y-3">
            {/* Search Configuration: Internet Sources Toggle + Relative Similarity Threshold */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Option 1: Live Internet Toggle */}
              <div className="flex items-center justify-between px-4 py-3 rounded-2xl shadow-sm transition-all"
                style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className={`w-7 h-7 rounded-xl flex items-center justify-center flex-shrink-0 transition-colors ${
                    enableInternetSources ? 'bg-emerald-500/20 text-emerald-400' : 'bg-zinc-800 text-zinc-400'
                  }`}>
                    <Globe className="w-4 h-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold truncate" style={{ color: 'var(--text-primary)' }}>Live Internet</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                        enableInternetSources ? 'bg-emerald-500/20 text-emerald-400' : 'bg-zinc-800 text-zinc-400'
                      }`}>
                        {enableInternetSources ? 'ON' : 'OFF'}
                      </span>
                    </div>
                    <p className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }}>
                      {enableInternetSources ? 'Web, papers, news included' : 'Local repository only'}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  disabled={searching}
                  onClick={() => {
                    const next = !enableInternetSources;
                    setEnableInternetSources(next);
                    toast.info(next ? 'Live internet sources enabled' : 'Switched to local repository only');
                  }}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors flex-shrink-0 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
                    enableInternetSources ? 'bg-emerald-500' : 'bg-zinc-700'
                  }`}
                  title={enableInternetSources ? 'Disable live internet sources' : 'Enable live internet sources'}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-md transition-transform ${
                    enableInternetSources ? 'translate-x-6' : 'translate-x-1'
                  }`} />
                </button>
              </div>

              {/* Option 2: Relative Similarity Threshold */}
              <div className="flex flex-col justify-between px-4 py-3 rounded-2xl shadow-sm gap-2 transition-all"
                style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <Sparkles className="w-4 h-4 text-cyan-400 flex-shrink-0" />
                    <span className="text-xs font-bold truncate" style={{ color: 'var(--text-primary)' }}>
                      Relative Threshold
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    {thresholdInfo && thresholdInfo.topScore !== undefined && thresholdInfo.minScore !== undefined && (
                      <span className="text-[10px] font-mono text-cyan-400 font-bold">
                        Top {Math.round(thresholdInfo.topScore * 100)}% → Min {Math.round(thresholdInfo.minScore * 100)}%
                      </span>
                    )}
                    <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                      {relativeThreshold === 100 ? 'ALL' : `${relativeThreshold}%`}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-1 flex-wrap">
                  {[
                    { label: '1%', val: 1 },
                    { label: '2%', val: 2 },
                    { label: '5%', val: 5, isDefault: true },
                    { label: '10%', val: 10 },
                    { label: '15%', val: 15 },
                    { label: '25%', val: 25 },
                    { label: 'All', val: 100 },
                  ].map((preset) => {
                    const isActive = relativeThreshold === preset.val;
                    return (
                      <button
                        key={preset.val}
                        type="button"
                        disabled={searching}
                        onClick={() => {
                          setRelativeThreshold(preset.val);
                          toast.info(`Relative Similarity Threshold set to ${preset.val === 100 ? 'All (No Filter)' : `${preset.val}%`}`);
                          if (hasSearched) {
                            handleSearch(query, preset.val);
                          }
                        }}
                        className={`px-2 py-0.5 rounded-lg text-[10px] font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
                          isActive
                            ? 'bg-cyan-500 text-white shadow-sm'
                            : 'bg-zinc-800/80 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700'
                        }`}
                        title={preset.isDefault ? 'Default threshold: 5%' : undefined}
                      >
                        {preset.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              className={`relative p-2 rounded-2xl flex flex-col gap-2 shadow-2xl transition-all ${
                dragOver ? 'border-cyan-500 ring-2 ring-cyan-500/30' : ''
              }`}
              style={{
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border)',
                boxShadow: '0 12px 40px rgba(0,0,0,0.4), 0 0 0 1px rgba(6,182,212,0.15)',
              }}
            >
              {/* Query File Preview Pill if loaded */}
              {queryFile && (
                <div className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl bg-cyan-500/10 border border-cyan-500/30 w-fit max-w-full">
                  {queryFile.previewUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={queryFile.previewUrl} alt="Query Preview" className="w-6 h-6 rounded-md object-cover border border-cyan-500/40" />
                  ) : queryFile.type === 'video' ? (
                    <Film className="w-4 h-4 text-cyan-400" />
                  ) : queryFile.type === 'audio' ? (
                    <FileAudio className="w-4 h-4 text-cyan-400" />
                  ) : (
                    <FileText className="w-4 h-4 text-cyan-400" />
                  )}
                  <span className="text-xs font-semibold text-cyan-400 truncate max-w-[240px]">
                    {queryFile.name}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.2 rounded bg-cyan-500/20 text-cyan-300 font-mono uppercase">
                    {queryFile.type}
                  </span>
                  <button
                    type="button"
                    disabled={searching}
                    onClick={() => setQueryFile(null)}
                    className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}

              <form
                onSubmit={(e: FormEvent) => {
                  e.preventDefault();
                  handleSearch();
                }}
                className="flex items-center gap-2 w-full"
              >
                <div className="pl-3" style={{ color: '#06b6d4' }}>
                  <Search className="w-5 h-5" />
                </div>

                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={
                    queryFile
                      ? `Searching by ${queryFile.type}: "${queryFile.name}" (Optional extra keywords)...`
                      : enableInternetSources
                      ? 'Upload reference material or search local repository + live internet...'
                      : 'Upload reference material or search local repository (Internet disabled)...'
                  }
                  disabled={searching}
                  className="flex-1 bg-transparent px-2 py-2 text-sm outline-none placeholder:text-muted-foreground/50"
                  style={{ color: 'var(--text-primary)' }}
                />

                {/* Hidden File Input for All Reference Material */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*,video/*,audio/*,.pdf,.doc,.docx,.txt,.md,.csv,.xlsx"
                  className="hidden"
                  onChange={(e: ChangeEvent<HTMLInputElement>) => {
                    if (e.target.files && e.target.files[0]) {
                      handleFileSelect(e.target.files[0]);
                    }
                  }}
                />

                {/* Universal Upload Button */}
                <button
                  type="button"
                  disabled={searching}
                  onClick={() => fileInputRef.current?.click()}
                  className={`p-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                    queryFile
                      ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                      : 'text-zinc-400 hover:text-cyan-400 hover:bg-[var(--bg-hover)]'
                  }`}
                  title="Upload Image, Face, Video, Audio, or PDF document"
                >
                  <UploadCloud className="w-4 h-4" />
                  <span className="hidden sm:inline text-[11px]">{queryFile ? 'File Attached' : 'Upload Material'}</span>
                </button>

                {query && (
                  <button
                    type="button"
                    disabled={searching}
                    onClick={() => setQuery('')}
                    className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-[var(--bg-hover)] disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}

                <button
                  type="submit"
                  disabled={(!query.trim() && !queryFile) || searching}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-sm text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-md"
                  style={{
                    background: 'linear-gradient(135deg, #06b6d4 0%, #6366f1 100%)',
                    boxShadow: '0 4px 14px rgba(6,182,212,0.4)',
                  }}
                >
                  {searching ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Discovering...</span>
                    </>
                  ) : (
                    <>
                      <span>Discover</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </form>
            </div>

            {/* Page-level loading animation & progress bar when searching */}
            {searching && (
              <motion.div
                initial={{ opacity: 0, y: -10, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -10, scale: 0.98 }}
                className="p-5 rounded-3xl relative overflow-hidden shadow-xl"
                style={{
                  background: 'var(--bg-elevated)',
                  border: '1px solid rgba(6,182,212,0.3)',
                  boxShadow: '0 8px 32px rgba(6,182,212,0.12)',
                }}
              >
                {/* Animated top progress bar */}
                <div className="absolute top-0 left-0 right-0 h-1 bg-zinc-800 overflow-hidden">
                  <motion.div
                    className="h-full w-1/3"
                    style={{ background: 'linear-gradient(90deg, #06b6d4, #6366f1, #06b6d4)' }}
                    animate={{
                      x: ['-100%', '350%'],
                    }}
                    transition={{
                      repeat: Infinity,
                      duration: 1.6,
                      ease: 'easeInOut',
                    }}
                  />
                </div>

                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-1">
                  <div className="flex items-center gap-3">
                    <div
                      className="w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0 relative"
                      style={{ background: 'rgba(6,182,212,0.15)', border: '1px solid rgba(6,182,212,0.3)' }}
                    >
                      <Loader2 className="w-5 h-5 text-cyan-400 animate-spin" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
                          {SEARCH_PHASES[searchPhaseIndex]}
                        </span>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 font-semibold animate-pulse">
                          LIVE DISCOVERY
                        </span>
                      </div>
                      <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
                        Evaluating multimodal vectors, lexical tokens, and cross-source relevance...
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 self-start sm:self-center">
                    <div className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-zinc-800/80 border border-zinc-700/60 text-xs">
                      <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
                      <span className="text-[11px] text-zinc-300 font-medium">Discovering files...</span>
                    </div>
                  </div>
                </div>
              </motion.div>
            )}

            {!hasSearched && !searching && (
              <div className="flex flex-wrap items-center justify-center gap-2 mt-4">
                <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Try:</span>
                {SUGGESTED_QUERIES.map((sq) => (
                  <button
                    key={sq}
                    disabled={searching}
                    onClick={() => handleSearch(sq)}
                    className="text-xs px-3 py-1 rounded-full transition-all hover:scale-105 disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{
                      background: 'var(--bg-elevated)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {sq}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Results Section */}
          {hasSearched && (
            <div className="space-y-6">
              {/* DISCOVERY TRACE FLOWCHART COMPONENT */}
              {discoveryTrace && (
                <DiscoveryTrace
                  trace={discoveryTrace}
                  onOpenVideoTimestamp={(srcId, ts) => openSourceWithSeek(srcId, ts)}
                />
              )}

              {/* Primary View Filters & Batch Select Bar */}
              <div
                className="p-4 rounded-3xl flex flex-wrap items-center justify-between gap-4"
                style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
              >
                {/* Domain Selector (Internet first, Local second) */}
                <div className="flex items-center gap-1.5 p-1 rounded-2xl" style={{ background: 'var(--bg-base)' }}>
                  {[
                    { id: 'all', label: 'All Sources', count: internetData.total + localData.total, icon: Layers },
                    { id: 'internet', label: 'Internet Sources', count: internetData.total, icon: Globe },
                    { id: 'local', label: 'Local Knowledge', count: localData.total, icon: Database },
                  ].map((tab) => {
                    const isActive = domainFilter === tab.id;
                    const Icon = tab.icon;
                    return (
                      <button
                        key={tab.id}
                        onClick={() => setDomainFilter(tab.id as typeof domainFilter)}
                        className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all"
                        style={{
                          background: isActive ? (tab.id === 'internet' ? '#06b6d4' : tab.id === 'local' ? 'var(--accent)' : 'linear-gradient(135deg, #06b6d4, #6366f1)') : 'transparent',
                          color: isActive ? '#fff' : 'var(--text-secondary)',
                        }}
                      >
                        <Icon className="w-3.5 h-3.5" />
                        <span>{tab.label}</span>
                        {searching ? (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.2 rounded-full text-[10px] bg-cyan-500/20 text-cyan-300 font-mono">
                            <Loader2 className="w-2.5 h-2.5 animate-spin" />
                            <span>...</span>
                          </span>
                        ) : (
                          <span
                            className="px-1.5 py-0.2 rounded-full text-[10px]"
                            style={{
                              background: isActive ? 'rgba(255,255,255,0.25)' : 'var(--bg-active)',
                              color: isActive ? '#fff' : 'var(--text-muted)',
                            }}
                          >
                            {tab.count}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>

                {/* Batch Action Buttons */}
                <div className="flex items-center gap-2 text-xs">
                  <button
                    onClick={selectAllGlobal}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-medium transition-colors hover:bg-[var(--bg-hover)]"
                    style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                  >
                    <CheckSquare className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Toggle All ({totalSelected})</span>
                  </button>
                  <button
                    onClick={selectAllInternet}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-medium transition-colors hover:bg-[var(--bg-hover)]"
                    style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                  >
                    <Globe className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Internet ({selectedInternetIds.size})</span>
                  </button>
                  <button
                    onClick={selectAllLocal}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-medium transition-colors hover:bg-[var(--bg-hover)]"
                    style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                  >
                    <Database className="w-3.5 h-3.5 text-indigo-400" />
                    <span>Local ({selectedLocalIds.size})</span>
                  </button>
                </div>
              </div>

              {/* Categorized Sources Layout: INTERNET FIRST, THEN LOCAL */}
              <div className="space-y-8">
                {/* ═══════════════════════════════════════════════════════════════
                    1. INTERNET SOURCES (RETRIEVED & DISPLAYED FIRST)
                   ═══════════════════════════════════════════════════════════════ */}
                {(domainFilter === 'all' || domainFilter === 'internet') && (
                  <div className="space-y-6">
                    <div className="flex items-center justify-between border-b border-[var(--border)] pb-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-xl flex items-center justify-center"
                          style={{ background: 'rgba(6,182,212,0.15)', color: '#06b6d4' }}>
                          <Globe className="w-4 h-4" />
                        </div>
                        <div>
                          <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
                            1. Internet Intelligence Sources ({searching ? 'Searching...' : internetData.total})
                          </h2>
                          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                            Live Web References, News, Research Papers, Videos & Images matching enhanced query &quot;{discoveryTrace?.enhancedQuery || query}&quot;
                          </p>
                        </div>
                      </div>

                      {/* Sub-category Filter Buttons */}
                      <div className="flex items-center gap-1">
                        {[
                          { id: 'all', label: 'All', count: internetData.total },
                          { id: 'web', label: 'Web', count: internetData.web.length, icon: Globe },
                          { id: 'news', label: 'News', count: internetData.news.length, icon: Newspaper },
                          { id: 'paper', label: 'Papers', count: internetData.papers.length, icon: BookOpen },
                          { id: 'video', label: 'Videos', count: internetData.videos.length, icon: VideoIcon },
                          { id: 'image', label: 'Images', count: internetData.images.length, icon: ImageIcon },
                        ].map((sub) => {
                          const isSubActive = internetCategoryFilter === sub.id;
                          return (
                            <button
                              key={sub.id}
                              onClick={() => setInternetCategoryFilter(sub.id as typeof internetCategoryFilter)}
                              className="px-2.5 py-1 rounded-xl text-xs font-semibold transition-all"
                              style={{
                                background: isSubActive ? 'rgba(6,182,212,0.15)' : 'transparent',
                                color: isSubActive ? '#06b6d4' : 'var(--text-muted)',
                                border: isSubActive ? '1px solid rgba(6,182,212,0.3)' : '1px solid transparent',
                              }}
                            >
                              {sub.label} ({searching ? '...' : sub.count})
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {searching ? (
                      <div className="space-y-4">
                        <div className="flex items-center gap-2 text-xs font-bold text-cyan-400 uppercase tracking-wider">
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          <span>Discovering and fetching live web intelligence...</span>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {[1, 2, 3, 4].map((i) => (
                            <div key={i} className="p-4 rounded-2xl border animate-pulse space-y-2.5"
                              style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}>
                              <div className="flex items-center justify-between">
                                <div className="h-3.5 w-24 bg-zinc-800 rounded" />
                                <div className="h-3.5 w-8 bg-zinc-800 rounded" />
                              </div>
                              <div className="h-4 w-3/4 bg-zinc-800 rounded" />
                              <div className="h-3 w-full bg-zinc-800/70 rounded" />
                              <div className="h-3 w-5/6 bg-zinc-800/50 rounded" />
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : internetData.total === 0 ? (
                      <div className="p-8 rounded-3xl text-center" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                        <Globe className="w-8 h-8 mx-auto mb-2 opacity-30" style={{ color: 'var(--text-muted)' }} />
                        <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>No internet sources retrieved</p>
                      </div>
                    ) : (
                      <div className="space-y-6">
                        {/* 1.1 Web References */}
                        {(internetCategoryFilter === 'all' || internetCategoryFilter === 'web') && internetData.web.length > 0 && (
                          <div className="space-y-3">
                            <div className="text-xs font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-1.5">
                              <Globe className="w-3.5 h-3.5" /> Web References ({internetData.web.length})
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                              {internetData.web.map((src) => {
                                const isSelected = selectedInternetIds.has(src.id);
                                return (
                                  <motion.div
                                    key={src.id}
                                    whileHover={{ scale: 1.005 }}
                                    onClick={() => setInspectInternetItem(src)}
                                    className="p-4 rounded-2xl transition-all cursor-pointer relative group flex gap-3"
                                    style={{
                                      background: 'var(--bg-elevated)',
                                      border: isSelected ? '1.5px solid #06b6d4' : '1px solid var(--border)',
                                      boxShadow: isSelected ? '0 4px 20px rgba(6,182,212,0.15)' : 'none',
                                    }}
                                  >
                                    <div className="mt-0.5 flex-shrink-0" onClick={(e) => { e.stopPropagation(); toggleInternetItem(src.id); }}>
                                      {isSelected ? (
                                        <CheckCircle2 className="w-5 h-5 text-cyan-400" />
                                      ) : (
                                        <Square className="w-5 h-5 text-zinc-500 hover:text-zinc-300" />
                                      )}
                                    </div>
                                    <div className="flex-1 min-w-0 space-y-1.5">
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="text-xs font-medium text-cyan-400 truncate">{src.domain}</span>
                                        <a href={src.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
                                          className="p-1.5 rounded-xl hover:bg-[var(--bg-active)] text-zinc-400 hover:text-cyan-400 transition-colors">
                                          <ExternalLink className="w-3.5 h-3.5" />
                                        </a>
                                      </div>
                                      <h3 className="text-xs font-bold line-clamp-2 group-hover:text-cyan-400 transition-colors"
                                        style={{ color: 'var(--text-primary)' }}>
                                        {src.title}
                                      </h3>
                                      <p className="text-xs leading-relaxed line-clamp-3 select-text" style={{ color: 'var(--text-secondary)' }}>
                                        {src.snippet}
                                      </p>
                                    </div>
                                  </motion.div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* 1.2 News */}
                        {(internetCategoryFilter === 'all' || internetCategoryFilter === 'news') && internetData.news.length > 0 && (
                          <div className="space-y-3">
                            <div className="text-xs font-bold uppercase tracking-wider text-rose-400 flex items-center gap-1.5">
                              <Newspaper className="w-3.5 h-3.5" /> News Articles ({internetData.news.length})
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                              {internetData.news.map((src) => {
                                const isSelected = selectedInternetIds.has(src.id);
                                return (
                                  <motion.div
                                    key={src.id}
                                    whileHover={{ scale: 1.005 }}
                                    onClick={() => setInspectInternetItem(src)}
                                    className="p-4 rounded-2xl transition-all cursor-pointer relative group flex gap-3"
                                    style={{
                                      background: 'var(--bg-elevated)',
                                      border: isSelected ? '1.5px solid #f43f5e' : '1px solid var(--border)',
                                    }}
                                  >
                                    <div className="mt-0.5 flex-shrink-0" onClick={(e) => { e.stopPropagation(); toggleInternetItem(src.id); }}>
                                      {isSelected ? (
                                        <CheckCircle2 className="w-5 h-5 text-rose-400" />
                                      ) : (
                                        <Square className="w-5 h-5 text-zinc-500 hover:text-zinc-300" />
                                      )}
                                    </div>
                                    <div className="flex-1 min-w-0 space-y-1.5">
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="text-xs font-medium text-rose-400 truncate">{src.domain}</span>
                                        <a href={src.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
                                          className="p-1.5 rounded-xl hover:bg-[var(--bg-active)] text-zinc-400 hover:text-rose-400 transition-colors">
                                          <ExternalLink className="w-3.5 h-3.5" />
                                        </a>
                                      </div>
                                      <h3 className="text-xs font-bold line-clamp-2" style={{ color: 'var(--text-primary)' }}>
                                        {src.title}
                                      </h3>
                                      <p className="text-xs leading-relaxed line-clamp-3 select-text" style={{ color: 'var(--text-secondary)' }}>
                                        {src.snippet}
                                      </p>
                                    </div>
                                  </motion.div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* 1.3 Research Papers */}
                        {(internetCategoryFilter === 'all' || internetCategoryFilter === 'paper') && internetData.papers.length > 0 && (
                          <div className="space-y-3">
                            <div className="text-xs font-bold uppercase tracking-wider text-purple-400 flex items-center gap-1.5">
                              <BookOpen className="w-3.5 h-3.5" /> Research Papers ({internetData.papers.length})
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                              {internetData.papers.map((src) => {
                                const isSelected = selectedInternetIds.has(src.id);
                                return (
                                  <motion.div
                                    key={src.id}
                                    whileHover={{ scale: 1.005 }}
                                    onClick={() => setInspectInternetItem(src)}
                                    className="p-4 rounded-2xl transition-all cursor-pointer relative group flex gap-3"
                                    style={{
                                      background: 'var(--bg-elevated)',
                                      border: isSelected ? '1.5px solid #a855f7' : '1px solid var(--border)',
                                    }}
                                  >
                                    <div className="mt-0.5 flex-shrink-0" onClick={(e) => { e.stopPropagation(); toggleInternetItem(src.id); }}>
                                      {isSelected ? (
                                        <CheckCircle2 className="w-5 h-5 text-purple-400" />
                                      ) : (
                                        <Square className="w-5 h-5 text-zinc-500 hover:text-zinc-300" />
                                      )}
                                    </div>
                                    <div className="flex-1 min-w-0 space-y-1.5">
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="text-xs font-medium text-purple-400 truncate">Academic Paper</span>
                                        <a href={src.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
                                          className="p-1.5 rounded-xl hover:bg-[var(--bg-active)] text-zinc-400 hover:text-purple-400 transition-colors">
                                          <ExternalLink className="w-3.5 h-3.5" />
                                        </a>
                                      </div>
                                      <h3 className="text-xs font-bold line-clamp-2" style={{ color: 'var(--text-primary)' }}>
                                        {src.title}
                                      </h3>
                                      <p className="text-xs leading-relaxed line-clamp-3 select-text" style={{ color: 'var(--text-secondary)' }}>
                                        {src.snippet}
                                      </p>
                                    </div>
                                  </motion.div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* 1.4 Videos */}
                        {(internetCategoryFilter === 'all' || internetCategoryFilter === 'video') && internetData.videos.length > 0 && (
                          <div className="space-y-3">
                            <div className="text-xs font-bold uppercase tracking-wider text-red-400 flex items-center gap-1.5">
                              <VideoIcon className="w-3.5 h-3.5" /> Videos ({internetData.videos.length})
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                              {internetData.videos.map((src) => {
                                const isSelected = selectedInternetIds.has(src.id);
                                return (
                                  <motion.div
                                    key={src.id}
                                    whileHover={{ scale: 1.005 }}
                                    onClick={() => setInspectInternetItem(src)}
                                    className="p-4 rounded-2xl transition-all cursor-pointer relative group flex gap-3"
                                    style={{
                                      background: 'var(--bg-elevated)',
                                      border: isSelected ? '1.5px solid #ef4444' : '1px solid var(--border)',
                                    }}
                                  >
                                    <div className="mt-0.5 flex-shrink-0" onClick={(e) => { e.stopPropagation(); toggleInternetItem(src.id); }}>
                                      {isSelected ? (
                                        <CheckCircle2 className="w-5 h-5 text-red-400" />
                                      ) : (
                                        <Square className="w-5 h-5 text-zinc-500 hover:text-zinc-300" />
                                      )}
                                    </div>
                                    <div className="flex-1 min-w-0 space-y-1.5">
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="text-xs font-medium text-red-400 truncate">YouTube Video</span>
                                        <button
                                          type="button"
                                          onClick={(e) => { e.stopPropagation(); setInspectInternetItem(src); }}
                                          className="flex items-center gap-1 px-2 py-0.5 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 text-[11px] font-semibold transition-colors"
                                        >
                                          <Play className="w-3 h-3" />
                                          <span>Play</span>
                                        </button>
                                      </div>
                                      <h3 className="text-xs font-bold line-clamp-2" style={{ color: 'var(--text-primary)' }}>
                                        {src.title}
                                      </h3>
                                      <p className="text-xs leading-relaxed line-clamp-2 select-text" style={{ color: 'var(--text-secondary)' }}>
                                        {src.snippet}
                                      </p>
                                    </div>
                                  </motion.div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* 1.5 Images */}
                        {(internetCategoryFilter === 'all' || internetCategoryFilter === 'image') && internetData.images.length > 0 && (
                          <div className="space-y-3">
                            <div className="text-xs font-bold uppercase tracking-wider text-emerald-400 flex items-center gap-1.5">
                              <ImageIcon className="w-3.5 h-3.5" /> Web Images ({internetData.images.length})
                            </div>
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                              {internetData.images.map((src) => {
                                const isSelected = selectedInternetIds.has(src.id);
                                return (
                                  <motion.div
                                    key={src.id}
                                    whileHover={{ scale: 1.02 }}
                                    onClick={() => setInspectInternetItem(src)}
                                    className="p-3 rounded-2xl transition-all cursor-pointer relative group flex flex-col space-y-2"
                                    style={{
                                      background: 'var(--bg-elevated)',
                                      border: isSelected ? '1.5px solid #10b981' : '1px solid var(--border)',
                                    }}
                                  >
                                    <div className="relative aspect-video rounded-xl overflow-hidden bg-black/40">
                                      {src.thumbnail ? (
                                        // eslint-disable-next-line @next/next/no-img-element
                                        <img src={src.thumbnail} alt={src.title} className="w-full h-full object-cover" />
                                      ) : (
                                        <div className="w-full h-full flex items-center justify-center text-zinc-600">
                                          <ImageIcon className="w-6 h-6" />
                                        </div>
                                      )}
                                      <div className="absolute top-1.5 left-1.5" onClick={(e) => { e.stopPropagation(); toggleInternetItem(src.id); }}>
                                        {isSelected ? (
                                          <CheckCircle2 className="w-4 h-4 text-emerald-400 bg-black/60 rounded-full" />
                                        ) : (
                                          <Square className="w-4 h-4 text-white/80 bg-black/40 rounded-sm" />
                                        )}
                                      </div>
                                    </div>
                                    <div className="min-w-0">
                                      <p className="text-[11px] font-semibold truncate" style={{ color: 'var(--text-primary)' }}>{src.title}</p>
                                      <p className="text-[10px] text-zinc-400 truncate">{src.domain}</p>
                                    </div>
                                  </motion.div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* ═══════════════════════════════════════════════════════════════
                    2. LOCAL KNOWLEDGE SOURCES (STRICT & PRECISE)
                   ═══════════════════════════════════════════════════════════════ */}
                {(domainFilter === 'all' || domainFilter === 'local') && (
                  <div className="space-y-6">
                    <div className="flex items-center justify-between border-b border-[var(--border)] pb-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-xl flex items-center justify-center"
                          style={{ background: 'rgba(99,102,241,0.15)', color: 'var(--accent)' }}>
                          <Database className="w-4 h-4" />
                        </div>
                        <div>
                          <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
                            2. Matching Local Knowledge Documents & Media ({searching ? 'Discovering...' : localData.total})
                          </h2>
                          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                            Exact documents, PDFs, face-matched video keyframes, and transcripts
                          </p>
                        </div>
                      </div>

                      {/* Sub-category Filter Buttons */}
                      <div className="flex items-center gap-1">
                        {[
                          { id: 'all', label: 'All', count: localData.total },
                          { id: 'video', label: 'Videos', count: localData.videos.length, icon: VideoIcon },
                          { id: 'document', label: 'Documents', count: localData.documents.length, icon: FileText },
                          { id: 'audio', label: 'Audio', count: localData.audio.length, icon: Music },
                          { id: 'image', label: 'Images', count: localData.images.length, icon: ImageIcon },
                        ].map((sub) => {
                          const isSubActive = localCategoryFilter === sub.id;
                          return (
                            <button
                              key={sub.id}
                              onClick={() => setLocalCategoryFilter(sub.id as typeof localCategoryFilter)}
                              className="px-2.5 py-1 rounded-xl text-xs font-semibold transition-all"
                              style={{
                                background: isSubActive ? 'rgba(99,102,241,0.15)' : 'transparent',
                                color: isSubActive ? 'var(--accent)' : 'var(--text-muted)',
                                border: isSubActive ? '1px solid rgba(99,102,241,0.3)' : '1px solid transparent',
                              }}
                            >
                              {sub.label} ({searching ? '...' : sub.count})
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {searching ? (
                      <div className="space-y-4">
                        <div className="flex items-center gap-2 text-xs font-bold text-indigo-400 uppercase tracking-wider">
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          <span>Discovering files & calculating vector similarity...</span>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {[1, 2, 3, 4].map((i) => (
                            <div key={i} className="p-4 rounded-2xl border animate-pulse space-y-3"
                              style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}>
                              <div className="flex items-center justify-between">
                                <div className="h-4 w-28 bg-zinc-800 rounded" />
                                <div className="h-4 w-16 bg-indigo-500/20 rounded" />
                              </div>
                              <div className="h-5 w-3/4 bg-zinc-800 rounded" />
                              <div className="h-3 w-full bg-zinc-800/70 rounded" />
                              <div className="h-3 w-4/5 bg-zinc-800/50 rounded" />
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : localData.total === 0 ? (
                      <div className="p-8 rounded-3xl text-center" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                        <Database className="w-8 h-8 mx-auto mb-2 opacity-30" style={{ color: 'var(--text-muted)' }} />
                        <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>No matching local items found</p>
                        <p className="text-[11px] mt-1" style={{ color: 'var(--text-muted)' }}>Local search acts as precision context layer for live internet intelligence.</p>
                      </div>
                    ) : (
                      <div className="space-y-6">
                        {/* 2.1 Local Videos (With Face Match & Timestamp Jumping) */}
                        {(localCategoryFilter === 'all' || localCategoryFilter === 'video') && localData.videos.length > 0 && (
                          <div className="space-y-3">
                            <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider text-rose-400">
                              <span className="flex items-center gap-1.5"><VideoIcon className="w-3.5 h-3.5" /> Videos & Keyframes ({localData.videos.length})</span>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              {localData.videos.map((vid) => {
                                const isSelected = selectedLocalIds.has(vid.id);
                                return (
                                  <motion.div
                                    key={vid.id}
                                    whileHover={{ scale: 1.005 }}
                                    onClick={() => openSourceWithSeek(vid.sourceId, vid.startTime)}
                                    className="p-4 rounded-2xl transition-all cursor-pointer relative group flex flex-col gap-3"
                                    style={{
                                      background: 'var(--bg-elevated)',
                                      border: isSelected ? '1.5px solid #f43f5e' : '1px solid var(--border)',
                                      boxShadow: isSelected ? '0 4px 20px rgba(244,63,94,0.15)' : 'none',
                                    }}
                                  >
                                    <div className="flex items-start gap-3">
                                      <div className="mt-0.5 flex-shrink-0" onClick={(e) => { e.stopPropagation(); toggleLocalItem(vid.id); }}>
                                        {isSelected ? (
                                          <CheckCircle2 className="w-5 h-5 text-rose-400" />
                                        ) : (
                                          <Square className="w-5 h-5 text-zinc-500 hover:text-zinc-300" />
                                        )}
                                      </div>
                                      <div className="flex-1 min-w-0 space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                          <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
                                            <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
                                              style={{ background: 'var(--bg-active)', color: '#f43f5e' }}>
                                              {vid.fileType || 'VIDEO'}
                                            </span>

                                            {/* Face Match Badge */}
                                            {vid.isFaceMatch && (
                                              <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-pink-500/20 text-pink-300 border border-pink-500/40">
                                                <UserCheck className="w-3 h-3" /> Face Match {vid.faceSimilarity ? `${Math.round(vid.faceSimilarity * 100)}%` : ''}
                                              </span>
                                            )}

                                            <h3 className="text-xs font-bold truncate group-hover:text-rose-400 transition-colors"
                                              style={{ color: 'var(--text-primary)' }}>
                                              {vid.title}
                                            </h3>
                                          </div>
                                          <span className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-rose-500/10 text-rose-400 font-bold flex-shrink-0">
                                            {Math.round(vid.relevanceScore * 100)}% Match
                                          </span>
                                        </div>

                                        {/* Exact Timestamp Action Pill & Find Similar */}
                                        <div className="flex flex-wrap items-center gap-2 pt-1">
                                          {vid.startTime !== undefined && (
                                            <button
                                              type="button"
                                              onClick={(e) => {
                                                e.stopPropagation();
                                                openSourceWithSeek(vid.sourceId, vid.startTime);
                                              }}
                                              className="flex items-center gap-1 px-2.5 py-1 rounded-xl bg-rose-500/15 text-rose-400 hover:bg-rose-500/25 text-xs font-bold transition-all shadow-sm"
                                            >
                                              <Play className="w-3 h-3 fill-current" />
                                              <span>Play from {formatSeconds(vid.startTime)}</span>
                                            </button>
                                          )}
                                          <button
                                            type="button"
                                            disabled={searching}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              handleFindSimilar(vid.sourceId, vid.title);
                                            }}
                                            className="flex items-center gap-1 px-2.5 py-1 rounded-xl bg-cyan-500/15 text-cyan-400 hover:bg-cyan-500/25 text-xs font-semibold transition-all shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
                                            title="Find similar sources to this video"
                                          >
                                            <Sparkles className="w-3 h-3" />
                                            <span>Find Similar</span>
                                          </button>
                                          {vid.duration && (
                                            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                                              Duration: {formatDuration(vid.duration)}
                                            </span>
                                          )}
                                        </div>

                                        <p className="text-xs leading-relaxed line-clamp-3 select-text mt-1" style={{ color: 'var(--text-secondary)' }}>
                                          {vid.snippet}
                                        </p>
                                      </div>
                                    </div>
                                  </motion.div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* 2.2 Local Documents */}
                        {(localCategoryFilter === 'all' || localCategoryFilter === 'document') && localData.documents.length > 0 && (
                          <div className="space-y-3">
                            <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider text-indigo-400">
                              <span className="flex items-center gap-1.5"><FileText className="w-3.5 h-3.5" /> Documents & PDFs ({localData.documents.length})</span>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              {localData.documents.map((doc) => {
                                const isSelected = selectedLocalIds.has(doc.id);
                                return (
                                  <motion.div
                                    key={doc.id}
                                    whileHover={{ scale: 1.005 }}
                                    onClick={() => openSourceWithSeek(doc.sourceId)}
                                    className="p-4 rounded-2xl transition-all cursor-pointer relative group flex flex-col gap-3"
                                    style={{
                                      background: 'var(--bg-elevated)',
                                      border: isSelected ? '1.5px solid var(--accent)' : '1px solid var(--border)',
                                      boxShadow: isSelected ? '0 4px 20px rgba(99,102,241,0.15)' : 'none',
                                    }}
                                  >
                                    <div className="flex items-start gap-3">
                                      <div className="mt-0.5 flex-shrink-0" onClick={(e) => { e.stopPropagation(); toggleLocalItem(doc.id); }}>
                                        {isSelected ? (
                                          <CheckCircle2 className="w-5 h-5 text-indigo-400" />
                                        ) : (
                                          <Square className="w-5 h-5 text-zinc-500 hover:text-zinc-300" />
                                        )}
                                      </div>
                                      <div className="flex-1 min-w-0 space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                          <div className="flex items-center gap-2 min-w-0">
                                            <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
                                              style={{ background: 'var(--bg-active)', color: 'var(--accent)' }}>
                                              {doc.fileType || 'PDF'}
                                            </span>
                                            <h3 className="text-xs font-bold truncate group-hover:text-[var(--accent)] transition-colors"
                                              style={{ color: 'var(--text-primary)' }}>
                                              {doc.title}
                                            </h3>
                                          </div>
                                          <div className="flex items-center gap-1.5 flex-shrink-0">
                                            <button
                                              type="button"
                                              disabled={searching}
                                              onClick={(e) => {
                                                e.stopPropagation();
                                                handleFindSimilar(doc.sourceId, doc.title);
                                              }}
                                              className="flex items-center gap-1 px-2 py-1 rounded-xl bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 text-[11px] font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                              title="Find similar sources to this document"
                                            >
                                              <Sparkles className="w-3 h-3" />
                                              <span>Similar</span>
                                            </button>
                                            <a
                                              href={`/api/knowledge/${doc.sourceId}/file`}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              onClick={(e) => e.stopPropagation()}
                                              className="flex items-center gap-1 px-2 py-1 rounded-xl bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 text-[11px] font-semibold transition-colors"
                                              title="Open Original Document"
                                            >
                                              <span>Open</span>
                                              <ExternalLink className="w-3 h-3" />
                                            </a>
                                          </div>
                                        </div>
                                        <div className="flex items-center gap-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                                          {doc.pageNum && <span className="font-bold text-indigo-400">Page {doc.pageNum}</span>}
                                          {doc.sectionTitle && <span>· § {doc.sectionTitle}</span>}
                                          <span>· {formatBytes(doc.fileSize)}</span>
                                          <span className="ml-auto font-mono text-indigo-400 font-bold">{Math.round(doc.relevanceScore * 100)}% Match</span>
                                        </div>
                                        <p className="text-xs leading-relaxed line-clamp-3 select-text" style={{ color: 'var(--text-secondary)' }}>
                                          {doc.snippet}
                                        </p>
                                      </div>
                                    </div>
                                  </motion.div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* 2.3 Local Audio */}
                        {(localCategoryFilter === 'all' || localCategoryFilter === 'audio') && localData.audio.length > 0 && (
                          <div className="space-y-3">
                            <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider text-amber-400">
                              <span className="flex items-center gap-1.5"><Music className="w-3.5 h-3.5" /> Audio Recordings ({localData.audio.length})</span>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              {localData.audio.map((aud) => {
                                const isSelected = selectedLocalIds.has(aud.id);
                                return (
                                  <motion.div
                                    key={aud.id}
                                    whileHover={{ scale: 1.005 }}
                                    onClick={() => openSourceWithSeek(aud.sourceId, aud.startTime)}
                                    className="p-4 rounded-2xl transition-all cursor-pointer relative group flex flex-col gap-3"
                                    style={{
                                      background: 'var(--bg-elevated)',
                                      border: isSelected ? '1.5px solid #f59e0b' : '1px solid var(--border)',
                                    }}
                                  >
                                    <div className="flex items-start gap-3">
                                      <div className="mt-0.5 flex-shrink-0" onClick={(e) => { e.stopPropagation(); toggleLocalItem(aud.id); }}>
                                        {isSelected ? (
                                          <CheckCircle2 className="w-5 h-5 text-amber-400" />
                                        ) : (
                                          <Square className="w-5 h-5 text-zinc-500 hover:text-zinc-300" />
                                        )}
                                      </div>
                                      <div className="flex-1 min-w-0 space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                          <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
                                            style={{ background: 'var(--bg-active)', color: '#f59e0b' }}>
                                            AUDIO
                                          </span>
                                          <span className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-400 font-bold">
                                            {Math.round(aud.relevanceScore * 100)}% Match
                                          </span>
                                        </div>
                                        <h3 className="text-xs font-bold truncate group-hover:text-amber-400 transition-colors"
                                          style={{ color: 'var(--text-primary)' }}>
                                          {aud.title}
                                        </h3>

                                        <div className="flex flex-wrap items-center gap-2 pt-1">
                                          {aud.startTime !== undefined && (
                                            <button
                                              type="button"
                                              onClick={(e) => {
                                                e.stopPropagation();
                                                openSourceWithSeek(aud.sourceId, aud.startTime);
                                              }}
                                              className="flex items-center gap-1 px-2.5 py-1 rounded-xl bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 text-xs font-bold transition-colors"
                                            >
                                              <Play className="w-3 h-3 fill-current" />
                                              <span>Play from {formatSeconds(aud.startTime)}</span>
                                            </button>
                                          )}
                                          <button
                                            type="button"
                                            disabled={searching}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              handleFindSimilar(aud.sourceId, aud.title);
                                            }}
                                            className="flex items-center gap-1 px-2.5 py-1 rounded-xl bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 text-xs font-semibold transition-colors shadow-sm"
                                            title="Find similar sources"
                                          >
                                            <Sparkles className="w-3 h-3" />
                                            <span>Find Similar</span>
                                          </button>
                                        </div>

                                        <p className="text-xs leading-relaxed line-clamp-3 select-text" style={{ color: 'var(--text-secondary)' }}>
                                          {aud.snippet}
                                        </p>
                                      </div>
                                    </div>
                                  </motion.div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* 2.4 Local Images */}
                        {(localCategoryFilter === 'all' || localCategoryFilter === 'image') && localData.images.length > 0 && (
                          <div className="space-y-3">
                            <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider text-emerald-400">
                              <span className="flex items-center gap-1.5"><ImageIcon className="w-3.5 h-3.5" /> Images & Clippings ({localData.images.length})</span>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              {localData.images.map((img) => {
                                const isSelected = selectedLocalIds.has(img.id);
                                return (
                                  <motion.div
                                    key={img.id}
                                    whileHover={{ scale: 1.005 }}
                                    onClick={() => openSourceWithSeek(img.sourceId)}
                                    className="p-4 rounded-2xl transition-all cursor-pointer relative group flex gap-3"
                                    style={{
                                      background: 'var(--bg-elevated)',
                                      border: isSelected ? '1.5px solid #10b981' : '1px solid var(--border)',
                                      boxShadow: isSelected ? '0 4px 20px rgba(16,185,129,0.15)' : 'none',
                                    }}
                                  >
                                    <div className="mt-0.5 flex-shrink-0" onClick={(e) => { e.stopPropagation(); toggleLocalItem(img.id); }}>
                                      {isSelected ? (
                                        <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                                      ) : (
                                        <Square className="w-5 h-5 text-zinc-500 hover:text-zinc-300" />
                                      )}
                                    </div>
                                    <div className="flex-1 min-w-0 space-y-1.5">
                                      <div className="flex items-center justify-between gap-2">
                                        <div className="flex items-center gap-1.5">
                                          <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
                                            style={{ background: 'var(--bg-active)', color: '#10b981' }}>
                                            {img.fileType || 'IMAGE'}
                                          </span>
                                          <span className="text-[10px] font-mono text-emerald-400 font-bold">
                                            {Math.round(img.relevanceScore * 100)}% Match
                                          </span>
                                          {img.isFaceMatch && (
                                            <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-pink-500/20 text-pink-300 border border-pink-500/40">
                                              <UserCheck className="w-3 h-3" /> Face Match
                                            </span>
                                          )}
                                        </div>
                                        <div className="flex items-center gap-1.5">
                                          <button
                                            type="button"
                                            disabled={searching}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              handleFindSimilar(img.sourceId, img.title);
                                            }}
                                            className="flex items-center gap-1 px-2 py-1 rounded-xl bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 text-[11px] font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                            title="Find similar sources to this image"
                                          >
                                            <Sparkles className="w-3 h-3" />
                                            <span>Similar</span>
                                          </button>
                                          <button
                                            type="button"
                                            onClick={(e) => { e.stopPropagation(); openSourceWithSeek(img.sourceId); }}
                                            className="p-1.5 rounded-xl hover:bg-[var(--bg-active)] text-zinc-400 hover:text-emerald-400 transition-colors"
                                            title="View Image & OCR Details"
                                          >
                                            <Info className="w-3.5 h-3.5" />
                                          </button>
                                        </div>
                                      </div>
                                      <h3 className="text-xs font-bold truncate group-hover:text-emerald-400 transition-colors"
                                        style={{ color: 'var(--text-primary)' }}>
                                        {img.title}
                                      </h3>
                                      <p className="text-xs leading-relaxed line-clamp-3 select-text" style={{ color: 'var(--text-secondary)' }}>
                                        {img.snippet}
                                      </p>
                                    </div>
                                  </motion.div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* ═══════════════════════════════════════════════════════════════
                  3. DOCKED ACTIONS BAR: SEND TO AI CHAT & SYNTHESIS
                 ═══════════════════════════════════════════════════════════════ */}
              <div
                className="sticky bottom-6 p-4 rounded-3xl shadow-2xl flex flex-wrap items-center justify-between gap-4 z-20 backdrop-blur-xl"
                style={{
                  background: 'rgba(15, 23, 42, 0.94)',
                  border: '1px solid rgba(6,182,212,0.3)',
                  boxShadow: '0 20px 50px rgba(0,0,0,0.6), 0 0 25px rgba(6,182,212,0.25)',
                }}
              >
                <div className="flex items-center gap-3">
                  <div
                    className="w-9 h-9 rounded-2xl flex items-center justify-center font-bold text-white shadow-md"
                    style={{ background: 'linear-gradient(135deg, #06b6d4, #6366f1)' }}
                  >
                    <Sparkles className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="text-xs font-bold text-white">
                      {totalSelected} Sources Selected for AI Intelligence
                    </p>
                    <p className="text-[11px] text-zinc-400">
                      {selectedInternetIds.size} Internet Intelligence · {selectedLocalIds.size} Local Documents
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  {/* Generate Combined AI Synthesis */}
                  <button
                    onClick={handleSynthesize}
                    disabled={totalSelected === 0 || synthesizing}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-xl font-bold text-xs transition-all disabled:opacity-40 disabled:cursor-not-allowed text-white shadow-md hover:scale-105"
                    style={{
                      background: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)',
                      boxShadow: '0 4px 14px rgba(6,182,212,0.35)',
                    }}
                  >
                    {synthesizing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                    <span>{synthesizing ? 'Synthesizing...' : 'Summarize Selected Sources'}</span>
                  </button>

                  {/* Send to Dedicated AI Research Chat */}
                  <button
                    onClick={handleSendToAIChat}
                    disabled={totalSelected === 0 || startingChat}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-xl font-bold text-xs text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-md hover:scale-105"
                    style={{
                      background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
                      boxShadow: '0 4px 14px rgba(99,102,241,0.35)',
                    }}
                  >
                    {startingChat ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <MessageSquare className="w-3.5 h-3.5" />}
                    <span>Open in AI Research Chat</span>
                  </button>
                </div>
              </div>

              {/* ═══════════════════════════════════════════════════════════════
                  4. SYNTHESIS RESULT CARD (IF GENERATED)
                 ═══════════════════════════════════════════════════════════════ */}
              {synthesisResult && (
                <div
                  ref={synthesisRef}
                  className="p-6 rounded-3xl space-y-4 border shadow-2xl"
                  style={{
                    background: 'var(--bg-elevated)',
                    borderColor: 'rgba(6,182,212,0.3)',
                    boxShadow: '0 12px 30px rgba(0,0,0,0.3)',
                  }}
                >
                  <div className="flex items-center justify-between pb-3 border-b border-[var(--border)]">
                    <div className="flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-cyan-400" />
                      <h3 className="text-sm font-bold text-white">
                        AI Multimodal Intelligence Synthesis ({totalSelected} Sources)
                      </h3>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleCopySynthesis}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors hover:bg-[var(--bg-hover)]"
                        style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                      >
                        {copiedSynthesis ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                        <span>{copiedSynthesis ? 'Copied' : 'Copy'}</span>
                      </button>
                    </div>
                  </div>

                  <div className="prose prose-invert max-w-none text-xs leading-relaxed text-zinc-300">
                    <MarkdownMessage content={synthesisResult} />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Source Metadata & Playback Inspector Modal */}
      <DocumentMetadataModal
        isOpen={Boolean(inspectSourceId || inspectInternetItem)}
        onClose={() => {
          setInspectSourceId(null);
          setInspectTimestamp(undefined);
          setInspectInternetItem(null);
        }}
        sourceId={inspectSourceId}
        initialTimestamp={inspectTimestamp}
        internetItem={inspectInternetItem}
        onFindSimilar={handleFindSimilar}
      />
    </div>
  );
}
