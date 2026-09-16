'use client';
// src/components/chat/ChatInterface.tsx — Full Interactive Research Chat with Smart Search Context Workflow, File Uploads, & Sources Review

import { useState, useRef, useEffect, FormEvent, ChangeEvent, DragEvent } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send, Sparkles, Bot, User, Loader2, Globe, Database, Layers,
  PanelRightOpen, PanelRightClose, MessageSquare, BookOpen, Calendar, Share2,
  Paperclip, Image as ImageIcon, FileText, X, CheckCircle2, ArrowRight, Eye, Search
} from 'lucide-react';
import { useChatStore, ContextItem } from '@/store/chat';
import { useAuthStore } from '@/store/auth';
import SearchModeSelector from './SearchModeSelector';
import ContextPanel from './ContextPanel';
import InteractiveMessageItem from './InteractiveMessageItem';
import DocumentMetadataModal from '@/components/modals/DocumentMetadataModal';
import { toast } from 'sonner';

interface AttachedFile {
  id: string;
  file: File;
  name: string;
  size: number;
  previewUrl?: string;
  type: string;
}

interface ExtractedSearchInfo {
  searchQuery?: string;
  keywords?: string[];
  searchTerms?: string[];
  intent?: string;
}

type WorkflowState = 'idle' | 'extracting_query' | 'searching_sources' | 'reviewing_sources' | 'generating_answer';

