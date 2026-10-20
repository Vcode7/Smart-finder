'use client';
// src/components/chat/ChatInterface.tsx — Full Interactive Research Chat with Smart Search Context Workflow, File Uploads, & Sources Review

import { useState, useRef, useEffect, FormEvent, ChangeEvent, DragEvent } from 'react';
import { motion } from 'framer-motion';
import {
  Send, Sparkles, Bot, Loader2, Globe, Database, BookOpen, Calendar, Share2,
  Paperclip, FileText, X, CheckCircle2, ArrowRight,
} from 'lucide-react';
import { useChatStore, ContextItem, Citation, ChatMessage } from '@/store/chat';
import SearchModeSelector from './SearchModeSelector';
import ContextPanel from './ContextPanel';
import InteractiveMessageItem from './InteractiveMessageItem';
import DocumentMetadataModal from '@/components/modals/DocumentMetadataModal';
import { toast } from 'sonner';
import { apiErrorMessage, readJson } from '@/lib/utils/api';

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

/** One result of /api/search/smart (local or internet). */
interface SearchResultItem {
  id?: string;
  sourceId?: string;
  title?: string;
  snippet?: string;
  relevanceScore?: number;
  fileType?: string;
  page?: number;
  section?: string;
  filePath?: string;
  startTime?: number;
  url?: string;
  thumbnail?: string;
  author?: string;
  domain?: string;
  publishedDate?: string;
  metadata?: Record<string, unknown>;
}

interface SentMessages {
  userMessage: { id: string; content: string };
  assistantMessage: { id: string; content: string; citations?: Citation[] };
}

const errorText = (err: unknown, fallback: string) => (err instanceof Error && err.message ? err.message : fallback);

let tempSeq = 0;
/** Id of an optimistic message until the server returns the stored one. */
const newTempId = () => `temp-${Date.now()}-${++tempSeq}`;

