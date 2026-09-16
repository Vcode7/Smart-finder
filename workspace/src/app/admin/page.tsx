'use client';
// src/app/admin/page.tsx — Create/Update Repository Management with Local Uploads & Internet Data Scraper

import { useState, useEffect, useCallback, useRef, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload, FileText, Video, Image as ImageIcon, Trash2, RefreshCw, CheckCircle,
  XCircle, Clock, Loader2, Database, ChevronLeft, AlertCircle,
  File, BarChart3, Sparkles, Info, Globe, Search, Plus, CheckSquare, Square,
  BookOpen, Newspaper, ExternalLink, Layers, Check, ArrowRight, Filter
} from 'lucide-react';
import { useAuthStore } from '@/store/auth';
import { toast } from 'sonner';
import Sidebar from '@/components/layout/Sidebar';
import DocumentMetadataModal from '@/components/modals/DocumentMetadataModal';
import type { ScrapedSourceItem } from '@/types/research';

interface KnowledgeSource {
  id: string;
  original_name: string;
  file_type: string;
  file_size: number;
  upload_date: string;
  processing_status: 'uploaded' | 'processing' | 'indexing' | 'completed' | 'failed';
  error_message?: string;
  chunk_count: number;
  transcript_count: number;
  face_count: number;
  uploader_name: string;
  metadata_json?: string;
  file_path?: string;
}

const STATUS_CONFIG = {
  uploaded: { icon: Clock, color: '#6366f1', label: 'Queued', bg: 'rgba(99,102,241,0.1)' },
  processing: { icon: Loader2, color: '#f59e0b', label: 'Processing', bg: 'rgba(245,158,11,0.1)', spin: true },
  indexing: { icon: Loader2, color: '#06b6d4', label: 'Indexing', bg: 'rgba(6,182,212,0.1)', spin: true },
  completed: { icon: CheckCircle, color: '#10b981', label: 'Ready', bg: 'rgba(16,185,129,0.1)' },
  failed: { icon: XCircle, color: '#f43f5e', label: 'Failed', bg: 'rgba(244,63,94,0.1)' },
};

const TYPE_ICONS: Record<string, typeof FileText> = {
  pdf: FileText, docx: FileText, doc: FileText, txt: FileText, md: FileText,
  csv: FileText, xlsx: FileText, xls: FileText, json: FileText, xml: FileText, html: FileText,
  jpg: ImageIcon, jpeg: ImageIcon, png: ImageIcon, webp: ImageIcon, gif: ImageIcon,
  mp4: Video, avi: Video, mov: Video, mkv: Video, webm: Video,
  paper: BookOpen, article: FileText, news: Newspaper, web: Globe, image: ImageIcon, video: Video,
};

function isInternetSource(source: KnowledgeSource): boolean {
  if (['web', 'paper', 'news', 'article', 'internet', 'video', 'image'].includes(source.file_type.toLowerCase())) return true;
  if (source.file_path && (source.file_path.startsWith('http://') || source.file_path.startsWith('https://'))) return true;
  if (source.metadata_json) {
    try {
      const meta = JSON.parse(source.metadata_json);
      if (meta.source_type === 'internet' || meta.url) return true;
    } catch {}
  }
  return false;
}