function TypingIndicator({ statusText }: { statusText?: string }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3">
      <div
        className="w-9 h-9 rounded-2xl flex-shrink-0 flex items-center justify-center shadow-md"
        style={{ background: 'linear-gradient(135deg, #06b6d4 0%, #6366f1 100%)' }}
      >
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="px-5 py-3.5 rounded-3xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            {[0, 1, 2].map((i) => (
              <motion.div
                key={i}
                className="w-2 h-2 rounded-full"
                style={{ background: '#06b6d4' }}
                animate={{ y: [0, -4, 0] }}
                transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.15 }}
              />
            ))}
          </div>
          {statusText && (
            <span className="text-xs text-muted-foreground ml-2 font-medium">{statusText}</span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

export default function ChatInterface() {
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isContextOpen, setIsContextOpen] = useState(false);
  const [inspectSourceId, setInspectSourceId] = useState<string | null>(null);
  const [inspectTimestamp, setInspectTimestamp] = useState<number | undefined>(undefined);

  // Smart Search & Attachment states
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [workflowState, setWorkflowState] = useState<WorkflowState>('idle');
  const [workflowProgressText, setWorkflowProgressText] = useState('');
  const [extractedInfo, setExtractedInfo] = useState<ExtractedSearchInfo | null>(null);
  const [pendingPrompt, setPendingPrompt] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    activeChatId,
    setActiveChatId,
    messages,
    setMessages,
    searchMode,
    isSending,
    setSending,
    addMessage,
    activeContext,
    setActiveContext,
    isSmartSearchEnabled,
    setIsSmartSearchEnabled,
    chats,
    setChats,
  } = useChatStore();
  const { user } = useAuthStore();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping, workflowState]);

  // Open context drawer automatically if context items get added
  useEffect(() => {
    if (activeContext.length > 0 && !isContextOpen) {
      setIsContextOpen(true);
    }
  }, [activeContext.length]);

  // Load chat messages and restore saved context items when activeChatId changes
  useEffect(() => {
    if (!activeChatId) return;

    const fetchChatData = async () => {
      try {
        const res = await fetch(`/api/chats/${activeChatId}`);
        if (res.ok) {
          const data = await res.json();
          if (data.messages) {
            setMessages(data.messages);
          }
          if (data.contextItems && Array.isArray(data.contextItems) && data.contextItems.length > 0) {
            setActiveContext(data.contextItems);
          }
        }
      } catch {
        // ignore
      }
    };

    fetchChatData();
  }, [activeChatId, setMessages, setActiveContext]);

  // File Upload Handlers
  const handleFileSelect = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(Array.from(e.target.files));
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const addFiles = (files: File[]) => {
    const newItems: AttachedFile[] = files.map((file) => {
      const isImg = file.type.startsWith('image/');
      return {
        id: `att-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        file,
        name: file.name,
        size: file.size,
        previewUrl: isImg ? URL.createObjectURL(file) : undefined,
        type: file.type || 'application/octet-stream',
      };
    });
    setAttachedFiles((prev) => [...prev, ...newItems]);
    toast.success(`Attached ${files.length} file${files.length > 1 ? 's' : ''}`);
  };

  const removeAttachedFile = (id: string) => {
    setAttachedFiles((prev) => {
      const item = prev.find((f) => f.id === id);
      if (item?.previewUrl) URL.revokeObjectURL(item.previewUrl);
      return prev.filter((f) => f.id !== id);
    });
  };

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  };

  // 1. SMART SEARCH WORKFLOW EXECUTION
  const handleSmartSearchFlow = async (textPrompt: string) => {
    if (!textPrompt.trim() && attachedFiles.length === 0) {
      toast.error('Please enter a search prompt or attach a reference document/image');
      return;
    }

    const currentPrompt = textPrompt.trim();
    setPendingPrompt(currentPrompt);
    setWorkflowState('extracting_query');
    setWorkflowProgressText('Extracting search query, keywords & search terms with LLM...');

    try {
      // Step A: Send input to LLM to generate clean search query, keywords, and search terms
      const queryFormData = new FormData();
      if (currentPrompt) queryFormData.append('query', currentPrompt);
      if (attachedFiles.length > 0) {
        queryFormData.append('file', attachedFiles[0].file);
        if (attachedFiles[0].file.type.startsWith('image/')) {
          queryFormData.append('image', attachedFiles[0].file);
        }
      }

      const extractRes = await fetch('/api/search/extract-query', {
        method: 'POST',
        body: queryFormData,
      });

      if (!extractRes.ok) {
        throw new Error('Failed to generate search query from LLM');
      }

      const extractedData: ExtractedSearchInfo & { fileSnippet?: string } = await extractRes.json();
      setExtractedInfo(extractedData);

      // Step B: Run document search logic matching Smart Finder with relativeThreshold = 0.20 (20%)
      setWorkflowState('searching_sources');
      setWorkflowProgressText(
        `Searching local repository & live internet sources (relative similarity threshold 20%)...`
      );

      const smartFormData = new FormData();
      smartFormData.append('query', extractedData.searchQuery || currentPrompt);
      smartFormData.append('relativeThreshold', '0.20'); // 20% relative threshold
      smartFormData.append('enableInternet', 'true'); // Show both local repository and internet sources
      if (attachedFiles.length > 0) {
        smartFormData.append('file', attachedFiles[0].file);
        if (attachedFiles[0].file.type.startsWith('image/')) {
          smartFormData.append('image', attachedFiles[0].file);
        }
      }

      const searchRes = await fetch('/api/search/smart', {
        method: 'POST',
        body: smartFormData,
      });

      if (!searchRes.ok) {
        throw new Error('Smart Finder document search failed');
      }

      const searchData = await searchRes.json();
      const localDocs = searchData.local?.documents || [];
      const localVideos = searchData.local?.videos || [];
      const localImages = searchData.local?.images || [];
      const internetWeb = searchData.internet?.web || [];
      const internetNews = searchData.internet?.news || [];
      const internetPapers = searchData.internet?.papers || [];
      const internetVideos = searchData.internet?.videos || [];
      const internetImages = searchData.internet?.images || [];

      // Map discovered items into ContextItem[]
      const discoveredItems: ContextItem[] = [];

      // 1. Prioritize user-attached document/image as the primary context item
      if (attachedFiles.length > 0) {
        attachedFiles.forEach((att, idx) => {
          const isImg = att.file.type.startsWith('image/');
          discoveredItems.push({
            id: `attached-${att.id || idx}`,
            type: isImg ? 'image' : 'document',
            title: `[Attached ${isImg ? 'Image' : 'Document'}] ${att.name}`,
            snippet: extractedData.fileSnippet || `User attached ${isImg ? 'image' : 'document'}: ${att.name} (${(att.size / 1024).toFixed(1)} KB)`,
            relevanceScore: 1.0,
            metadata: {
              isUserAttachment: true,
              fileName: att.name,
              fileSize: att.size,
              fileType: att.type,
              previewUrl: att.previewUrl,
              extractedSnippet: extractedData.fileSnippet,
            },
          });
        });
      }

      // 2. Local Knowledge Repository Sources
      localDocs.forEach((d: any) => {
        discoveredItems.push({
          id: d.id,
          type: 'document',
          title: d.title || 'Document',
          snippet: d.snippet || '',
          relevanceScore: d.relevanceScore,
          metadata: {
            sourceId: d.sourceId,
            fileType: d.fileType,
            page: d.page,
            section: d.section,
            filePath: d.filePath,
            ...d.metadata,
          },
        });
      });

      localVideos.forEach((v: any) => {
        discoveredItems.push({
          id: v.id,
          type: 'video',
          title: v.title || 'Video',
          snippet: v.snippet || '',
          relevanceScore: v.relevanceScore,
          metadata: {
            sourceId: v.sourceId,
            timestamp: v.startTime,
            url: v.url,
            ...v.metadata,
          },
        });
      });

      localImages.forEach((img: any) => {
        discoveredItems.push({
          id: img.id,
          type: 'image',
          title: img.title || 'Image',
          snippet: img.snippet || '',
          relevanceScore: img.relevanceScore,
          metadata: {
            sourceId: img.sourceId,
            ...img.metadata,
          },
        });
      });

      // 3. Live Internet Sources (Videos, Web, News, Papers, Images)
      internetVideos.forEach((v: any) => {
        discoveredItems.push({
          id: v.id || `yt-${Math.random().toString(36).slice(2, 9)}`,
          type: 'video',
          title: v.title || 'YouTube Video',
          snippet: v.snippet || '',
          relevanceScore: v.relevanceScore || 0.90,
          metadata: {
            url: v.url,
            thumbnail: v.thumbnail,
            author: v.author,
            domain: v.domain || 'youtube.com',
            publishedDate: v.publishedDate,
            isInternet: true,
          },
        });
      });

      internetWeb.forEach((w: any) => {
        discoveredItems.push({
          id: w.id || `web-${Math.random().toString(36).slice(2, 9)}`,
          type: 'web',
          title: w.title || 'Web Page',
          snippet: w.snippet || '',
          relevanceScore: w.relevanceScore || 0.92,
          metadata: {
            url: w.url,
            domain: w.domain,
            publishedDate: w.publishedDate,
            thumbnail: w.thumbnail,
            isInternet: true,
          },
        });
      });

      internetNews.forEach((n: any) => {
        discoveredItems.push({
          id: n.id || `news-${Math.random().toString(36).slice(2, 9)}`,
          type: 'web',
          title: n.title || 'News Article',
          snippet: n.snippet || '',
          relevanceScore: n.relevanceScore || 0.89,
          metadata: {
            url: n.url,
            domain: n.domain,
            author: n.author,
            publishedDate: n.publishedDate,
            isInternet: true,
          },
        });
      });

      internetPapers.forEach((p: any) => {
        discoveredItems.push({
          id: p.id || `paper-${Math.random().toString(36).slice(2, 9)}`,
          type: 'document',
          title: p.title || 'Academic Paper',
          snippet: p.snippet || '',
          relevanceScore: p.relevanceScore || 0.90,
          metadata: {
            url: p.url,
            domain: p.domain,
            author: p.author,
            publishedDate: p.publishedDate,
            isInternet: true,
          },
        });
      });

      internetImages.forEach((img: any) => {
        discoveredItems.push({
          id: img.id || `img-${Math.random().toString(36).slice(2, 9)}`,
          type: 'image',
          title: img.title || 'Internet Image',
          snippet: img.snippet || '',
          relevanceScore: img.relevanceScore || 0.88,
          metadata: {
            url: img.url,
            thumbnail: img.thumbnail,
            domain: img.domain,
            isInternet: true,
          },
        });
      });

      // Populate right sidebar with discovered sources (replacing previous source set when re-run)
      setActiveContext(discoveredItems);
      setIsContextOpen(true);
      setWorkflowState('reviewing_sources');
      setWorkflowProgressText(
        `Discovered ${discoveredItems.length} matching sources (both local & internet). Review and remove unwanted items, then click Generate Answer.`
      );

      if (discoveredItems.length > 0) {
        toast.success(`Found ${discoveredItems.length} sources matching 20% relative similarity.`);
      } else {
        toast.info('No documents matched the 20% threshold. You can still generate an answer or refine your prompt.');
      }
    } catch (err: any) {
      toast.error(err.message || 'Smart search failed. Please try again.');
      setWorkflowState('idle');
    }
  };

  // 2. GENERATE ANSWER USING CONFIRMED CONTEXT
  const handleGenerateAnswer = async () => {
    const promptToUse =
      pendingPrompt ||
      input.trim() ||
      extractedInfo?.searchQuery ||
      (activeContext.length > 0
        ? 'Synthesize the provided research context and summarize key findings.'
        : '');
    if (!promptToUse && activeContext.length === 0) {
      toast.error('Please enter a question or provide context to generate an answer.');
      return;
    }

    let chatId = activeChatId;

    // Create a new chat session if none exists
    if (!chatId) {
      try {
        const res = await fetch('/api/chats', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: (promptToUse || extractedInfo?.searchQuery || 'Smart Search Chat').slice(0, 60),
            searchMode,
          }),
        });
        if (!res.ok) throw new Error('Failed to create chat session');
        const data = await res.json();
        chatId = data.chat.id;
        setActiveChatId(chatId!);
        setChats([data.chat, ...chats]);
      } catch {
        toast.error('Failed to initialize chat');
        return;
      }
    }

    setWorkflowState('generating_answer');
    setSending(true);
    setIsTyping(true);

    // Persist confirmed context on the backend
    try {
      await fetch(`/api/chats/${chatId}/context`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contextItems: activeContext }),
      });
    } catch {
      // silent fallback
    }

    // Optimistic user message in UI
    const tempId = `temp-${Date.now()}`;
    addMessage({
      id: tempId,
      role: 'user',
      content: promptToUse,
      createdAt: new Date().toISOString(),
    });

    try {
      const res = await fetch(`/api/chats/${chatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: promptToUse,
          contextItems: activeContext,
        }),
      });

      if (!res.ok) {
        let errDetail = 'Failed to generate response';
        try {
          const errData = await res.json();
          if (errData?.detail) errDetail = errData.detail;
        } catch {}
        throw new Error(errDetail);
      }

      const data = await res.json();
      const filtered = messages.filter((m) => m.id !== tempId);
      setMessages([
        ...filtered,
        { id: data.userMessage.id, role: 'user', content: data.userMessage.content, createdAt: new Date().toISOString() },
        { id: data.assistantMessage.id, role: 'assistant', content: data.assistantMessage.content, createdAt: new Date().toISOString() },
      ]);

      // Keep confirmed sources as active chat context for subsequent messages!
      // Turn off Smart Search toggle so subsequent messages continue seamlessly without re-running search
      setIsSmartSearchEnabled(false);
      setInput('');
      setPendingPrompt('');
      setAttachedFiles([]);
      setWorkflowState('idle');
      toast.success('Answer generated! Confirmed sources remain active for this chat session.');
    } catch (err: any) {
      toast.error(err.message || 'Generation failed.');
      setWorkflowState('reviewing_sources'); // allow re-clicking generate
    } finally {
      setSending(false);
      setIsTyping(false);
    }
  };

  // 3. REGULAR MESSAGE SUBMIT (WHEN SMART SEARCH IS DISABLED)
  const handleSubmitWithText = async (textToSend: string) => {
    if (!textToSend.trim() && attachedFiles.length === 0) return;
    if (isSending) return;

    // If Smart Search is enabled or files are attached, route through the Smart Search workflow!
    if (isSmartSearchEnabled || attachedFiles.length > 0) {
      handleSmartSearchFlow(textToSend);
      return;
    }

    let chatId = activeChatId;

    // Create a new chat if none is active
    if (!chatId) {
      try {
        const res = await fetch('/api/chats', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: textToSend.trim().slice(0, 60), searchMode }),
        });
        if (!res.ok) {
          toast.error('Failed to create chat');
          return;
        }
        const data = await res.json();
        chatId = data.chat.id;
        setActiveChatId(chatId!);
        setChats([data.chat, ...chats]);
      } catch {
        toast.error('Failed to start chat');
        return;
      }
    }

    const userMsg = textToSend.trim();
    setInput('');
    setSending(true);
    setIsTyping(true);

    // Optimistic user message
    const tempId = `temp-${Date.now()}`;
    addMessage({ id: tempId, role: 'user', content: userMsg, createdAt: new Date().toISOString() });

    try {
      const res = await fetch(`/api/chats/${chatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg, contextItems: activeContext }),
      });

      if (!res.ok) {
        toast.error('Failed to send message');
        return;
      }

      const data = await res.json();
      const filtered = messages.filter((m) => m.id !== tempId);
      setMessages([
        ...filtered,
        { id: data.userMessage.id, role: 'user', content: data.userMessage.content, createdAt: new Date().toISOString() },
        { id: data.assistantMessage.id, role: 'assistant', content: data.assistantMessage.content, createdAt: new Date().toISOString() },
      ]);
    } catch {
      toast.error('Message failed. Please check connection.');
    } finally {
      setSending(false);
      setIsTyping(false);
    }
  };

  const handleSubmit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (isSmartSearchEnabled || attachedFiles.length > 0) {
      handleSmartSearchFlow(input);
    } else {
      handleSubmitWithText(input);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const hasMessages = messages.length > 0;

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* Main chat column */}
      <div className="flex-1 flex flex-col min-w-0 h-full">
        {/* Empty state */}
        {!hasMessages && workflowState === 'idle' && (
          <div className="flex-1 flex flex-col items-center justify-center px-6 sm:px-8 text-center overflow-y-auto py-8">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ type: 'spring', bounce: 0.2 }}
              className="max-w-2xl mx-auto space-y-6"
            >
              {/* Badge & Glow Icon */}
              <div className="flex flex-col items-center gap-3">
                <div
                  className="w-16 h-16 rounded-3xl flex items-center justify-center shadow-2xl relative group"
                  style={{
                    background: 'linear-gradient(135deg, #06b6d4 0%, #6366f1 50%, #8b5cf6 100%)',
                    boxShadow: '0 0 50px rgba(6,182,212,0.35)',
                  }}
                >
                  <Sparkles className="w-8 h-8 text-white animate-pulse" />
                </div>

                <div
                  className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold"
                  style={{
                    background: 'rgba(6,182,212,0.12)',
                    color: '#06b6d4',
                    border: '1px solid rgba(6,182,212,0.25)',
                  }}
                >
                  <Globe className="w-3.5 h-3.5" />
                  <span>Multimodal Knowledge & Smart Search</span>
                </div>
              </div>

              {/* Title & Description */}
              <div className="space-y-3">
                <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight" style={{ color: 'var(--text-primary)' }}>
                  Interactive Research Scout
                </h2>
                <p className="text-sm sm:text-base leading-relaxed max-w-xl mx-auto font-normal" style={{ color: 'var(--text-secondary)' }}>
                  Ask questions, attach reference files, or enable <strong>Smart Search</strong> to discover matching knowledge base documents, verify sources, and generate grounded answers.
                </p>
              </div>

              {/* Quick suggestions */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-w-xl mx-auto pt-2 text-left">
                {[
                  { icon: BookOpen, text: 'Explore academic research and latest technical findings on AI architectures', smart: true },
                  { icon: Calendar, text: 'Extract chronological timelines of key policy milestones and events', smart: true },
                  { icon: Share2, text: 'Map entity knowledge graphs across connected organizations and people', smart: false },
                  { icon: Globe, text: 'Synthesize cross-source perspectives and compare findings across media', smart: false },
                ].map((s) => {
                  const Icon = s.icon;
                  return (
                    <motion.button
                      key={s.text}
                      whileHover={{ scale: 1.015, y: -2 }}
                      whileTap={{ scale: 0.985 }}
                      onClick={() => {
                        setInput(s.text);
                        if (s.smart) setIsSmartSearchEnabled(true);
                        handleSubmitWithText(s.text);
                      }}
                      className="flex items-start gap-3 p-3.5 rounded-2xl text-left text-xs transition-all shadow-sm group hover:border-cyan-500/40"
                      style={{
                        background: 'var(--bg-elevated)',
                        border: '1px solid var(--border)',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      <div className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400 flex-shrink-0 group-hover:bg-cyan-500/20 transition-colors">
                        <Icon className="w-4 h-4" />
                      </div>
                      <span className="leading-relaxed font-medium group-hover:text-[var(--text-primary)] transition-colors">{s.text}</span>
                    </motion.button>
                  );
                })}
              </div>
            </motion.div>
          </div>
        )}

        {/* Messages feed */}
        {(hasMessages || workflowState !== 'idle') && (
          <div className="flex-1 overflow-y-auto px-4 sm:px-8 py-6 space-y-6">
            {messages.map((msg) => (
              <InteractiveMessageItem
                key={msg.id}
                msg={msg}
                onSendFollowup={(q) => handleSubmitWithText(q)}
                onOpenSourceModal={(sourceId, timestamp) => {
                  setInspectSourceId(sourceId);
                  setInspectTimestamp(timestamp);
                }}
              />
            ))}

            {/* Smart Search Workflow Stepper & Verification Card */}
            {workflowState !== 'idle' && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="p-5 rounded-3xl border shadow-xl relative overflow-hidden"
                style={{
                  background: 'linear-gradient(135deg, rgba(6,182,212,0.07) 0%, rgba(99,102,241,0.07) 100%)',
                  borderColor: 'rgba(6,182,212,0.3)',
                }}
              >
                <div className="flex items-start justify-between gap-4 flex-wrap sm:flex-nowrap">
                  <div className="flex items-start gap-3">
                    <div className="p-2.5 rounded-2xl bg-cyan-500/20 text-cyan-400 flex-shrink-0 mt-0.5 shadow-inner">
                      {workflowState === 'reviewing_sources' ? (
                        <CheckCircle2 className="w-5 h-5 text-cyan-400" />
                      ) : (
                        <Loader2 className="w-5 h-5 animate-spin text-cyan-400" />
                      )}
                    </div>
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-1.5">
                          <Sparkles className="w-3.5 h-3.5" />
                          Smart Search Workflow
                        </h4>
                        <span className="text-[10px] px-2.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 font-semibold border border-cyan-500/30">
                          {workflowState === 'extracting_query' && 'Phase 1: Query & Keyword Extraction'}
                          {workflowState === 'searching_sources' && 'Phase 2: Smart Finder Retrieval (20% threshold)'}
                          {workflowState === 'reviewing_sources' && 'Phase 3: Review Matched Sources'}
                          {workflowState === 'generating_answer' && 'Phase 4: Generating Grounded Answer'}
                        </span>
                      </div>

                      <p className="text-sm font-medium text-[var(--text-primary)]">
                        {workflowProgressText}
                      </p>

                      {extractedInfo?.searchQuery && (
                        <div className="flex items-center gap-2 pt-1 flex-wrap text-xs">
                          <span className="text-muted-foreground font-medium">Clean Query:</span>
                          <span className="font-semibold text-cyan-300 bg-[var(--bg-base)] px-2 py-0.5 rounded-lg border border-cyan-500/30">
                            &ldquo;{extractedInfo.searchQuery}&rdquo;
                          </span>
                          {extractedInfo.keywords && extractedInfo.keywords.length > 0 && (
                            <span className="text-[11px] text-muted-foreground">
                              Keywords: {extractedInfo.keywords.slice(0, 4).join(', ')}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  {workflowState === 'reviewing_sources' && (
                    <div className="flex items-center gap-2 flex-shrink-0 w-full sm:w-auto justify-end pt-2 sm:pt-0">
                      <button
                        onClick={() => setIsContextOpen(true)}
                        className="px-3.5 py-2 rounded-2xl text-xs font-semibold bg-[var(--bg-elevated)] border border-[var(--border)] hover:bg-[var(--bg-hover)] text-zinc-300 transition-all shadow-sm"
                      >
                        Inspect Sources ({activeContext.length})
                      </button>
                      <motion.button
                        whileHover={{ scale: 1.03 }}
                        whileTap={{ scale: 0.97 }}
                        onClick={handleGenerateAnswer}
                        disabled={isSending || activeContext.length === 0}
                        className="px-4 py-2 rounded-2xl text-xs font-bold flex items-center gap-2 text-white shadow-lg transition-all disabled:opacity-50"
                        style={{
                          background: 'linear-gradient(135deg, #06b6d4 0%, #6366f1 100%)',
                          boxShadow: '0 4px 14px rgba(6,182,212,0.35)',
                        }}
                      >
                        <Sparkles className="w-4 h-4" />
                        <span>Generate Answer</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </motion.button>
                    </div>
                  )}
                </div>
              </motion.div>
            )}

            {isTyping && workflowState !== 'reviewing_sources' && (
              <TypingIndicator
                statusText={
                  workflowState === 'generating_answer'
                    ? 'Synthesizing response from confirmed research context...'
                    : undefined
                }
              />
            )}
            <div ref={messagesEndRef} />
          </div>
        )}

        {/* Active context pill banner */}
        {activeContext.length > 0 && workflowState !== 'reviewing_sources' && (
          <div className="px-4 sm:px-8 pb-2 flex items-center justify-between">
            <button
              onClick={() => setIsContextOpen(!isContextOpen)}
              className="flex items-center gap-2 text-xs px-3.5 py-1.5 rounded-xl transition-all hover:opacity-90 shadow-sm"
              style={{
                background: 'rgba(6,182,212,0.12)',
                border: '1px solid rgba(6,182,212,0.25)',
                color: '#06b6d4',
              }}
            >
              <Database className="w-3.5 h-3.5" />
              <span className="font-bold">{activeContext.length} Active Source{activeContext.length > 1 ? 's' : ''} in Context</span>
              <span style={{ color: 'var(--text-muted)' }}>— active across all messages in session</span>
            </button>
          </div>
        )}

        {/* Input area */}
        <div className="flex-shrink-0 px-4 sm:px-8 pb-4">
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className={`rounded-3xl overflow-hidden shadow-2xl transition-all ${
              isDragging ? 'ring-2 ring-cyan-400 bg-cyan-950/20' : ''
            }`}
            style={{
              background: 'var(--bg-elevated)',
              border: isSmartSearchEnabled
                ? '1px solid rgba(6,182,212,0.4)'
                : '1px solid var(--border)',
              boxShadow: isSmartSearchEnabled
                ? '0 12px 40px rgba(0,0,0,0.4), 0 0 20px rgba(6,182,212,0.15)'
                : '0 12px 40px rgba(0,0,0,0.4)',
            }}
          >
            {/* Top Toolbar Row: Search Mode + Smart Search Toggle */}
            <div className="flex items-center justify-between px-4 py-2.5 flex-wrap gap-2" style={{ borderBottom: '1px solid var(--border)' }}>
              <div className="flex items-center gap-2.5 flex-wrap">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wider flex-shrink-0 text-cyan-400">
                    Mode
                  </span>
                  <SearchModeSelector />
                </div>

                <div className="h-4 w-[1px] bg-[var(--border)] mx-1" />

                {/* Smart Search Checkbox / Toggle */}
                <button
                  type="button"
                  onClick={() => setIsSmartSearchEnabled(!isSmartSearchEnabled)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-xl text-xs font-semibold transition-all ${
                    isSmartSearchEnabled
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 shadow-[0_0_14px_rgba(6,182,212,0.3)]'
                      : 'bg-[var(--bg-base)] text-muted-foreground border border-[var(--border)] hover:text-[var(--text-primary)] hover:border-cyan-500/30'
                  }`}
                  title="Enable Smart Search: Uses LLM query formulation and Smart Finder document discovery before answering"
                >
                  <Sparkles className={`w-3.5 h-3.5 ${isSmartSearchEnabled ? 'text-cyan-400 animate-pulse' : 'text-muted-foreground'}`} />
                  <span>Smart Search</span>
                  {isSmartSearchEnabled ? (
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
                  ) : null}
                </button>
              </div>

              {/* Sources Drawer Toggle */}
              {activeContext.length > 0 && (
                <button
                  onClick={() => setIsContextOpen(!isContextOpen)}
                  className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-xl transition-all hover:bg-[var(--bg-hover)] border border-cyan-500/20 bg-cyan-500/10 text-cyan-400"
                  title="Toggle sources drawer"
                >
                  <Database className="w-3.5 h-3.5" />
                  <span className="text-[11px] font-bold">{activeContext.length} Sources</span>
                </button>
              )}
            </div>

            {/* Attached Files Preview Chips */}
            {attachedFiles.length > 0 && (
              <div className="px-4 pt-2.5 flex flex-wrap gap-2">
                {attachedFiles.map((f) => (
                  <div
                    key={f.id}
                    className="flex items-center gap-2 pl-2.5 pr-2 py-1 rounded-xl text-xs bg-[var(--bg-base)] border border-cyan-500/30 text-[var(--text-primary)] shadow-sm"
                  >
                    {f.previewUrl ? (
                      <img src={f.previewUrl} alt={f.name} className="w-5 h-5 rounded object-cover" />
                    ) : (
                      <FileText className="w-4 h-4 text-cyan-400" />
                    )}
                    <span className="max-w-[150px] truncate font-medium">{f.name}</span>
                    <span className="text-[10px] text-muted-foreground font-mono">
                      {(f.size / 1024).toFixed(0)} KB
                    </span>
                    <button
                      type="button"
                      onClick={() => removeAttachedFile(f.id)}
                      className="p-0.5 rounded-full hover:bg-red-500/20 hover:text-red-400 text-muted-foreground transition-colors ml-1"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Text input row */}
            <div className="flex items-end gap-2 px-4 py-3">
              {/* File / Image Attachment Button */}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/*,.pdf,.docx,.doc,.txt,.md"
                onChange={handleFileSelect}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="w-9 h-9 rounded-xl flex items-center justify-center text-muted-foreground hover:text-cyan-400 hover:bg-[var(--bg-hover)] transition-all flex-shrink-0"
                title="Attach reference image or document (.pdf, .txt, .docx, images)"
              >
                <Paperclip className="w-4 h-4" />
              </button>

              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isSending || workflowState === 'extracting_query' || workflowState === 'searching_sources'}
                placeholder={
                  isSmartSearchEnabled
                    ? 'Enter research question or topic (Smart Search will discover sources first)...'
                    : 'Ask follow-up questions, request timelines, compare evidence, or analyze sources...'
                }
                rows={1}
                className="flex-1 bg-transparent text-sm outline-none resize-none leading-relaxed placeholder:text-muted-foreground/50"
                style={{
                  color: 'var(--text-primary)',
                  maxHeight: '120px',
                  overflowY: 'auto',
                }}
                onInput={(e) => {
                  const t = e.target as HTMLTextAreaElement;
                  t.style.height = 'auto';
                  t.style.height = Math.min(t.scrollHeight, 120) + 'px';
                }}
              />

              {/* Submit Button */}
              <motion.button
                onClick={() => handleSubmit()}
                disabled={(!input.trim() && attachedFiles.length === 0) || isSending}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                className="h-10 px-3.5 rounded-2xl flex items-center justify-center gap-1.5 flex-shrink-0 shadow-md transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                style={{
                  background:
                    input.trim() || attachedFiles.length > 0
                      ? isSmartSearchEnabled
                        ? 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)'
                        : 'linear-gradient(135deg, #06b6d4 0%, #6366f1 100%)'
                      : 'var(--bg-active)',
                  boxShadow:
                    input.trim() || attachedFiles.length > 0
                      ? '0 4px 14px rgba(6,182,212,0.35)'
                      : 'none',
                }}
                title={isSmartSearchEnabled ? 'Run Smart Search' : 'Send message'}
              >
                {isSending || workflowState === 'extracting_query' || workflowState === 'searching_sources' ? (
                  <Loader2 className="w-4 h-4 text-white animate-spin" />
                ) : isSmartSearchEnabled ? (
                  <>
                    <Sparkles className="w-4 h-4 text-white" />
                    <span className="text-xs font-bold text-white hidden sm:inline">Search</span>
                  </>
                ) : (
                  <Send
                    className="w-4 h-4"
                    style={{
                      color: input.trim() || attachedFiles.length > 0 ? 'white' : 'var(--text-muted)',
                    }}
                  />
                )}
              </motion.button>
            </div>
          </div>
        </div>
      </div>

      {/* Sources Sidebar Drawer */}
      <ContextPanel
        isOpen={isContextOpen}
        onToggle={() => setIsContextOpen(!isContextOpen)}
        isReviewMode={workflowState === 'reviewing_sources'}
        extractedInfo={extractedInfo}
        onGenerateAnswer={handleGenerateAnswer}
        isGeneratingAnswer={workflowState === 'generating_answer'}
      />

      {/* Metadata Detail Modal */}
      <DocumentMetadataModal
        sourceId={inspectSourceId}
        initialTimestamp={inspectTimestamp}
        isOpen={Boolean(inspectSourceId)}
        onClose={() => {
          setInspectSourceId(null);
          setInspectTimestamp(undefined);
        }}
      />
    </div>
  );
}

