'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { useResearchStore } from '@/store/research';
import { useUIStore } from '@/store/ui';
import { toast } from 'sonner';
import { FileOutput, Zap, Download, Copy, Check, Sparkles, BookOpen, ExternalLink, ShieldCheck } from 'lucide-react';
import type { ResearchSession } from '@/types/research';

interface ReportGeneratorProps {
  session: ResearchSession;
  sessionId: string;
}

export function ReportGenerator({ session, sessionId }: ReportGeneratorProps) {
  const { addReport } = useResearchStore();
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const report = session.reports[0];

  const { aiSelectedSourceIds } = useUIStore();

  const generate = async () => {
    if (session.sources.length === 0) {
      toast.error('No sources available');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch('/api/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: session.topic,
          sources: session.sources,
          selectedSourceIds: aiSelectedSourceIds,
          briefing: session.overallBriefing,
        }),
      });
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.message || 'Report generation failed');
      }
      const data = await res.json();
      addReport(sessionId, data);
      toast.success('Formal research report compiled!');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to generate report';
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const exportMarkdown = () => {
    if (!report) return;
    const md = `# ${report.topic}
*AI Comprehensive Intelligence Dossier*
*Date: ${new Date(report.generatedAt).toLocaleDateString()}*

---

## 1. Executive Summary
${report.executiveSummary}

## 2. Background & Strategic Context
${report.background}

## 3. Key Findings
${report.keyFindings.map((f, i) => `${i + 1}. ${f}`).join('\n')}

## 4. Empirical Evidence & Citations
${report.evidence.map((e) => `### ${e.claim}\n${e.sources.map((s) => `- ${s.text}`).join('\n')}`).join('\n\n')}

## 5. Perspectives & Stakeholder Analysis
${report.perspectives.map((p) => `### ${p.viewpoint}`).join('\n')}

## 6. Identified Contradictions
${report.contradictions.map((c, i) => `${i + 1}. ${c}`).join('\n')}

## 7. Key Quantitative Statistics
${report.statistics.map((s, i) => `${i + 1}. ${s}`).join('\n')}

## 8. Strategic Conclusion
${report.conclusion}

## 9. Bibliography & Analyzed Sources
${report.sources.map((s, i) => `${i + 1}. [${s.title}](${s.url}) — *${s.provider}*`).join('\n')}

---
*Synthesized via Smart Finder (Groq Qwen 3.6 27B)*
`;
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${session.topic.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase()}-report.md`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success('Downloaded Markdown Report');
  };

  const copyReport = () => {
    if (!report) return;
    navigator.clipboard.writeText(
      `# ${report.topic}\n\n${report.executiveSummary}\n\n## Key Findings\n` +
      report.keyFindings.join('\n')
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast.success('Copied summary to clipboard');
  };

  if (!report) {
    return (
      <div
        className="rounded-3xl p-8 sm:p-12 text-center border shadow-xl relative overflow-hidden"
        style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
      >
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5 shadow-lg shadow-rose-500/25" style={{ background: 'linear-gradient(135deg, #f43f5e 0%, #a855f7 100%)' }}>
          <FileOutput className="w-8 h-8 text-white" />
        </div>

        <h3 className="text-xl sm:text-2xl font-extrabold mb-2" style={{ color: 'var(--text-primary)' }}>
          Compile Formal Research Report
        </h3>

        <p className="text-xs sm:text-sm max-w-xl mx-auto mb-8 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Generate a publication-ready research dossier formatted with structured headings, empirical evidence citations, stakeholder perspectives, and bibliography.
        </p>

        <button
          onClick={generate}
          disabled={loading}
          className="inline-flex items-center gap-2.5 px-6 py-3 rounded-2xl font-bold text-sm text-white shadow-lg shadow-rose-500/25 transition-all hover:scale-105 disabled:opacity-50"
          style={{ background: 'linear-gradient(135deg, #f43f5e 0%, #a855f7 100%)' }}
        >
          {loading ? (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Compiling Research Dossier...</span>
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4" />
              <span>Compile Full Research Report</span>
            </>
          )}
        </button>
      </div>
    );
  }

  const SECTIONS = [
    { title: '1. Executive Summary', content: report.executiveSummary, color: '#6366f1' },
    { title: '2. Background & Strategic Context', content: report.background, color: '#06b6d4' },
    { title: '3. Key Findings', content: report.keyFindings.map((f, i) => `${i + 1}. ${f}`).join('\n\n'), color: '#10b981' },
    { title: '4. Empirical Evidence', content: report.evidence.map((e) => `**${e.claim}**\n${e.sources.map((s) => `• ${s.text}`).join('\n')}`).join('\n\n'), color: '#a855f7' },
    { title: '5. Perspectives & Viewpoints', content: report.perspectives.map((p) => `**${p.viewpoint}**`).join('\n\n'), color: '#f59e0b' },
    { title: '6. Identified Contradictions', content: report.contradictions.map((c, i) => `${i + 1}. ${c}`).join('\n\n'), color: '#f43f5e' },
    { title: '7. Quantitative Statistics', content: report.statistics.map((s, i) => `${i + 1}. ${s}`).join('\n\n'), color: '#14b8a6' },
    { title: '8. Strategic Conclusion', content: report.conclusion, color: '#6366f1' },
  ];

  return (
    <div className="space-y-5">
      {/* Report Action Banner */}
      <div
        className="flex items-center justify-between gap-3 px-5 py-4 rounded-2xl border shadow-md backdrop-blur-xl flex-wrap"
        style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center bg-rose-500/15 text-rose-400">
            <FileOutput className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              Publication-Ready Research Dossier
            </h3>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              {report.sources.length} cited sources • Compiled {new Date(report.generatedAt).toLocaleDateString()}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={generate}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold hover:bg-[var(--bg-hover)] transition-colors"
            style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', background: 'var(--bg-card)' }}
          >
            <Zap className="w-3.5 h-3.5" />
            <span>Re-synthesize</span>
          </button>

          <button
            onClick={copyReport}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold hover:bg-[var(--bg-hover)] transition-colors"
            style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', background: 'var(--bg-card)' }}
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied!' : 'Copy Summary'}</span>
          </button>

          <button
            onClick={exportMarkdown}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-xl text-xs font-bold text-white shadow-md shadow-indigo-500/20"
            style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export Markdown</span>
          </button>
        </div>
      </div>

      {/* Formal Paper Container */}
      <div className="space-y-4 max-w-4xl mx-auto">
        {SECTIONS.map((section, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04 }}
            className="rounded-2xl p-5 border shadow-sm"
            style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
          >
            <h4 className="text-xs font-bold uppercase tracking-wider mb-3 flex items-center gap-2" style={{ color: section.color }}>
              <span className="w-2 h-2 rounded-full" style={{ background: section.color }} />
              {section.title}
            </h4>

            <div className="text-xs sm:text-sm font-normal leading-relaxed space-y-2" style={{ color: 'var(--text-primary)' }}>
              {section.content.split('\n\n').map((para, pi) => (
                <p key={pi}>{para}</p>
              ))}
            </div>
          </motion.div>
        ))}

        {/* Bibliography Section */}
        <div className="rounded-2xl border overflow-hidden shadow-sm" style={{ borderColor: 'var(--border)' }}>
          <div className="px-5 py-3.5 border-b" style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}>
            <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-400">
              9. Primary Bibliography & Analyzed Sources ({report.sources.length})
            </h4>
          </div>

          <div className="divide-y" style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-card)' }}>
            {report.sources.map((source, i) => (
              <div key={source.id} className="flex items-center justify-between gap-3 px-5 py-3 text-xs hover:bg-[var(--bg-hover)] transition-colors">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-[11px] font-mono font-bold w-5 flex-shrink-0 text-muted-foreground">
                    [{i + 1}]
                  </span>
                  <div className="min-w-0">
                    <p className="font-semibold truncate leading-snug" style={{ color: 'var(--text-primary)' }}>
                      {source.title}
                    </p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      {source.provider} • {source.type}
                    </p>
                  </div>
                </div>

                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="p-1.5 rounded-lg border hover:bg-indigo-500/10 hover:text-indigo-400 transition-colors flex-shrink-0"
                  style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}
                  title="Open Source"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
