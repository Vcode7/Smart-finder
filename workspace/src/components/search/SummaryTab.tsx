'use client';
// Summary tab: each of the most relevant files summarised on its own, then one overall summary.
// The job runs in the background and is polled, so file summaries appear as they finish.

import { useState } from 'react';
import { AlertTriangle, Check, Copy, ExternalLink, Info, Loader2, RotateCcw, Sparkles } from 'lucide-react';
import MarkdownMessage from '@/components/chat/MarkdownMessage';
import TopicChips from '@/components/search/TopicChips';
import { withBase } from '@/lib/base-path';
import type { AsyncData, SummaryDoc, SummaryJob } from '@/types/insights';
import { toast } from 'sonner';

interface Props {
  state: AsyncData<SummaryJob>;
  onRetry: () => void;
}

const SOURCE_BADGE: Record<string, { label: string; title: string }> = {
  llm: { label: 'AI summary', title: 'Written by the AI from the file text' },
  cache: { label: 'Saved summary', title: 'Written for an earlier search and reused' },
  extractive: { label: 'Excerpt', title: 'The AI was unavailable, so this is the start of the file text' },
};

export default function SummaryTab({ state, onRetry }: Props) {
  const [copied, setCopied] = useState(false);
  const job = state.data;

  if (state.status === 'idle') {
    return <Notice title="Summary not available" text="This kind of search does not keep its results for summarising. Run a normal search to get a summary." />;
  }
  if (state.status === 'error' || (job && (job.status === 'error' || job.status === 'cancelled'))) {
    const text = job?.status === 'cancelled' ? 'The summary was cancelled.' : state.error ?? job?.error ?? 'Something went wrong.';
    return (
      <Notice title="The summary could not be completed" text={text} warn>
        <RetryButton onRetry={onRetry} />
      </Notice>
    );
  }
  if (!job) {
    return (
      <div className="space-y-3" role="status" aria-live="polite">
        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider" style={{ color: 'var(--accent)' }}>
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Preparing the summary…
        </div>
        <SkeletonCard lines={4} />
        <SkeletonCard lines={3} />
      </div>
    );
  }

  const running = job.status === 'queued' || job.status === 'running';
  const { done, total } = job.progress;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const overallPending = running && total > 1;

  const copyOverall = () => {
    if (!job.overall) return;
    navigator.clipboard.writeText(job.overall);
    setCopied(true);
    toast.success('Summary copied to clipboard');
    setTimeout(() => setCopied(false), 2000);
  };

  if (total === 0 && !running) {
    return <Notice title="Nothing to summarise" text="No files were found for this search." />;
  }

  return (
    <div className="space-y-4">
      {/* Progress */}
      {running && (
        <div className="p-4 rounded-2xl space-y-2" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }} role="status" aria-live="polite">
          <div className="flex items-center justify-between gap-2 text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
            <span className="flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: 'var(--accent)' }} /> Summarising {done} of {total} files…</span>
            <span className="font-mono" style={{ color: 'var(--text-muted)' }}>{pct}%</span>
          </div>
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--viz-grid)' }} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
            <div className="h-full rounded-full transition-all" style={{ width: `${Math.max(4, pct)}%`, background: 'var(--accent)' }} />
          </div>
        </div>
      )}

      {/* Overall summary */}
      {(job.overall || overallPending) && (
        <section className="p-5 rounded-2xl space-y-3" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--accent-glow)' }}>
          <header className="flex items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              <Sparkles className="w-4 h-4" style={{ color: 'var(--accent)' }} aria-hidden />
              Overall summary {total > 1 && <span className="text-[11px] font-normal" style={{ color: 'var(--text-muted)' }}>of the {total} most relevant files</span>}
            </h3>
            {job.overall && (
              <button type="button" onClick={copyOverall} className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold hover:bg-[var(--bg-hover)]"
                style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            )}
          </header>
          {job.overall ? (
            <div className="text-sm leading-relaxed" style={{ color: 'var(--text-primary)' }}>
              <MarkdownMessage content={job.overall} />
            </div>
          ) : (
            <div className="space-y-2" aria-hidden>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Written once every file has been summarised.</p>
              <div className="h-3 w-full rounded animate-pulse" style={{ background: 'var(--bg-active)' }} />
              <div className="h-3 w-5/6 rounded animate-pulse" style={{ background: 'var(--bg-active)' }} />
            </div>
          )}
        </section>
      )}

      {job.warnings.length > 0 && (
        <div className="p-3 rounded-2xl flex gap-2 text-xs" style={{ background: 'var(--warning-muted)', color: 'var(--text-primary)' }} role="note">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--warning)' }} aria-hidden />
          <div className="space-y-1">
            {job.warnings.map((w) => <p key={w}>{w}</p>)}
            {!running && <RetryButton onRetry={onRetry} label="Try the AI again" />}
          </div>
        </div>
      )}

      {/* One summary per file */}
      <ol className="space-y-3">
        {job.docs.map((d, i) => <DocCard key={d.id} doc={d} rank={i + 1} />)}
      </ol>

      {!running && <UsageFooter job={job} />}
    </div>
  );
}

