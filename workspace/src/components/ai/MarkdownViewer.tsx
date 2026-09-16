// src/components/ai/MarkdownViewer.tsx
// High-craft Markdown Code & Document Viewer for AI Chat Responses

'use client';

import React, { useState, useMemo } from 'react';
import {
  Check,
  Copy,
  Code2,
  Terminal,
  ExternalLink,
  Hash,
  Eye,
  FileCode,
} from 'lucide-react';
import { toast } from 'sonner';

interface MarkdownViewerProps {
  content: string;
  isStreaming?: boolean;
  sourceTitle?: string;
  compact?: boolean;
}

export function MarkdownViewer({
  content,
  isStreaming = false,
  sourceTitle,
}: MarkdownViewerProps) {
  const [copiedFull, setCopiedFull] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  const handleCopyFull = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(content);
      setCopiedFull(true);
      toast.success('Copied AI response to clipboard');
      setTimeout(() => setCopiedFull(false), 2000);
    } catch {
      toast.error('Failed to copy text');
    }
  };

  const parsedTokens = useMemo(() => {
    return parseMarkdown(content);
  }, [content]);

  const wordCount = useMemo(() => {
    return content.trim().split(/\s+/).filter(Boolean).length;
  }, [content]);

  if (!content && !isStreaming) return null;

  return (
    <div
      className="markdown-viewer-container w-full rounded-xl overflow-hidden border transition-all text-xs"
      style={{
        background: 'var(--bg-card)',
        borderColor: 'var(--border)',
        color: 'var(--text-primary)',
      }}
    >
      {/* Code Viewer Header Toolbar */}
      <div
        className="flex items-center justify-between px-3 py-1.5 border-b select-none flex-wrap gap-1"
        style={{
          background: 'var(--bg-elevated)',
          borderColor: 'var(--border-subtle)',
        }}
      >
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-rose-500/80 inline-block" />
            <span className="w-2 h-2 rounded-full bg-amber-500/80 inline-block" />
            <span className="w-2 h-2 rounded-full bg-emerald-500/80 inline-block" />
          </div>

          <div className="flex items-center gap-1.5 ml-1 px-1.5 py-0.5 rounded-md bg-indigo-500/10 text-indigo-400 font-mono text-[10px] font-semibold border border-indigo-500/20">
            <FileCode className="w-3 h-3" />
            <span>markdown-viewer</span>
          </div>

          {sourceTitle && (
            <span
              className="text-[10px] font-medium truncate max-w-[140px] hidden sm:inline"
              style={{ color: 'var(--text-muted)' }}
              title={sourceTitle}
            >
              ref: {sourceTitle}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {!isStreaming && wordCount > 0 && (
            <span
              className="text-[10px] font-mono font-medium hidden xs:inline"
              style={{ color: 'var(--text-muted)' }}
            >
              {wordCount} words
            </span>
          )}

          {/* Toggle Raw vs Formatted */}
          <button
            onClick={() => setShowRaw(!showRaw)}
            className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-medium border transition-colors hover:bg-[var(--bg-hover)]"
            style={{
              background: showRaw ? 'var(--accent-muted)' : 'transparent',
              borderColor: 'var(--border)',
              color: showRaw ? 'var(--accent)' : 'var(--text-secondary)',
            }}
            title={showRaw ? 'Switch to formatted view' : 'View raw markdown source'}
          >
            {showRaw ? <Eye className="w-2.5 h-2.5" /> : <Code2 className="w-2.5 h-2.5" />}
            <span>{showRaw ? 'Formatted' : 'Raw'}</span>
          </button>

          {/* Copy Full Button */}
          <button
            onClick={handleCopyFull}
            className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-medium border transition-colors hover:bg-[var(--bg-hover)]"
            style={{
              borderColor: 'var(--border)',
              color: copiedFull ? '#10b981' : 'var(--text-secondary)',
            }}
            title="Copy entire response"
          >
            {copiedFull ? (
              <>
                <Check className="w-2.5 h-2.5 text-emerald-400 stroke-[3]" />
                <span className="text-emerald-400 font-semibold">Copied</span>
              </>
            ) : (
              <>
                <Copy className="w-2.5 h-2.5" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Main Viewer Body */}
      <div className="p-3.5 space-y-2.5 overflow-x-auto leading-relaxed">
        {showRaw ? (
          <pre
            className="font-mono text-xs p-3 rounded-lg border whitespace-pre-wrap select-text overflow-x-auto"
            style={{
              background: 'var(--bg-base)',
              borderColor: 'var(--border)',
              color: 'var(--text-secondary)',
            }}
          >
            {content}
          </pre>
        ) : (
          <div className="space-y-3 select-text">
            {parsedTokens.map((token, idx) => (
              <RenderToken key={idx} token={token} />
            ))}

            {isStreaming && (
              <span className="inline-block w-2 h-4 ml-1 bg-indigo-500 rounded-sm animate-pulse align-middle" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Token Definition & Parser ──────────────────────────────────────────────

type TokenType =
  | { type: 'code_block'; lang: string; code: string }
  | { type: 'heading'; level: number; text: string }
  | { type: 'list'; items: string[]; ordered: boolean }
  | { type: 'blockquote'; text: string }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'horizontal_rule' }
  | { type: 'paragraph'; text: string };

function parseMarkdown(md: string): TokenType[] {
  const lines = md.split('\n');
  const tokens: TokenType[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // 1. Code Block (```lang)
    if (line.trim().startsWith('```')) {
      const lang = line.trim().replace(/^```/, '').trim() || 'code';
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      tokens.push({
        type: 'code_block',
        lang,
        code: codeLines.join('\n'),
      });
      i++;
      continue;
    }

    // 2. Horizontal Rule (--- or ***)
    if (/^(\s*[-*_]\s*){3,}$/.test(line)) {
      tokens.push({ type: 'horizontal_rule' });
      i++;
      continue;
    }

    // 3. Headings (# H1, ## H2, ### H3, #### H4)
    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      tokens.push({
        type: 'heading',
        level: headingMatch[1].length,
        text: headingMatch[2],
      });
      i++;
      continue;
    }

    // 4. Blockquote (> text)
    if (line.trim().startsWith('>')) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        quoteLines.push(lines[i].trim().replace(/^>\s?/, ''));
        i++;
      }
      tokens.push({
        type: 'blockquote',
        text: quoteLines.join(' '),
      });
      continue;
    }

    // 5. Tables (| Header 1 | Header 2 |)
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
        tableLines.push(lines[i]);
        i++;
      }

      if (tableLines.length >= 2) {
        const headers = tableLines[0]
          .split('|')
          .slice(1, -1)
          .map((c) => c.trim());
        const hasDivider = tableLines[1].includes('---');
        const rowStartIndex = hasDivider ? 2 : 1;
        const rows = tableLines.slice(rowStartIndex).map((r) =>
          r
            .split('|')
            .slice(1, -1)
            .map((c) => c.trim())
        );

        tokens.push({
          type: 'table',
          headers,
          rows,
        });
        continue;
      }
    }

    // 6. Ordered List (1. Item)
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ''));
        i++;
      }
      tokens.push({
        type: 'list',
        ordered: true,
        items,
      });
      continue;
    }

    // 7. Unordered List (- Item, * Item, • Item)
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*•]\s+/, ''));
        i++;
      }
      tokens.push({
        type: 'list',
        ordered: false,
        items,
      });
      continue;
    }

    // 8. Paragraph (Regular text, combining consecutive non-empty lines)
    if (line.trim()) {
      const pLines: string[] = [];
      while (
        i < lines.length &&
        lines[i].trim() &&
        !lines[i].trim().startsWith('```') &&
        !lines[i].match(/^#{1,6}\s+/) &&
        !lines[i].trim().startsWith('>') &&
        !(lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) &&
        !/^\s*\d+\.\s+/.test(lines[i]) &&
        !/^\s*[-*•]\s+/.test(lines[i]) &&
        !/^(\s*[-*_]\s*){3,}$/.test(lines[i])
      ) {
        pLines.push(lines[i]);
        i++;
      }
      tokens.push({
        type: 'paragraph',
        text: pLines.join(' '),
      });
      continue;
    }

    i++;
  }

  return tokens;
}

// ─── Token Rendering Components ─────────────────────────────────────────────

function RenderToken({ token }: { token: TokenType }) {
  switch (token.type) {
    case 'code_block':
      return <CodeBlockCard lang={token.lang} code={token.code} />;

    case 'heading': {
      const sizeClasses = {
        1: 'text-sm sm:text-base font-bold text-foreground pb-1 border-b border-[var(--border)] mt-2 mb-1 text-indigo-400',
        2: 'text-xs sm:text-sm font-bold text-foreground mt-2 mb-0.5 text-indigo-300',
        3: 'text-xs font-bold text-foreground mt-1.5 mb-0.5 text-emerald-400',
        4: 'text-xs font-semibold text-foreground mt-1',
        5: 'text-xs font-medium text-muted-foreground mt-1',
        6: 'text-xs font-medium text-muted-foreground mt-1',
      }[token.level] || 'text-xs font-bold';

      return (
        <div className={`flex items-center gap-1.5 ${sizeClasses}`}>
          <Hash className="w-3 h-3 opacity-60 flex-shrink-0" />
          <span><FormattedInline text={token.text} /></span>
        </div>
      );
    }

    case 'list':
      return (
        <ul className={`space-y-1 my-1.5 ${token.ordered ? 'list-decimal pl-4' : 'pl-1'}`}>
          {token.items.map((item, idx) => (
            <li key={idx} className="flex items-start gap-2 leading-relaxed">
              {!token.ordered && (
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 flex-shrink-0" />
              )}
              {token.ordered && (
                <span className="font-mono text-[10px] text-indigo-400 font-bold mt-0.5 flex-shrink-0">
                  {idx + 1}.
                </span>
              )}
              <span className="flex-1">
                <FormattedInline text={item} />
              </span>
            </li>
          ))}
        </ul>
      );

    case 'blockquote':
      return (
        <blockquote
          className="p-2.5 rounded-r-xl border-l-3 my-2 text-xs italic font-medium leading-relaxed"
          style={{
            borderLeftColor: '#6366f1',
            background: 'rgba(99, 102, 241, 0.07)',
            color: 'var(--text-primary)',
          }}
        >
          <FormattedInline text={token.text} />
        </blockquote>
      );

    case 'table':
      return (
        <div
          className="w-full my-2.5 overflow-x-auto rounded-xl border"
          style={{ borderColor: 'var(--border)', background: 'var(--bg-base)' }}
        >
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr
                className="border-b"
                style={{
                  background: 'var(--bg-elevated)',
                  borderColor: 'var(--border)',
                }}
              >
                {token.headers.map((h, i) => (
                  <th
                    key={i}
                    className="px-3 py-2 font-bold font-mono text-[11px]"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    <FormattedInline text={h} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {token.rows.map((row, rIdx) => (
                <tr
                  key={rIdx}
                  className="border-b last:border-b-0 hover:bg-[var(--bg-hover)] transition-colors"
                  style={{ borderColor: 'var(--border-subtle)' }}
                >
                  {row.map((cell, cIdx) => (
                    <td
                      key={cIdx}
                      className="px-3 py-1.5"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      <FormattedInline text={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case 'horizontal_rule':
      return <hr className="my-3 border-t" style={{ borderColor: 'var(--border)' }} />;

    case 'paragraph':
      return (
        <p className="leading-relaxed" style={{ color: 'var(--text-primary)' }}>
          <FormattedInline text={token.text} />
        </p>
      );

    default:
      return null;
  }
}

// ─── Code Block Card Component ──────────────────────────────────────────────

function CodeBlockCard({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopyCode = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      toast.success('Copied code block');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Failed to copy code');
    }
  };

  const lineCount = code.split('\n').length;

  return (
    <div
      className="my-2 rounded-xl overflow-hidden border shadow-sm"
      style={{
        background: '#090d16',
        borderColor: 'rgba(99, 102, 241, 0.25)',
      }}
    >
      {/* Code Header Bar */}
      <div
        className="flex items-center justify-between px-3 py-1.5 border-b"
        style={{
          background: '#0f172a',
          borderColor: 'rgba(255, 255, 255, 0.08)',
        }}
      >
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-indigo-400" />
          <span className="font-mono text-[11px] font-bold text-indigo-300 uppercase tracking-wider">
            {lang || 'code'}
          </span>
          <span className="text-[10px] font-mono text-slate-500">
            {lineCount} {lineCount === 1 ? 'line' : 'lines'}
          </span>
        </div>

        <button
          onClick={handleCopyCode}
          className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium transition-all"
          style={{
            background: copied ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255, 255, 255, 0.08)',
            color: copied ? '#10b981' : '#94a3b8',
            border: `1px solid ${copied ? '#10b98140' : 'rgba(255, 255, 255, 0.1)'}`,
          }}
          title="Copy code snippet"
        >
          {copied ? (
            <>
              <Check className="w-2.5 h-2.5 text-emerald-400 stroke-[3]" />
              <span className="text-emerald-400 font-bold">Copied</span>
            </>
          ) : (
            <>
              <Copy className="w-2.5 h-2.5" />
              <span>Copy Code</span>
            </>
          )}
        </button>
      </div>

      {/* Code Content View */}
      <div className="p-3 overflow-x-auto font-mono text-xs leading-relaxed text-slate-200">
        <pre className="select-text whitespace-pre">
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
}

// ─── Inline Formatter (Bold, Italic, Code, Links) ───────────────────────────

function FormattedInline({ text }: { text: string }) {
  if (!text) return null;

  // Split by inline code first: `code`
  const codeParts = text.split(/(`[^`]+`)/g);

  return (
    <>
      {codeParts.map((part, idx) => {
        if (part.startsWith('`') && part.endsWith('`') && part.length > 1) {
          const inner = part.slice(1, -1);
          return (
            <code
              key={idx}
              className="px-1.5 py-0.5 mx-0.5 rounded-md font-mono text-[11px] font-semibold border inline-block"
              style={{
                background: 'rgba(99, 102, 241, 0.12)',
                borderColor: 'rgba(99, 102, 241, 0.25)',
                color: '#818cf8',
              }}
            >
              {inner}
            </code>
          );
        }

        return <FormattedTextSpan key={idx} text={part} />;
      })}
    </>
  );
}

function FormattedTextSpan({ text }: { text: string }) {
  // Parse links: [label](url)
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
  const elements: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = linkRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      elements.push(
        <FormatBoldItalic key={lastIndex} text={text.slice(lastIndex, match.index)} />
      );
    }
    const linkLabel = match[1];
    const linkUrl = match[2];
    elements.push(
      <a
        key={match.index}
        href={linkUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-0.5 text-indigo-400 hover:text-indigo-300 font-semibold underline underline-offset-2 transition-colors mx-0.5"
      >
        <span>{linkLabel}</span>
        <ExternalLink className="w-2.5 h-2.5 inline" />
      </a>
    );
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    elements.push(
      <FormatBoldItalic key={lastIndex} text={text.slice(lastIndex)} />
    );
  }

  return <>{elements}</>;
}

function FormatBoldItalic({ text }: { text: string }) {
  // Parse **bold** and *italic*
  const boldParts = text.split(/(\*\*[^*]+\*\*)/g);

  return (
    <>
      {boldParts.map((bPart, bIdx) => {
        if (bPart.startsWith('**') && bPart.endsWith('**') && bPart.length > 3) {
          return (
            <strong key={bIdx} className="font-bold text-foreground">
              {bPart.slice(2, -2)}
            </strong>
          );
        }

        // Parse *italic* inside non-bold text
        const italicParts = bPart.split(/(\*[^*]+\*)/g);
        return (
          <React.Fragment key={bIdx}>
            {italicParts.map((iPart, iIdx) => {
              if (iPart.startsWith('*') && iPart.endsWith('*') && iPart.length > 2) {
                return (
                  <em key={iIdx} className="italic text-muted-foreground">
                    {iPart.slice(1, -1)}
                  </em>
                );
              }
              return iPart;
            })}
          </React.Fragment>
        );
      })}
    </>
  );
}