/** The confirmed user message and its answer, as the backend stored them. */
function toMessages(data: SentMessages): ChatMessage[] {
  const now = new Date().toISOString();
  return [
    { id: data.userMessage.id, role: 'user', content: data.userMessage.content, createdAt: now },
    {
      id: data.assistantMessage.id, role: 'assistant', content: data.assistantMessage.content,
      citations: data.assistantMessage.citations || [], createdAt: now,
    },
  ];
}

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
  const attachedFilesRef = useRef<AttachedFile[]>([]);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    activeChatId,
    setActiveChatId,
    messages,
    setMessages,
    searchMode,
    isSending,
    sendingChatId,
    setSending,
    addMessage,
    activeContext,
    setActiveContext,
    isSmartSearchEnabled,
    setIsSmartSearchEnabled,
    isLoading: isLoadingChat,
    setLoading: setLoadingChat,
    createChat,
    refreshChats,
  } = useChatStore();
  // Waiting for an answer in the chat on screen (another chat may still be answering)
  const isTyping = isSending && sendingChatId === activeChatId;

  const [isContextOpen, setIsContextOpen] = useState(activeContext.length > 0);
  // Open the sources drawer whenever sources are added (here, from search or a source modal)
  const [contextCount, setContextCount] = useState(activeContext.length);
  if (activeContext.length !== contextCount) {
    setContextCount(activeContext.length);
    if (activeContext.length > contextCount) setIsContextOpen(true);
  }

  // Opening another chat (sidebar, palette, new chat) drops this one's unfinished Smart
  // Search workflow; chats this component creates itself keep it running.
  const [shownChatId, setShownChatId] = useState(activeChatId);
  const [ownChatId, setOwnChatId] = useState<string | null>(null);
  if (activeChatId !== shownChatId) {
    setShownChatId(activeChatId);
    if (activeChatId !== ownChatId) {
      setWorkflowState('idle');
      setWorkflowProgressText('');
      setExtractedInfo(null);
      setPendingPrompt('');
    }
  }

  useEffect(() => {
    attachedFilesRef.current = attachedFiles;
  }, [attachedFiles]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping, workflowState]);

  // Release attachment preview object URLs on unmount
  useEffect(() => () => {
    attachedFilesRef.current.forEach((f) => { if (f.previewUrl) URL.revokeObjectURL(f.previewUrl); });
  }, []);

  const clearAttachments = () => {
    attachedFilesRef.current.forEach((f) => { if (f.previewUrl) URL.revokeObjectURL(f.previewUrl); });
    setAttachedFiles([]);
  };

  // Remove an optimistic message (failed send); reads fresh store state, not a stale closure
  const dropMessage = (id: string) => {
    setMessages(useChatStore.getState().messages.filter((m) => m.id !== id));
  };

  // Load the messages and saved sources of the chat being opened
  useEffect(() => {
    if (!activeChatId) return;
    let current = true;
    setLoadingChat(true);
    fetch(`/api/chats/${activeChatId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        // Another chat was opened meanwhile, or the request failed
        if (!current || !data) return;
        // While this chat's message is being answered, its optimistic list is newer
        if (Array.isArray(data.messages) && useChatStore.getState().sendingChatId !== activeChatId) {
          setMessages(data.messages);
        }
        if (Array.isArray(data.contextItems) && data.contextItems.length > 0) {
          setActiveContext(data.contextItems);
        }
      })
      .catch(() => { /* keep what is shown; the chat reloads when reopened */ })
      .finally(() => { if (current) setLoadingChat(false); });
    return () => { current = false; };
  }, [activeChatId, setMessages, setActiveContext, setLoadingChat]);

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
      const extractFor = async (att?: AttachedFile) => {
        const fd = new FormData();
        if (currentPrompt) fd.append('query', currentPrompt);
        if (att) fd.append('file', att.file);
        const res = await fetch('/api/search/extract-query', { method: 'POST', body: fd });
        if (!res.ok) throw new Error('Failed to generate search query from LLM');
        return (await res.json()) as ExtractedSearchInfo & { fileSnippet?: string };
      };

      // The first attachment drives the search; every attachment gets its own extracted snippet
      const [extractedData, ...extraExtracts] = await Promise.all(
        attachedFiles.length > 0 ? attachedFiles.map((att) => extractFor(att)) : [extractFor()]
      );
      setExtractedInfo(extractedData);
      const snippetsByAttachment = [extractedData, ...extraExtracts].map((d) => d?.fileSnippet);

      // Step B: Run document search logic matching Smart Finder with relativeThreshold = 0.20 (20%)
      setWorkflowState('searching_sources');
      setWorkflowProgressText(
        `Searching ${searchMode === 'local' ? 'your libraries' : 'your libraries & the internet'} (relative similarity threshold 20%)...`
      );

      const smartFormData = new FormData();
      const hasImageOnly = attachedFiles.length > 0 && attachedFiles[0].file.type.startsWith('image/') && !currentPrompt;
      const baseQuery = hasImageOnly ? (extractedData.keywords?.length ? extractedData.keywords.join(' ') : '') : (extractedData.searchQuery || currentPrompt);
      // Additional attachments contribute their keywords to the query
      const extraKeywords = extraExtracts.flatMap((d) => d?.keywords || []).slice(0, 6);
      const targetQuery = [baseQuery, ...extraKeywords].filter(Boolean).join(' ').trim();
      if (targetQuery) {
        smartFormData.append('query', targetQuery);
      }
      smartFormData.append('relativeThreshold', '0.20'); // 20% relative threshold
      smartFormData.append('enableInternet', searchMode === 'local' ? 'false' : 'true');
      if (attachedFiles.length > 0) {
        smartFormData.append('file', attachedFiles[0].file);
      }

      const searchRes = await fetch('/api/search/smart', {
        method: 'POST',
        body: smartFormData,
      });

      if (!searchRes.ok) {
        throw new Error('Smart Finder document search failed');
      }

      const searchData = await searchRes.json();
      const localDocs: SearchResultItem[] = searchData.local?.documents || [];
      const localVideos: SearchResultItem[] = searchData.local?.videos || [];
      const localAudio: SearchResultItem[] = searchData.local?.audio || [];
      const localImages: SearchResultItem[] = searchData.local?.images || [];
      const internetWeb: SearchResultItem[] = searchData.internet?.web || [];
      const internetNews: SearchResultItem[] = searchData.internet?.news || [];
      const internetPapers: SearchResultItem[] = searchData.internet?.papers || [];
      const internetVideos: SearchResultItem[] = searchData.internet?.videos || [];
      const internetImages: SearchResultItem[] = searchData.internet?.images || [];

      // Map discovered items into ContextItem[]
      const discoveredItems: ContextItem[] = [];

      // 1. Prioritize user-attached document/image as the primary context item
      if (attachedFiles.length > 0) {
        attachedFiles.forEach((att, idx) => {
          const isImg = att.file.type.startsWith('image/');
          const attSnippet = snippetsByAttachment[idx];
          discoveredItems.push({
            id: `attached-${att.id || idx}`,
            type: isImg ? 'image' : 'document',
            title: `[Attached ${isImg ? 'Image' : 'Document'}] ${att.name}`,
            snippet: attSnippet || `User attached ${isImg ? 'image' : 'document'}: ${att.name} (${(att.size / 1024).toFixed(1)} KB)`,
            relevanceScore: 1.0,
            // No blob: preview URL here — context is persisted and the URL dies with the page
            metadata: {
              isUserAttachment: true,
              fileName: att.name,
              fileSize: att.size,
              fileType: att.type,
              extractedSnippet: attSnippet,
            },
          });
        });
      }

      // 2. Local Knowledge Repository Sources
      localDocs.forEach((d) => {
        const cleanSid = String(d.sourceId || d.id || '').replace(/^src-/, '');
        discoveredItems.push({
          id: d.id || `doc-${cleanSid}`,
          type: 'document',
          title: d.title || 'Document',
          snippet: d.snippet || '',
          relevanceScore: d.relevanceScore,
          metadata: {
            sourceId: cleanSid,
            fileType: d.fileType,
            page: d.page,
            section: d.section,
            filePath: d.filePath,
            ...d.metadata,
          },
        });
      });

      localVideos.forEach((v) => {
        const cleanSid = String(v.sourceId || v.id || '').replace(/^src-/, '');
        discoveredItems.push({
          id: v.id || `video-${cleanSid}-${v.startTime ?? 0}`,
          type: 'video',
          title: v.title || 'Video',
          snippet: v.snippet || '',
          relevanceScore: v.relevanceScore,
          metadata: {
            sourceId: cleanSid,
            timestamp: v.startTime,
            url: v.url,
            ...v.metadata,
          },
        });
      });

      localAudio.forEach((a) => {
        const cleanSid = String(a.sourceId || a.id || '').replace(/^src-/, '');
        discoveredItems.push({
          id: a.id || `audio-${cleanSid}-${a.startTime ?? 0}`,
          type: 'audio',
          title: a.title || 'Audio Recording',
          snippet: a.snippet || '',
          relevanceScore: a.relevanceScore,
          metadata: {
            sourceId: cleanSid,
            timestamp: a.startTime,
            ...a.metadata,
          },
        });
      });

      localImages.forEach((img) => {
        const cleanSid = String(img.sourceId || img.id || '').replace(/^src-/, '');
        discoveredItems.push({
          id: img.id || `image-${cleanSid}`,
          type: 'image',
          title: img.title || 'Image',
          snippet: img.snippet || '',
          relevanceScore: img.relevanceScore,
          metadata: {
            sourceId: cleanSid,
            ...img.metadata,
          },
        });
      });

      // 3. Live Internet Sources (Videos, Web, News, Papers, Images)
      internetVideos.forEach((v) => {
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

      internetWeb.forEach((w) => {
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

      internetNews.forEach((n) => {
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

      internetPapers.forEach((p) => {
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

      internetImages.forEach((img) => {
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

      // User attachments first; then local results by real relevance; internet results keep
      // provider order after them (their scores are fixed placeholders, not comparable).
      const rank = (item: ContextItem) => (item.metadata?.isUserAttachment ? 0 : item.metadata?.isInternet ? 2 : 1);
      discoveredItems.sort((a, b) => rank(a) - rank(b) || (b.relevanceScore || 0) - (a.relevanceScore || 0));

      // Populate right sidebar with discovered sources (replacing previous source set when re-run)
      setActiveContext(discoveredItems);
      setIsContextOpen(true);
      setWorkflowState('reviewing_sources');
      setWorkflowProgressText(
        `Discovered ${discoveredItems.length} matching sources. Review and remove unwanted items, then click Generate Answer.`
      );

      if (discoveredItems.length > 0) {
        toast.success(`Found ${discoveredItems.length} sources matching 20% relative similarity.`);
      } else {
        toast.info('No documents matched the 20% threshold. You can still generate an answer or refine your prompt.');
      }
    } catch (err) {
      toast.error(errorText(err, 'Smart search failed. Please try again.'));
      setWorkflowState('idle');
    }
  };

  // The server chat is created with its first message. It starts with the sources chosen
  // before it existed and keeps this component's workflow running.
  const ensureChat = async (title: string): Promise<string | null> => {
    if (activeChatId) return activeChatId;
    try {
      const chat = await createChat(title);
      const context = useChatStore.getState().activeContext;
      setOwnChatId(chat.id);
      setActiveChatId(chat.id);
      setActiveContext(context);
      return chat.id;
    } catch {
      toast.error('Failed to start a chat');
      return null;
    }
  };

  // A send in another chat may have started since; only clear this chat's marker
  const endSending = (chatId: string) => {
    if (useChatStore.getState().sendingChatId === chatId) setSending(false);
  };

  // Replace the optimistic message with the stored pair, unless another chat was opened
  // meanwhile (that chat shows its own messages; this answer is on the server).
  const showSent = (chatId: string, tempId: string, data: SentMessages) => {
    const s = useChatStore.getState();
    if (s.activeChatId !== chatId) return;
    setMessages([...s.messages.filter((m) => m.id !== tempId), ...toMessages(data)]);
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

    const confirmedContext = activeContext;
    const chatId = await ensureChat(promptToUse || extractedInfo?.searchQuery || 'Smart Search Chat');
    if (!chatId) return;

    setWorkflowState('generating_answer');
    setSending(true, chatId);

    // Persist confirmed context on the backend
    try {
      await fetch(`/api/chats/${chatId}/context`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contextItems: confirmedContext }),
      });
    } catch {
      // The message request below stores its context items too
    }

    // Optimistic user message in UI
    const tempId = newTempId();
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
          contextItems: confirmedContext,
        }),
      });

      if (!res.ok) {
        throw new Error(apiErrorMessage(await readJson(res), 'Failed to generate response'));
      }

      showSent(chatId, tempId, await res.json());
      refreshChats();

      // Confirmed sources stay active for follow-up questions, which are answered from
      // them directly (Smart Search turns off so they don't re-run the search)
      setIsSmartSearchEnabled(false);
      setInput('');
      setPendingPrompt('');
      clearAttachments();
      setWorkflowState('idle');
      toast.success('Answer generated! Confirmed sources remain active for this chat session.');
    } catch (err) {
      dropMessage(tempId);
      toast.error(errorText(err, 'Generation failed.'));
      setWorkflowState('reviewing_sources'); // allow re-clicking generate
    } finally {
      endSending(chatId);
    }
  };

  // 3. REGULAR MESSAGE SUBMIT (WHEN SMART SEARCH IS DISABLED)
  const handleSubmitWithText = async (textToSend: string, opts: { forceSmart?: boolean } = {}) => {
    if (!textToSend.trim() && attachedFiles.length === 0) return;
    if (isTyping) return;

    // If Smart Search is enabled or files are attached, route through the Smart Search workflow!
    if (opts.forceSmart || isSmartSearchEnabled || attachedFiles.length > 0) {
      handleSmartSearchFlow(textToSend);
      return;
    }

    const userMsg = textToSend.trim();
    const context = activeContext;
    const chatId = await ensureChat(userMsg);
    if (!chatId) return;

    setInput('');
    setSending(true, chatId);

    // Optimistic user message
    const tempId = newTempId();
    addMessage({ id: tempId, role: 'user', content: userMsg, createdAt: new Date().toISOString() });

    try {
      const res = await fetch(`/api/chats/${chatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg, contextItems: context }),
      });

      if (!res.ok) {
        dropMessage(tempId);
        toast.error(apiErrorMessage(await readJson(res), 'Failed to send message'));
        return;
      }

      showSent(chatId, tempId, await res.json());
      refreshChats();
    } catch {
      dropMessage(tempId);
      toast.error('Message failed. Please check connection.');
    } finally {
      endSending(chatId);
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
  const openingChat = isLoadingChat && !hasMessages && Boolean(activeChatId);

  return (
    <div className="flex h-full min-h-0 overflow-hidden relative">
      {/* Main chat column */}
      <div className="flex-1 flex flex-col min-w-0 h-full">
        {openingChat && workflowState === 'idle' && (
          <div className="flex-1 flex items-center justify-center gap-2 text-sm" style={{ color: 'var(--text-muted)' }}>
            <Loader2 className="w-4 h-4 animate-spin" style={{ color: 'var(--accent)' }} />
            Loading conversation…
          </div>
        )}

        {/* Empty state */}
        {!hasMessages && !openingChat && workflowState === 'idle' && (
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
                        handleSubmitWithText(s.text, { forceSmart: s.smart });
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

                      {/* Ranked Discovered Sources Preview directly inside chat */}
                      {workflowState === 'reviewing_sources' && activeContext.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-cyan-500/20 space-y-2">
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-bold text-cyan-400 uppercase tracking-wider text-[10px]">
                              Top Ranked Matches ({activeContext.length})
                            </span>
                            <button
                              onClick={() => setIsContextOpen(true)}
                              className="text-[11px] text-cyan-400 hover:underline flex items-center gap-1 font-medium"
                            >
                              <span>Inspect in sidebar</span>
                              <ArrowRight className="w-3 h-3" />
                            </button>
                          </div>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-48 overflow-y-auto pr-1">
                            {activeContext.slice(0, 4).map((item, idx) => {
                              const rawScore = item.relevanceScore;
                              const safeScore = rawScore === undefined || rawScore === null || isNaN(rawScore) ? 0 : rawScore > 1 ? Math.min(100, Math.round(rawScore)) : Math.round(rawScore * 100);
                              const isAtt = Boolean(item.metadata?.isUserAttachment);
                              const cleanSid = item.metadata?.sourceId ? String(item.metadata.sourceId).replace(/^src-/, '') : null;
                              return (
                                <div
                                  key={item.id || idx}
                                  onClick={() => {
                                    if (cleanSid) {
                                      setInspectSourceId(cleanSid);
                                    } else if (item.metadata?.url) {
                                      window.open(String(item.metadata.url), '_blank');
                                    }
                                  }}
                                  className="p-2.5 rounded-xl bg-[var(--bg-base)]/80 border border-cyan-500/20 hover:border-cyan-500/40 transition-all cursor-pointer flex items-start gap-2 text-left"
                                >
                                  <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded flex-shrink-0 mt-0.5 ${
                                    idx === 0
                                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                                      : 'bg-zinc-800 text-zinc-400 border border-zinc-700/50'
                                  }`}>
                                    {isAtt ? 'User File' : idx === 0 ? '🏆 #1' : `#${idx + 1}`}
                                  </span>
                                  <div className="min-w-0 flex-1">
                                    <div className="flex items-center justify-between gap-1">
                                      <h5 className="text-[11px] font-bold truncate text-[var(--text-primary)]">
                                        {item.title}
                                      </h5>
                                      <span className="text-[10px] font-mono text-cyan-400 font-bold flex-shrink-0">
                                        {safeScore}%
                                      </span>
                                    </div>
                                    {item.snippet && (
                                      <p className="text-[10px] text-muted-foreground line-clamp-1 mt-0.5">
                                        {item.snippet}
                                      </p>
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
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
                        disabled={isTyping || activeContext.length === 0}
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
                      // eslint-disable-next-line @next/next/no-img-element -- blob: preview URL
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
                disabled={isTyping || workflowState === 'extracting_query' || workflowState === 'searching_sources'}
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
                disabled={(!input.trim() && attachedFiles.length === 0) || isTyping}
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
                {isTyping || workflowState === 'extracting_query' || workflowState === 'searching_sources' ? (
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