function DocCard({ doc, rank }: { doc: SummaryDoc; rank: number }) {
  const badge = doc.source ? SOURCE_BADGE[doc.source] : null;
  return (
    <li className="p-4 rounded-2xl space-y-2" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
      <div className="flex items-start gap-3">
        <span className="text-[11px] font-mono font-bold w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'var(--accent-muted)', color: 'var(--accent)' }}>{rank}</span>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="text-sm font-bold truncate max-w-full" style={{ color: 'var(--text-primary)' }} title={doc.relPath}>{doc.title}</h4>
            <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full" style={{ background: 'var(--bg-active)', color: 'var(--accent)' }}>{doc.fileType || doc.category}</span>
            <span className="text-[10px] font-mono font-bold" style={{ color: 'var(--text-muted)' }}>{Math.round((doc.relevanceScore || 0) * 100)}% match</span>
            {badge && (
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full" title={badge.title}
                style={{ background: doc.source === 'extractive' ? 'var(--warning-muted)' : 'var(--bg-active)', color: doc.source === 'extractive' ? 'var(--warning)' : 'var(--text-secondary)' }}>
                {doc.source === 'extractive' && <Info className="w-3 h-3" aria-hidden />}{badge.label}
              </span>
            )}
          </div>
          {(doc.libraryName || doc.folder) && (
            <p className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }}>{doc.libraryName ? `${doc.libraryName} · ` : ''}{doc.folder || '(top level)'}</p>
          )}
        </div>
        {doc.libraryId && (
          <a href={withBase(`/api/knowledge/${doc.sourceId}/file`)} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-semibold flex-shrink-0"
            style={{ background: 'var(--accent-muted)', color: 'var(--accent)' }}>
            Open <ExternalLink className="w-3 h-3" aria-hidden />
          </a>
        )}
      </div>
      {doc.state === 'done' && doc.summary ? (
        <>
          <p className="text-xs leading-relaxed select-text" style={{ color: 'var(--text-secondary)' }}>{doc.summary}</p>
          <TopicChips topics={doc.topics} events={doc.events} max={5} />
        </>
      ) : (
        <div className="space-y-2 pl-9" aria-hidden>
          <div className="h-3 w-full rounded animate-pulse" style={{ background: 'var(--bg-active)' }} />
          <div className="h-3 w-4/5 rounded animate-pulse" style={{ background: 'var(--bg-active)' }} />
        </div>
      )}
    </li>
  );
}

function UsageFooter({ job }: { job: SummaryJob }) {
  const { calls, promptTokens, completionTokens, cachedDocs } = job.usage;
  return (
    <p className="text-[11px] text-center" style={{ color: 'var(--text-muted)' }}>
      {calls === 0 ? 'No AI calls were needed' : `${calls} AI call${calls === 1 ? '' : 's'} · ${(promptTokens + completionTokens).toLocaleString()} tokens (${promptTokens.toLocaleString()} in, ${completionTokens.toLocaleString()} out)`}
      {cachedDocs > 0 && ` · ${cachedDocs} file${cachedDocs === 1 ? '' : 's'} reused from earlier summaries`}
    </p>
  );
}

function RetryButton({ onRetry, label = 'Try again' }: { onRetry: () => void; label?: string }) {
  return (
    <button type="button" onClick={onRetry} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-white" style={{ background: 'var(--accent)' }}>
      <RotateCcw className="w-3.5 h-3.5" aria-hidden /> {label}
    </button>
  );
}

function SkeletonCard({ lines }: { lines: number }) {
  return (
    <div className="p-4 rounded-2xl space-y-2" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }} aria-hidden>
      <div className="h-4 w-1/3 rounded animate-pulse" style={{ background: 'var(--bg-active)' }} />
      {Array.from({ length: lines }, (_, i) => <div key={i} className="h-3 rounded animate-pulse" style={{ background: 'var(--bg-active)', width: `${100 - i * 8}%` }} />)}
    </div>
  );
}

function Notice({ title, text, warn, children }: { title: string; text: string; warn?: boolean; children?: React.ReactNode }) {
  return (
    <div className="p-8 rounded-3xl text-center space-y-2" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
      {warn && <div className="flex justify-center"><AlertTriangle className="w-5 h-5" style={{ color: 'var(--warning)' }} aria-hidden /></div>}
      <p className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{title}</p>
      <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{text}</p>
      {children}
    </div>
  );
}
