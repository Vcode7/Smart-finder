'use client';

import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useChat } from '@/hooks/useChat';
import { Send, Square, MessageSquare, Sparkles, Bot, User, CornerDownLeft } from 'lucide-react';
import { MarkdownViewer } from '@/components/ai/MarkdownViewer';
import type { Source } from '@/types/research';

const SUGGESTED_QUESTIONS = [
  'What is the core argument?',
  'What limitations or caveats are mentioned?',
  'Explain the methodology simply.',
  'What statistics support this claim?',
];

interface ChatPanelProps {
  source: Source;
  sessionId: string;
  fullHeight?: boolean;
}

export function ChatPanel({ source, sessionId, fullHeight }: ChatPanelProps) {
  const { sendMessage, isStreaming, streamingText, stopStreaming } = useChat(sessionId, source);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [source.chatHistory, streamingText]);

  const handleSend = (msg?: string) => {
    const m = msg || input.trim();
    if (!m) return;
    sendMessage(m);
    setInput('');
  };

  const allMessages = source.chatHistory;

  return (
    <div className={`flex flex-col ${fullHeight ? 'h-full' : 'max-h-[480px]'}`}>
      {/* Header Bar */}
      <div className="flex items-center justify-between gap-2 pb-2 mb-2 border-b" style={{ borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-md bg-indigo-500/20 flex items-center justify-center text-indigo-400">
            <Bot className="w-3 h-3" />
          </div>
          <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
            Source Deep-Dive AI Chat
          </span>
        </div>
        <span className="text-[10px] font-mono text-muted-foreground">Groq Qwen 3.6 27B</span>
      </div>

      {/* Message History */}
      <div className="flex-1 overflow-y-auto space-y-3 mb-3 pr-1 min-h-[160px]">
        {allMessages.length === 0 && !streamingText && (
          <div className="py-4 text-center px-2">
            <p className="text-xs font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>
              Ask anything about <span className="font-semibold text-indigo-400">&ldquo;{source.title.slice(0, 30)}...&rdquo;</span>
            </p>
            <div className="flex flex-wrap gap-1.5 justify-center">
              {SUGGESTED_QUESTIONS.map((q) => (
                <button
                  key={q}
                  onClick={() => handleSend(q)}
                  className="text-[11px] px-2.5 py-1.5 rounded-xl border text-left transition-all hover:bg-[var(--bg-hover)] hover:border-indigo-500/40"
                  style={{
                    background: 'var(--bg-card)',
                    borderColor: 'var(--border)',
                    color: 'var(--text-secondary)',
                  }}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {allMessages.map((msg) => (
          <div
            key={msg.id}
            className={`flex items-start gap-2 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'assistant' && (
              <div className="w-6 h-6 rounded-lg bg-purple-500/20 text-purple-400 flex items-center justify-center flex-shrink-0 mt-1">
                <Bot className="w-3.5 h-3.5" />
              </div>
            )}

            {msg.role === 'assistant' ? (
              <div className="flex-1 max-w-[94%] min-w-0">
                <MarkdownViewer content={msg.content} sourceTitle={source.title} />
              </div>
            ) : (
              <div
                className="max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-tr-sm text-xs leading-relaxed font-medium text-white shadow-sm"
                style={{
                  background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
                }}
              >
                {msg.content}
              </div>
            )}

            {msg.role === 'user' && (
              <div className="w-6 h-6 rounded-lg bg-indigo-500/20 text-indigo-400 flex items-center justify-center flex-shrink-0 mt-1">
                <User className="w-3.5 h-3.5" />
              </div>
            )}
          </div>
        ))}

        {/* Streaming Message Response in Markdown Viewer Format */}
        {streamingText && (
          <div className="flex items-start gap-2 justify-start">
            <div className="w-6 h-6 rounded-lg bg-purple-500/20 text-purple-400 flex items-center justify-center flex-shrink-0 mt-1">
              <Bot className="w-3.5 h-3.5 animate-pulse" />
            </div>
            <div className="flex-1 max-w-[94%] min-w-0">
              <MarkdownViewer content={streamingText} isStreaming sourceTitle={source.title} />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Box */}
      <div
        className="flex items-center gap-2 p-2 rounded-2xl border transition-all focus-within:border-indigo-500/50 shadow-sm"
        style={{ background: 'var(--bg-base)', borderColor: 'var(--border)' }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder="Ask a question about this source..."
          className="flex-1 bg-transparent text-xs outline-none px-2 font-medium"
          style={{ color: 'var(--text-primary)' }}
          disabled={isStreaming}
        />

        {isStreaming ? (
          <button
            onClick={stopStreaming}
            className="p-2 rounded-xl bg-rose-500/20 text-rose-400 hover:bg-rose-500/30 transition-colors flex-shrink-0"
            title="Stop generation"
          >
            <Square className="w-3.5 h-3.5" />
          </button>
        ) : (
          <button
            onClick={() => handleSend()}
            disabled={!input.trim()}
            className="p-2 rounded-xl text-white shadow-md shadow-indigo-500/20 transition-all disabled:opacity-40 disabled:hover:scale-100 hover:scale-105 flex-shrink-0"
            style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }}
            title="Send Message"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}
