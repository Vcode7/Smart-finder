'use client';
// src/components/chat/MarkdownMessage.tsx — Rich Markdown Renderer with Thinking Block & Code Syntax Highlighting

import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain, ChevronDown, ChevronRight, Copy, Check, Terminal,
  ExternalLink, Sparkles
} from 'lucide-react';
import { toast } from 'sonner';

interface MarkdownMessageProps {
  content: string;
  isStreaming?: boolean;
}

/**
 * Extracts <think>...</think> reasoning blocks from the raw LLM output.
 */
function parseThinkingAndContent(raw: string): { thinking: string | null; response: string } {
  if (!raw) return { thinking: null, response: '' };

  // Match complete <think>...</think>
  const thinkRegex = /<think>([\s\S]*?)<\/think>/i;
  const match = raw.match(thinkRegex);

  if (match) {
    const thinking = match[1].trim();
    const response = raw.replace(thinkRegex, '').trim();
    return { thinking: thinking.length > 0 ? thinking : null, response };
  }

  // Match unclosed <think>... (e.g. streaming or cut-off)
  const unclosedThinkRegex = /<think>([\s\S]*)$/i;
  const unclosedMatch = raw.match(unclosedThinkRegex);
  if (unclosedMatch) {
    return { thinking: unclosedMatch[1].trim(), response: '' };
  }

  return { thinking: null, response: raw };
}

/**
 * Code Block Component with 1-click copy & language badge
 */
function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    toast.success('Code copied to clipboard');
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className="my-3 rounded-2xl overflow-hidden border border-[var(--border)] shadow-lg"
      style={{ background: 'rgba(15, 23, 42, 0.95)' }}
    >
      {/* Code Header Bar */}
      <div
        className="flex items-center justify-between px-4 py-2 text-xs"
        style={{
          background: 'rgba(30, 41, 59, 0.7)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
        }}
      >
        <div className="flex items-center gap-2 text-zinc-400 font-mono text-[11px]">
          <Terminal className="w-3.5 h-3.5 text-indigo-400" />
          <span className="uppercase tracking-wider font-semibold text-zinc-300">
            {language || 'text'}
          </span>
        </div>

        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all hover:bg-white/10 text-zinc-300"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-emerald-400">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code Content */}
      <pre className="p-4 overflow-x-auto text-xs font-mono leading-relaxed text-zinc-200 selection:bg-indigo-500/30">
        <code>{code}</code>
      </pre>
    </div>
  );
}

/**
 * Collapsible Thinking / Reasoning Block
 */