function getSourceUrl(source: KnowledgeSource): string | null {
  if (source.metadata_json) {
    try {
      const meta = JSON.parse(source.metadata_json);
      if (meta.url || meta.original_url) return meta.url || meta.original_url;
    } catch {}
  }
  if (source.file_path && source.file_path.startsWith('http')) return source.file_path;
  return null;
}

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(dateStr: string) {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export default function AdminRepositoryPage() {
  const [activeTab, setActiveTab] = useState<'upload' | 'scrape' | 'inventory'>('scrape');
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const { user } = useAuthStore();

  // ─── Scrape Data from Internet State ─────────────────────────────
  const [scrapeQuery, setScrapeQuery] = useState('');
  const [scraping, setScraping] = useState(false);
  const [hasScraped, setHasScraped] = useState(false);
  const [scrapedCategoryFilter, setScrapedCategoryFilter] = useState<'all' | 'paper' | 'article' | 'news' | 'video' | 'image'>('all');
  const [scrapedResults, setScrapedResults] = useState<{
    papers: ScrapedSourceItem[];
    articles: ScrapedSourceItem[];
    news: ScrapedSourceItem[];
    videos: ScrapedSourceItem[];
    images: ScrapedSourceItem[];
    others: ScrapedSourceItem[];
    total: number;
  }>({ papers: [], articles: [], news: [], videos: [], images: [], others: [], total: 0 });
  const [selectedScrapeIds, setSelectedScrapeIds] = useState<Set<string>>(new Set());
  const [importingToRepo, setImportingToRepo] = useState(false);

  // ─── Inventory Filter State ──────────────────────────────────────
  const [inventoryFilter, setInventoryFilter] = useState<'all' | 'local' | 'internet'>('all');
  const [inventorySearch, setInventorySearch] = useState('');

  // ─── Duplicate File Warning State ────────────────────────────────
  const [duplicateConflicts, setDuplicateConflicts] = useState<{ originalName: string; suggestedName: string }[]>([]);
  const [pendingUploadFiles, setPendingUploadFiles] = useState<File[] | null>(null);
  const [showDuplicateModal, setShowDuplicateModal] = useState(false);

  const fetchSources = useCallback(async () => {
    try {
      const res = await fetch('/api/knowledge');
      if (res.ok) {
        const data = await res.json();
        setSources(data.sources || []);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user && user.role !== 'admin') { router.push('/'); return; }
    fetchSources();
    const interval = setInterval(fetchSources, 4000);
    return () => clearInterval(interval);
  }, [user, router, fetchSources]);

  // ─── Core Upload Execution ────────────────────────────────────────
  const executeUpload = async (files: File[], resolveDuplicates: boolean = false) => {
    setUploading(true);
    const formData = new FormData();
    for (const file of files) formData.append('files', file);
    if (resolveDuplicates) {
      formData.append('resolve_duplicates', 'true');
    }

    try {
      const res = await fetch('/api/knowledge/upload', { method: 'POST', body: formData });
      const data = await res.json();
      if (res.ok) {
        const success = data.results?.filter((r: { error?: string }) => !r.error).length || 0;
        const failed = data.results?.filter((r: { error?: string }) => r.error).length || 0;
        if (success > 0) toast.success(`${success} file${success > 1 ? 's' : ''} uploaded & queued for processing`);
        if (failed > 0) toast.error(`${failed} file${failed > 1 ? 's' : ''} failed validation`);
        await fetchSources();
        setActiveTab('inventory');
      } else {
        toast.error(data.error || 'Upload failed');
      }
    } catch {
      toast.error('Upload failed. Please try again.');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // ─── Upload Handler with Pre-Check for Duplicates ─────────────────
  const handleUpload = async (files: FileList | File[]) => {
    const fileArray = Array.from(files);
    if (fileArray.length === 0) return;

    // Check whether any file with the same name already exists
    try {
      const checkRes = await fetch('/api/knowledge/check-conflicts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filenames: fileArray.map((f) => f.name) }),
      });

      if (checkRes.ok) {
        const checkData = await checkRes.json();
        if (checkData.hasConflicts && checkData.conflicts?.length > 0) {
          setDuplicateConflicts(checkData.conflicts);
          setPendingUploadFiles(fileArray);
          setShowDuplicateModal(true);
          return;
        }
      }
    } catch (e) {
      console.warn('[Upload] Conflict pre-check failed, proceeding with direct upload', e);
    }

    // No conflict detected: upload directly with original filename
    await executeUpload(fileArray, false);
  };

  const handleConfirmDuplicateUpload = async () => {
    if (!pendingUploadFiles) return;
    const filesToUpload = pendingUploadFiles;
    setShowDuplicateModal(false);
    setPendingUploadFiles(null);
    setDuplicateConflicts([]);
    // Upload with resolve_duplicates=true so backend assigns unique suffixes without overwriting
    await executeUpload(filesToUpload, true);
  };

  const handleCancelDuplicateUpload = () => {
    setShowDuplicateModal(false);
    setPendingUploadFiles(null);
    setDuplicateConflicts([]);
    if (fileInputRef.current) fileInputRef.current.value = '';
    toast.info('Upload cancelled.');
  };

  // ─── Scrape Internet Search Handler ──────────────────────────────
  const handleScrapeSearch = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!scrapeQuery.trim() || scraping) return;

    setScraping(true);
    setHasScraped(true);
    setSelectedScrapeIds(new Set());

    try {
      const res = await fetch('/api/knowledge/scrape-search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: scrapeQuery.trim() }),
      });

      if (!res.ok) {
        toast.error('Internet scrape search failed');
        return;
      }

      const data = await res.json();

      // Support structured categories or fallback to grouping flat sources array
      let categories = data.categories;
      if (!categories && Array.isArray(data.sources)) {
        categories = {
          papers: data.sources.filter((s: ScrapedSourceItem) => s.category === 'paper'),
          articles: data.sources.filter((s: ScrapedSourceItem) => ['article', 'web'].includes(s.category)),
          news: data.sources.filter((s: ScrapedSourceItem) => ['news', 'report'].includes(s.category)),
          videos: data.sources.filter((s: ScrapedSourceItem) => s.category === 'video'),
          images: data.sources.filter((s: ScrapedSourceItem) => s.category === 'image'),
          others: data.sources.filter((s: ScrapedSourceItem) => !['paper', 'article', 'web', 'news', 'report', 'video', 'image'].includes(s.category)),
        };
      }
      categories = categories || { papers: [], articles: [], news: [], videos: [], images: [], others: [] };

      const computedTotal = (
        (categories.papers?.length || 0) +
        (categories.articles?.length || 0) +
        (categories.news?.length || 0) +
        (categories.videos?.length || 0) +
        (categories.images?.length || 0) +
        (categories.others?.length || 0)
      );
      const total = data.counts?.total ?? data.counts?.all ?? computedTotal;

      setScrapedResults({
        papers: categories.papers || [],
        articles: categories.articles || [],
        news: categories.news || [],
        videos: categories.videos || [],
        images: categories.images || [],
        others: categories.others || [],
        total,
      });

      // Pre-select top relevant sources by default
      const initialSelected = new Set<string>();
      if (categories.papers?.length > 0) initialSelected.add(categories.papers[0].id);
      if (categories.articles?.length > 0) initialSelected.add(categories.articles[0].id);
      if (categories.news?.length > 0) initialSelected.add(categories.news[0].id);
      if (categories.videos?.length > 0) initialSelected.add(categories.videos[0].id);
      if (categories.images?.length > 0) initialSelected.add(categories.images[0].id);
      setSelectedScrapeIds(initialSelected);

      if (total > 0) {
        toast.success(`Discovered ${total} internet sources across categories`);
      } else {
        toast.info('No sources discovered for this query. Try broader keywords.');
      }
    } catch {
      toast.error('Network error during internet scrape');
    } finally {
      setScraping(false);
    }
  };

  const allScrapedList: ScrapedSourceItem[] = [
    ...scrapedResults.papers,
    ...scrapedResults.articles,
    ...scrapedResults.news,
    ...scrapedResults.videos,
    ...scrapedResults.images,
    ...scrapedResults.others,
  ];

  const visibleScrapedList = scrapedCategoryFilter === 'all'
    ? allScrapedList
    : scrapedCategoryFilter === 'paper'
    ? scrapedResults.papers
    : scrapedCategoryFilter === 'article'
    ? scrapedResults.articles
    : scrapedCategoryFilter === 'news'
    ? scrapedResults.news
    : scrapedCategoryFilter === 'video'
    ? scrapedResults.videos
    : scrapedResults.images;

  const toggleSelectScrapedItem = (id: string) => {
    setSelectedScrapeIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllScraped = () => {
    if (selectedScrapeIds.size === visibleScrapedList.length) {
      setSelectedScrapeIds(new Set());
    } else {
      setSelectedScrapeIds(new Set(visibleScrapedList.map((item) => item.id)));
    }
  };

  // ─── Import Selected Internet Sources to Local Repository ────────
  const handleImportToRepository = async () => {
    const selectedItems = allScrapedList.filter((item) => selectedScrapeIds.has(item.id));
    if (selectedItems.length === 0 || importingToRepo) {
      toast.error('Please select at least one internet source to add to the repository');
      return;
    }

    setImportingToRepo(true);
    try {
      const res = await fetch('/api/knowledge/import-internet', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources: selectedItems }),
      });

      const data = await res.json();
      if (res.ok) {
        toast.success(data.message || `Added ${selectedItems.length} internet sources to local repository!`);
        await fetchSources();
        setActiveTab('inventory');
      } else {
        toast.error(data.error || 'Failed to import internet sources');
      }
    } catch {
      toast.error('Failed to import internet sources to repository');
    } finally {
      setImportingToRepo(false);
    }
  };

  // ─── Delete & Reprocess ───────────────────────────────────────────
  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Delete "${name}" and all its indexed repository data? This cannot be undone.`)) return;
    try {
      const res = await fetch(`/api/knowledge/${id}`, { method: 'DELETE' });
      if (res.ok) {
        setSources((prev) => prev.filter((s) => s.id !== id));
        toast.success('Source deleted from repository');
      } else {
        toast.error('Delete failed');
      }
    } catch {
      toast.error('Delete failed');
    }
  };

  const handleReprocess = async (id: string) => {
    try {
      const res = await fetch(`/api/knowledge/${id}/reprocess`, { method: 'POST' });
      if (res.ok) {
        toast.success('Reprocessing started');
        await fetchSources();
      } else {
        toast.error('Reprocess failed');
      }
    } catch {
      toast.error('Reprocess failed');
    }
  };

  // ─── Sync & Reset ────────────────────────────────────────────────
  const [syncingFolder, setSyncingFolder] = useState(false);
  const [resettingKb, setResettingKb] = useState(false);

  const handleSyncFolder = async () => {
    setSyncingFolder(true);
    try {
      const res = await fetch('/api/knowledge/sync', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        toast.success(data.message || 'Knowledge Base folder synced successfully!');
        await fetchSources();
      } else {
        toast.error(data.error || 'Failed to sync knowledge folder');
      }
    } catch {
      toast.error('Sync request failed');
    } finally {
      setSyncingFolder(false);
    }
  };

  const handleResetKnowledgeBase = async () => {
    if (!confirm('Are you sure you want to reset all indexed knowledge records and derived embeddings? The physical files in knowledge_base will be preserved.')) return;
    setResettingKb(true);
    try {
      const res = await fetch('/api/knowledge/reset', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        toast.success(data.message || 'Repository database reset successfully!');
        await fetchSources();
      } else {
        toast.error(data.error || 'Failed to reset repository');
      }
    } catch {
      toast.error('Reset request failed');
    } finally {
      setResettingKb(false);
    }
  };

  // ─── Computed Stats ──────────────────────────────────────────────
  const internetSourcesCount = sources.filter((s) => isInternetSource(s)).length;
  const localFilesCount = sources.filter((s) => !isInternetSource(s)).length;

  const stats = {
    total: sources.length,
    localCount: localFilesCount,
    internetCount: internetSourcesCount,
    completed: sources.filter((s) => s.processing_status === 'completed').length,
    processing: sources.filter((s) => ['processing', 'indexing', 'uploaded'].includes(s.processing_status)).length,
    failed: sources.filter((s) => s.processing_status === 'failed').length,
    totalChunks: sources.reduce((acc, s) => acc + (s.chunk_count || 0), 0),
  };

  // ─── Inventory Filter ────────────────────────────────────────────
  const filteredSources = sources.filter((s) => {
    const isInt = isInternetSource(s);
    if (inventoryFilter === 'local' && isInt) return false;
    if (inventoryFilter === 'internet' && !isInt) return false;
    if (inventorySearch.trim()) {
      const q = inventorySearch.toLowerCase();
      return (
        s.original_name.toLowerCase().includes(q) ||
        s.file_type.toLowerCase().includes(q) ||
        (s.uploader_name || '').toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      <Sidebar />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-4 sm:px-8 py-8 space-y-8">
          {/* Header & Main Actions */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <div className="w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0 shadow-lg"
                style={{ background: 'linear-gradient(135deg, #6366f1 0%, #06b6d4 100%)', boxShadow: '0 0 28px rgba(99,102,241,0.35)' }}>
                <Database className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight" style={{ color: 'var(--text-primary)' }}>
                  Create/Update Repository
                </h1>
                <p className="text-xs sm:text-sm mt-0.5" style={{ color: 'var(--text-secondary)' }}>
                  Upload local files or scrape internet intelligence to create, chunk, and update your searchable AI repository
                </p>
              </div>
            </div>

            {/* Quick Repository Action Buttons */}
            <div className="flex items-center gap-2.5 flex-wrap">
              <button
                onClick={handleResetKnowledgeBase}
                disabled={resettingKb || syncingFolder}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold transition-all text-rose-300 bg-rose-500/10 border border-rose-500/25 hover:bg-rose-500/20 disabled:opacity-50"
                title="Reset all indexed database tables, chunk vectors, and embeddings"
              >
                <Trash2 className="w-3.5 h-3.5 text-rose-400" />
                <span>{resettingKb ? 'Resetting...' : 'Reset Indexes'}</span>
              </button>

              <button
                onClick={handleSyncFolder}
                disabled={syncingFolder || resettingKb}
                className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all text-white shadow-md disabled:opacity-50"
                style={{
                  background: 'linear-gradient(135deg, #6366f1 0%, #06b6d4 100%)',
                  boxShadow: '0 4px 14px rgba(99,102,241,0.3)',
                }}
                title="Scan and index all files in the knowledge_base folder"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${syncingFolder ? 'animate-spin' : ''}`} />
                <span>{syncingFolder ? 'Syncing...' : 'Sync Local Folder'}</span>
              </button>
            </div>
          </div>

          {/* Stats Bar */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            {[
              { label: 'Total Sources', value: stats.total, icon: Database, color: '#6366f1' },
              { label: 'Local Files', value: stats.localCount, icon: File, color: '#8b5cf6' },
              { label: 'Internet Sources', value: stats.internetCount, icon: Globe, color: '#06b6d4' },
              { label: 'Ready for AI', value: stats.completed, icon: CheckCircle, color: '#10b981' },
              { label: 'Indexed Chunks', value: stats.totalChunks.toLocaleString(), icon: BarChart3, color: '#f59e0b' },
            ].map((stat) => {
              const Icon = stat.icon;
              return (
                <div key={stat.label} className="p-3.5 rounded-2xl flex flex-col justify-between"
                  style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                  <div className="flex items-center gap-1.5 mb-1">
                    <Icon className="w-3.5 h-3.5" style={{ color: stat.color }} />
                    <span className="text-[10px] font-semibold uppercase tracking-wider truncate" style={{ color: 'var(--text-muted)' }}>
                      {stat.label}
                    </span>
                  </div>
                  <p className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{stat.value}</p>
                </div>
              );
            })}
          </div>

          {/* Primary View Tabs */}
          <div className="flex items-center gap-2 p-1.5 rounded-2xl overflow-x-auto"
            style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
            {[
              { id: 'scrape', label: 'Scrape Data from Internet', icon: Globe, badge: 'New AI Scraper' },
              { id: 'upload', label: 'Upload Local Files', icon: Upload },
              { id: 'inventory', label: `Repository Inventory (${sources.length})`, icon: Layers },
            ].map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as typeof activeTab)}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex-shrink-0"
                  style={{
                    background: isActive ? 'linear-gradient(135deg, #6366f1 0%, #06b6d4 100%)' : 'transparent',
                    color: isActive ? '#fff' : 'var(--text-secondary)',
                    boxShadow: isActive ? '0 4px 14px rgba(99,102,241,0.35)' : 'none',
                  }}
                >
                  <Icon className="w-4 h-4" />
                  <span>{tab.label}</span>
                  {tab.badge && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase"
                      style={{
                        background: isActive ? 'rgba(255,255,255,0.25)' : 'rgba(6,182,212,0.15)',
                        color: isActive ? '#fff' : '#06b6d4',
                      }}>
                      {tab.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* ═══════════════════════════════════════════════════════════════
              TAB 1: SCRAPE DATA FROM INTERNET
             ═══════════════════════════════════════════════════════════════ */}
          {activeTab === 'scrape' && (
            <div className="space-y-6">
              {/* Scraper Search Box */}
              <div className="p-6 rounded-3xl space-y-4 shadow-xl"
                style={{
                  background: 'var(--bg-elevated)',
                  border: '1px solid var(--border)',
                  boxShadow: '0 12px 36px rgba(0,0,0,0.3), 0 0 0 1px rgba(6,182,212,0.15)',
                }}>
                <div>
                  <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold mb-2"
                    style={{ background: 'rgba(6,182,212,0.12)', color: '#06b6d4', border: '1px solid rgba(6,182,212,0.25)' }}>
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Live Intelligence Scraper</span>
                  </div>
                  <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
                    Scrape & Index Internet Sources to Repository
                  </h2>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
                    Enter any topic or query to fetch research papers, news, articles, video metadata, and web sources. Select and add them directly into your local database.
                  </p>
                </div>

                <form onSubmit={handleScrapeSearch} className="flex gap-2">
                  <div className="flex-1 relative">
                    <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-cyan-400" />
                    <input
                      type="text"
                      value={scrapeQuery}
                      onChange={(e) => setScrapeQuery(e.target.value)}
                      placeholder="Enter a topic (e.g., Quantum Computing Architectures, Climate Policy 2026, Exam Integrity Systems)..."
                      className="w-full pl-10 pr-4 py-3 rounded-2xl text-xs sm:text-sm outline-none font-medium transition-all"
                      style={{
                        background: 'var(--bg-base)',
                        border: '1px solid var(--border)',
                        color: 'var(--text-primary)',
                      }}
                      onFocus={(e) => { e.target.style.borderColor = '#06b6d4'; }}
                      onBlur={(e) => { e.target.style.borderColor = 'var(--border)'; }}
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={!scrapeQuery.trim() || scraping}
                    className="flex items-center gap-2 px-6 py-3 rounded-2xl font-bold text-xs sm:text-sm text-white shadow-md transition-all disabled:opacity-40"
                    style={{
                      background: 'linear-gradient(135deg, #06b6d4 0%, #6366f1 100%)',
                      boxShadow: '0 4px 16px rgba(6,182,212,0.35)',
                    }}
                  >
                    {scraping ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Scraping...</span>
                      </>
                    ) : (
                      <>
                        <Globe className="w-4 h-4" />
                        <span>Fetch Sources</span>
                      </>
                    )}
                  </button>
                </form>

                {/* Quick Topic Pills */}
                <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
                  <span className="text-[11px] font-medium" style={{ color: 'var(--text-muted)' }}>Suggestions:</span>
                  {[
                    'Deep Learning & Vision Transformers',
                    'SSC Exam Governance & Biometrics',
                    'NEET Examination System',
                    'Renewable Energy Policy Frameworks',
                    'Generative AI Agent Protocols',
                  ].map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => {
                        setScrapeQuery(preset);
                      }}
                      className="text-[11px] px-2.5 py-1 rounded-xl transition-all hover:border-cyan-500/40"
                      style={{
                        background: 'var(--bg-base)',
                        border: '1px solid var(--border)',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      {preset}
                    </button>
                  ))}
                </div>
              </div>

              {/* Scraped Results Section */}
              {hasScraped && (
                <div className="space-y-4">
                  {/* Category Filter & Batch Ingestion Bar */}
                  <div className="p-4 rounded-2xl flex flex-wrap items-center justify-between gap-3"
                    style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                    {/* Category Filter Pills */}
                    <div className="flex items-center gap-1 flex-wrap">
                      {[
                        { id: 'all', label: 'All Categories', count: scrapedResults.total, icon: Layers },
                        { id: 'paper', label: 'Research Papers', count: scrapedResults.papers.length, icon: BookOpen },
                        { id: 'article', label: 'Articles & Web', count: scrapedResults.articles.length, icon: FileText },
                        { id: 'news', label: 'News', count: scrapedResults.news.length, icon: Newspaper },
                        { id: 'video', label: 'Videos', count: scrapedResults.videos.length, icon: Video },
                        { id: 'image', label: 'Images', count: scrapedResults.images.length, icon: ImageIcon },
                      ].map((cat) => {
                        const isCatActive = scrapedCategoryFilter === cat.id;
                        const Icon = cat.icon;
                        return (
                          <button
                            key={cat.id}
                            onClick={() => setScrapedCategoryFilter(cat.id as typeof scrapedCategoryFilter)}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all"
                            style={{
                              background: isCatActive ? 'rgba(6,182,212,0.15)' : 'transparent',
                              color: isCatActive ? '#06b6d4' : 'var(--text-muted)',
                              border: isCatActive ? '1px solid rgba(6,182,212,0.3)' : '1px solid transparent',
                            }}
                          >
                            <Icon className="w-3.5 h-3.5" />
                            <span>{cat.label}</span>
                            <span className="text-[10px] px-1.5 py-0.2 rounded-full"
                              style={{ background: 'var(--bg-active)', color: 'var(--text-secondary)' }}>
                              {cat.count}
                            </span>
                          </button>
                        );
                      })}
                    </div>

                    {/* Actions: Select All & Add to Local Repository */}
                    <div className="flex items-center gap-2">
                      <button
                        onClick={selectAllScraped}
                        className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold hover:bg-[var(--bg-hover)] transition-colors"
                        style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                      >
                        <CheckSquare className="w-3.5 h-3.5 text-cyan-400" />
                        <span>Select All ({selectedScrapeIds.size})</span>
                      </button>

                      <button
                        onClick={handleImportToRepository}
                        disabled={selectedScrapeIds.size === 0 || importingToRepo}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold text-white shadow-md transition-all disabled:opacity-40"
                        style={{
                          background: 'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)',
                          boxShadow: '0 4px 14px rgba(16,185,129,0.35)',
                        }}
                      >
                        {importingToRepo ? (
                          <>
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            <span>Processing & Chunking...</span>
                          </>
                        ) : (
                          <>
                            <Plus className="w-4 h-4" />
                            <span>Add to Local Repository ({selectedScrapeIds.size})</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Results List */}
                  {visibleScrapedList.length === 0 ? (
                    <div className="text-center py-16 rounded-3xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                      <Globe className="w-10 h-10 mx-auto mb-3 opacity-30 text-cyan-400" />
                      <p className="font-semibold text-sm" style={{ color: 'var(--text-secondary)' }}>No sources found in this category</p>
                      <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Try choosing another category tab above or searching for a broader query</p>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                      {visibleScrapedList.map((item) => {
                        const isSelected = selectedScrapeIds.has(item.id);
                        const Icon = TYPE_ICONS[item.category] || Globe;
                        return (
                          <motion.div
                            key={item.id}
                            whileHover={{ scale: 1.005 }}
                            onClick={() => toggleSelectScrapedItem(item.id)}
                            className="p-4 rounded-2xl flex gap-3.5 cursor-pointer transition-all relative group"
                            style={{
                              background: 'var(--bg-elevated)',
                              border: isSelected ? '1.5px solid #06b6d4' : '1px solid var(--border)',
                              boxShadow: isSelected ? '0 4px 20px rgba(6,182,212,0.18)' : 'none',
                            }}
                          >
                            <div className="mt-0.5 flex-shrink-0" onClick={(e) => { e.stopPropagation(); toggleSelectScrapedItem(item.id); }}>
                              {isSelected ? (
                                <CheckCircle className="w-5 h-5 text-cyan-400" />
                              ) : (
                                <Square className="w-5 h-5 text-zinc-500 group-hover:text-zinc-300" />
                              )}
                            </div>

                            <div className="flex-1 min-w-0 space-y-1.5">
                              <div className="flex items-center justify-between gap-2">
                                <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
                                  style={{ background: 'rgba(6,182,212,0.12)', color: '#06b6d4' }}>
                                  <Icon className="w-3 h-3" />
                                  <span>{item.category}</span>
                                </span>

                                <a
                                  href={item.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  className="p-1 rounded-lg hover:bg-[var(--bg-hover)] text-zinc-400 hover:text-cyan-400 transition-colors"
                                  title="Open source URL"
                                >
                                  <ExternalLink className="w-3.5 h-3.5" />
                                </a>
                              </div>

                              <h3 className="text-xs font-bold line-clamp-2 group-hover:text-cyan-400 transition-colors"
                                style={{ color: 'var(--text-primary)' }}>
                                {item.title}
                              </h3>

                              <p className="text-xs line-clamp-2 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                                {item.snippet || 'No preview available.'}
                              </p>

                              {/* Metadata footer */}
                              <div className="flex items-center gap-3 pt-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                                <span className="truncate max-w-[140px] font-medium text-cyan-300">{item.platform || item.domain}</span>
                                {item.author && <span className="truncate max-w-[120px]">By {item.author}</span>}
                                {item.publishedDate && <span>{item.publishedDate}</span>}
                              </div>
                            </div>
                          </motion.div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════════
              TAB 2: UPLOAD LOCAL FILES
             ═══════════════════════════════════════════════════════════════ */}
          {activeTab === 'upload' && (
            <div className="space-y-6">
              {/* Permanent Knowledge Folder Banner */}
              <div
                className="p-4 rounded-3xl border flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs"
                style={{
                  background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(6, 182, 212, 0.08) 100%)',
                  borderColor: 'rgba(99, 102, 241, 0.25)',
                }}
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-xl bg-indigo-500/20 text-indigo-400 flex items-center justify-center flex-shrink-0">
                    <File className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="font-bold text-slate-200">
                      Permanent Knowledge Directory: <code className="px-2 py-0.5 rounded bg-slate-900/80 text-cyan-300 font-mono text-[11px]">knowledge_base/</code>
                    </p>
                    <p className="text-slate-400 text-[11px] mt-0.5">
                      All documents, videos, audio, and images in this folder are auto-discovered and indexed with vector embeddings.
                    </p>
                  </div>
                </div>
              </div>

              {/* Upload Zone */}
              <motion.div
                className={`relative rounded-3xl border-2 border-dashed p-10 text-center cursor-pointer transition-all ${dragOver ? 'scale-[1.01]' : ''}`}
                style={{
                  borderColor: dragOver ? 'var(--accent)' : 'var(--border)',
                  background: dragOver ? 'var(--accent-muted)' : 'var(--bg-elevated)',
                }}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => { e.preventDefault(); setDragOver(false); handleUpload(e.dataTransfer.files); }}
                whileHover={{ scale: 1.005 }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  accept=".pdf,.docx,.doc,.txt,.md,.csv,.xlsx,.xls,.json,.xml,.html,.jpg,.jpeg,.png,.webp,.mp4,.avi,.mov,.mkv,.webm"
                  onChange={(e) => e.target.files && handleUpload(e.target.files)}
                />
                {uploading ? (
                  <div className="flex flex-col items-center gap-3">
                    <Loader2 className="w-10 h-10 animate-spin" style={{ color: 'var(--accent)' }} />
                    <p className="font-semibold" style={{ color: 'var(--text-primary)' }}>Uploading & queuing files...</p>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-3">
                    <div className="w-14 h-14 rounded-2xl flex items-center justify-center"
                      style={{ background: 'var(--accent-muted)' }}>
                      <Upload className="w-7 h-7" style={{ color: 'var(--accent)' }} />
                    </div>
                    <div>
                      <p className="font-semibold text-lg" style={{ color: 'var(--text-primary)' }}>
                        Drop local files here or click to browse
                      </p>
                      <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>
                        PDF, DOCX, TXT, CSV, XLSX, JSON · JPG, PNG, WEBP · MP4, AVI, MOV, MKV, WEBM
                      </p>
                      <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Auto-chunked & indexed with vector embeddings</p>
                    </div>
                  </div>
                )}
              </motion.div>
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════════
              TAB 3: REPOSITORY INVENTORY
             ═══════════════════════════════════════════════════════════════ */}
          {activeTab === 'inventory' && (
            <div className="space-y-4">
              {/* Inventory Filter Bar */}
              <div className="p-4 rounded-2xl flex flex-col sm:flex-row items-center justify-between gap-3"
                style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                {/* Source Type Filter (All / Local / Internet) */}
                <div className="flex items-center gap-1.5 p-1 rounded-xl" style={{ background: 'var(--bg-base)' }}>
                  {[
                    { id: 'all', label: 'All Sources', count: sources.length },
                    { id: 'local', label: '📁 Local Files', count: localFilesCount },
                    { id: 'internet', label: '🌐 Internet Sources', count: internetSourcesCount },
                  ].map((f) => {
                    const isFilterActive = inventoryFilter === f.id;
                    return (
                      <button
                        key={f.id}
                        onClick={() => setInventoryFilter(f.id as typeof inventoryFilter)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
                        style={{
                          background: isFilterActive ? 'var(--accent)' : 'transparent',
                          color: isFilterActive ? '#fff' : 'var(--text-secondary)',
                        }}
                      >
                        <span>{f.label}</span>
                        <span className="text-[10px] px-1.5 py-0.2 rounded-full"
                          style={{
                            background: isFilterActive ? 'rgba(255,255,255,0.25)' : 'var(--bg-active)',
                            color: isFilterActive ? '#fff' : 'var(--text-muted)',
                          }}>
                          {f.count}
                        </span>
                      </button>
                    );
                  })}
                </div>

                {/* Search within Repository */}
                <div className="w-full sm:w-64 relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-400" />
                  <input
                    type="text"
                    value={inventorySearch}
                    onChange={(e) => setInventorySearch(e.target.value)}
                    placeholder="Filter repository..."
                    className="w-full pl-8 pr-3 py-1.5 rounded-xl text-xs outline-none"
                    style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                  />
                </div>
              </div>

              {/* Sources Table */}
              {loading ? (
                <div className="flex items-center justify-center py-20">
                  <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--accent)' }} />
                </div>
              ) : filteredSources.length === 0 ? (
                <div className="text-center py-20 rounded-3xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                  <Sparkles className="w-12 h-12 mx-auto mb-3 opacity-30" style={{ color: 'var(--text-muted)' }} />
                  <p className="font-semibold text-sm" style={{ color: 'var(--text-secondary)' }}>No repository sources found</p>
                  <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Upload files or scrape internet intelligence to build your AI repository</p>
                </div>
              ) : (
                <div className="rounded-2xl overflow-hidden shadow-lg" style={{ border: '1px solid var(--border)', background: 'var(--bg-elevated)' }}>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-active)' }}>
                          {['Source Name', 'Origin / Type', 'Size / Length', 'Date Added', 'Status', 'Chunks', 'Actions'].map((h) => (
                            <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider"
                              style={{ color: 'var(--text-muted)' }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        <AnimatePresence>
                          {filteredSources.map((source, i) => {
                            const isInt = isInternetSource(source);
                            const status = STATUS_CONFIG[source.processing_status] || STATUS_CONFIG.failed;
                            const StatusIcon = status.icon;
                            const TypeIcon = TYPE_ICONS[source.file_type] || FileText;
                            const url = getSourceUrl(source);

                            return (
                              <motion.tr
                                key={source.id}
                                initial={{ opacity: 0, y: 4 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: i * 0.02 }}
                                className="border-b last:border-b-0 hover:bg-[var(--bg-hover)] transition-colors cursor-pointer group"
                                style={{ borderColor: 'var(--border)' }}
                                onClick={() => setSelectedSourceId(source.id)}
                              >
                                <td className="px-4 py-3">
                                  <div className="flex items-center gap-2.5">
                                    <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                                      style={{
                                        background: isInt ? 'rgba(6,182,212,0.12)' : 'var(--accent-muted)',
                                        color: isInt ? '#06b6d4' : 'var(--accent)',
                                      }}>
                                      <TypeIcon className="w-3.5 h-3.5" />
                                    </div>
                                    <div className="min-w-0">
                                      <span className="font-semibold text-xs transition-colors group-hover:text-[var(--accent)] truncate block max-w-[280px]"
                                        title={source.original_name}>
                                        {source.original_name}
                                      </span>
                                      {url && (
                                        <a
                                          href={url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          onClick={(e) => e.stopPropagation()}
                                          className="text-[10px] text-cyan-400 hover:underline flex items-center gap-1 truncate max-w-[240px]"
                                        >
                                          <span>{url.replace(/^https?:\/\//, '')}</span>
                                          <ExternalLink className="w-2.5 h-2.5 flex-shrink-0" />
                                        </a>
                                      )}
                                    </div>
                                  </div>
                                </td>

                                <td className="px-4 py-3">
                                  <div className="flex items-center gap-1.5">
                                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full uppercase"
                                      style={{
                                        background: isInt ? 'rgba(6,182,212,0.15)' : 'var(--bg-active)',
                                        color: isInt ? '#06b6d4' : 'var(--text-secondary)',
                                      }}>
                                      {isInt ? `🌐 ${source.file_type}` : `📁 ${source.file_type}`}
                                    </span>
                                  </div>
                                </td>

                                <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                                  {source.file_size ? formatBytes(source.file_size) : '—'}
                                </td>

                                <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-muted)' }}>
                                  {formatDate(source.upload_date)}
                                </td>

                                <td className="px-4 py-3">
                                  <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full w-fit"
                                    style={{ background: status.bg }}>
                                    <StatusIcon
                                      className={`w-3.5 h-3.5 ${(status as { spin?: boolean }).spin ? 'animate-spin' : ''}`}
                                      style={{ color: status.color }}
                                    />
                                    <span className="text-[11px] font-semibold" style={{ color: status.color }}>
                                      {status.label}
                                    </span>
                                  </div>
                                </td>

                                <td className="px-4 py-3 text-xs text-center font-mono" style={{ color: 'var(--text-secondary)' }}>
                                  {source.chunk_count > 0 ? source.chunk_count.toLocaleString() : '—'}
                                </td>

                                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                                  <div className="flex items-center gap-1">
                                    <button
                                      onClick={() => setSelectedSourceId(source.id)}
                                      className="p-1.5 rounded-lg hover:bg-[var(--bg-active)] transition-colors text-indigo-400"
                                      title="Inspect Chunks & Metadata">
                                      <Info className="w-3.5 h-3.5" />
                                    </button>
                                    <button
                                      onClick={() => handleReprocess(source.id)}
                                      className="p-1.5 rounded-lg hover:bg-[var(--bg-active)] transition-colors"
                                      style={{ color: 'var(--text-muted)' }} title="Reprocess">
                                      <RefreshCw className="w-3.5 h-3.5" />
                                    </button>
                                    <button
                                      onClick={() => handleDelete(source.id, source.original_name)}
                                      className="p-1.5 rounded-lg hover:bg-red-500/10 transition-colors"
                                      style={{ color: 'var(--text-muted)' }} title="Delete">
                                      <Trash2 className="w-3.5 h-3.5" />
                                    </button>
                                  </div>
                                </td>
                              </motion.tr>
                            );
                          })}
                        </AnimatePresence>
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Metadata Detail Modal */}
      <DocumentMetadataModal
        sourceId={selectedSourceId}
        isOpen={Boolean(selectedSourceId)}
        onClose={() => setSelectedSourceId(null)}
        onReprocess={(id) => {
          handleReprocess(id);
          setSelectedSourceId(null);
        }}
      />

      {/* ─── Duplicate File Warning Confirmation Modal ───────────────── */}
      <AnimatePresence>
        {showDuplicateModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={handleCancelDuplicateUpload}
              className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            />

            {/* Modal Card */}
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ duration: 0.18 }}
              className="relative w-full max-w-lg rounded-3xl border shadow-2xl p-6 overflow-hidden z-10"
              style={{
                background: 'var(--bg-elevated)',
                borderColor: 'var(--border)',
                color: 'var(--text-primary)',
              }}
            >
              {/* Header Icon + Title */}
              <div className="flex items-start gap-4 mb-4">
                <div
                  className="w-12 h-12 rounded-2xl flex items-center justify-center shrink-0"
                  style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b' }}
                >
                  <AlertCircle className="w-7 h-7" />
                </div>
                <div>
                  <h3 className="text-lg font-bold leading-tight" style={{ color: 'var(--text-primary)' }}>
                    A file with this name already exists. Do you want to upload it anyway?
                  </h3>
                  <p className="text-xs mt-1.5" style={{ color: 'var(--text-secondary)' }}>
                    If you choose Yes, the new file will be uploaded with an automatically generated unique name so the existing file is not overwritten.
                  </p>
                </div>
              </div>

              {/* Conflict Details List */}
              <div
                className="my-4 p-3.5 rounded-2xl border max-h-48 overflow-y-auto space-y-2 text-xs"
                style={{ background: 'var(--bg-base)', borderColor: 'var(--border)' }}
              >
                {duplicateConflicts.map((c, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between gap-3 p-2.5 rounded-xl border"
                    style={{ background: 'var(--bg-surface)', borderColor: 'var(--border)' }}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-medium truncate" style={{ color: 'var(--text-primary)' }} title={c.originalName}>
                        {c.originalName}
                      </p>
                      <p className="text-[11px] text-amber-400 mt-0.5 font-medium">
                        Already exists in repository
                      </p>
                    </div>
                    <div
                      className="flex items-center gap-1.5 text-[11px] shrink-0 font-medium px-2.5 py-1 rounded-lg border"
                      style={{ background: 'var(--accent-muted)', borderColor: 'var(--accent)', color: 'var(--accent)' }}
                    >
                      <span className="opacity-75">Saved as:</span>
                      <span className="font-semibold">{c.suggestedName}</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Action Buttons */}
              <div
                className="flex items-center justify-end gap-3 mt-6 pt-3 border-t"
                style={{ borderColor: 'var(--border)' }}
              >
                <button
                  type="button"
                  onClick={handleCancelDuplicateUpload}
                  className="px-5 py-2.5 rounded-xl text-xs font-semibold transition-all border hover:bg-[var(--bg-hover)]"
                  style={{
                    borderColor: 'var(--border)',
                    color: 'var(--text-secondary)',
                  }}
                >
                  No, Cancel
                </button>
                <button
                  type="button"
                  onClick={handleConfirmDuplicateUpload}
                  className="px-6 py-2.5 rounded-xl text-xs font-semibold text-white shadow-lg transition-all flex items-center gap-2 hover:opacity-90 active:scale-95"
                  style={{
                    background: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)',
                  }}
                >
                  <Check className="w-3.5 h-3.5" />
                  Yes, Upload Anyway
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