function ThinkingBlock({ thinking, isStreaming }: { thinking: string; isStreaming?: boolean }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div
      className="mb-4 rounded-2xl overflow-hidden transition-all duration-200"
      style={{
        background: 'rgba(99, 102, 241, 0.04)',
        border: '1px solid rgba(99, 102, 241, 0.18)',
      }}
    >
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3.5 py-2.5 text-left transition-colors hover:bg-[rgba(99,102,241,0.08)]"
      >
        <div className="flex items-center gap-2 min-w-0">
          <div
            className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ background: 'rgba(99, 102, 241, 0.15)', color: 'var(--accent)' }}
          >
            <Brain className={`w-3.5 h-3.5 ${isStreaming ? 'animate-pulse' : ''}`} />
          </div>
          <span className="text-xs font-semibold" style={{ color: 'var(--accent)' }}>
            Thinking Process
          </span>
          <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
            ({thinking.length} chars)
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
          <span className="text-[11px]">{isOpen ? 'Hide' : 'View reasoning'}</span>
          {isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div
              className="px-4 py-3 text-xs leading-relaxed font-mono whitespace-pre-wrap select-text border-t"
              style={{
                borderColor: 'rgba(99, 102, 241, 0.12)',
                color: 'var(--text-secondary)',
                background: 'rgba(0, 0, 0, 0.15)',
                maxHeight: '350px',
                overflowY: 'auto',
              }}
            >
              {thinking}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function MarkdownMessage({ content, isStreaming }: MarkdownMessageProps) {
  const { thinking, response } = parseThinkingAndContent(content);

  return (
    <div className="text-sm leading-relaxed space-y-2">
      {/* Reasoning Thought Accordion */}
      {thinking && <ThinkingBlock thinking={thinking} isStreaming={isStreaming} />}

      {/* Main Formatted Markdown Response */}
      {response ? (
        <div className="markdown-content prose prose-sm max-w-none prose-invert space-y-2">
          <ReactMarkdown
            components={{
              // Custom code block renderer
              code({ node, className, children, ...props }) {
                const match = /language-(\w+)/.exec(className || '');
                const isInline = !match && !String(children).includes('\n');

                if (isInline) {
                  return (
                    <code
                      className="px-1.5 py-0.5 rounded-md text-xs font-mono font-medium"
                      style={{
                        background: 'var(--bg-active, rgba(255,255,255,0.08))',
                        color: 'var(--accent)',
                        border: '1px solid var(--border)',
                      }}
                      {...props}
                    >
                      {children}
                    </code>
                  );
                }

                const codeString = String(children).replace(/\n$/, '');
                const language = match ? match[1] : '';

                return <CodeBlock language={language} code={codeString} />;
              },

              // Custom Link Renderer
              a({ href, children, ...props }) {
                return (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-0.5 font-medium underline underline-offset-2 transition-colors hover:opacity-80"
                    style={{ color: 'var(--accent)' }}
                    {...props}
                  >
                    <span>{children}</span>
                    <ExternalLink className="w-3 h-3 inline-block ml-0.5 opacity-70" />
                  </a>
                );
              },

              // Custom Table Renderer
              table({ children }) {
                return (
                  <div className="my-3 rounded-2xl overflow-x-auto border border-[var(--border)] shadow-sm">
                    <table className="w-full text-xs text-left border-collapse">{children}</table>
                  </div>
                );
              },
              thead({ children }) {
                return (
                  <thead style={{ background: 'var(--bg-active)', borderBottom: '1px solid var(--border)' }}>
                    {children}
                  </thead>
                );
              },
              th({ children }) {
                return (
                  <th className="px-3.5 py-2.5 font-semibold uppercase tracking-wider text-[11px]" style={{ color: 'var(--text-muted)' }}>
                    {children}
                  </th>
                );
              },
              td({ children }) {
                return (
                  <td className="px-3.5 py-2.5 border-t border-[var(--border)]" style={{ color: 'var(--text-secondary)' }}>
                    {children}
                  </td>
                );
              },

              // Custom Blockquote Renderer
              blockquote({ children }) {
                return (
                  <blockquote
                    className="pl-3.5 py-1.5 my-2.5 rounded-r-xl text-xs italic"
                    style={{
                      borderLeft: '3px solid var(--accent)',
                      background: 'rgba(99, 102, 241, 0.05)',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {children}
                  </blockquote>
                );
              },

              // Headings
              h1({ children }) {
                return <h1 className="text-lg font-bold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>{children}</h1>;
              },
              h2({ children }) {
                return <h2 className="text-base font-bold mt-3 mb-1.5" style={{ color: 'var(--text-primary)' }}>{children}</h2>;
              },
              h3({ children }) {
                return <h3 className="text-sm font-semibold mt-2.5 mb-1" style={{ color: 'var(--text-primary)' }}>{children}</h3>;
              },

              // Lists
              ul({ children }) {
                return <ul className="list-disc list-inside space-y-1 my-2 pl-1" style={{ color: 'var(--text-secondary)' }}>{children}</ul>;
              },
              ol({ children }) {
                return <ol className="list-decimal list-inside space-y-1 my-2 pl-1" style={{ color: 'var(--text-secondary)' }}>{children}</ol>;
              },
              li({ children }) {
                return <li className="text-xs leading-relaxed">{children}</li>;
              },

              // Paragraph
              p({ children }) {
                return <p className="text-xs sm:text-sm leading-relaxed mb-2 last:mb-0" style={{ color: 'var(--text-primary)' }}>{children}</p>;
              },
            }}
          >
            {response}
          </ReactMarkdown>
        </div>
      ) : thinking && !response ? (
        <p className="text-xs italic" style={{ color: 'var(--text-muted)' }}>
          Thinking in progress...
        </p>
      ) : null}
    </div>
  );
}

export default MarkdownMessage;
