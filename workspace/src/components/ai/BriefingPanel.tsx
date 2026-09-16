// src/components/ai/BriefingPanel.tsx
// Comprehensive AI Executive Briefing with Multi-Section Expansion & Default Open-All State

'use client';

import { useState, useMemo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useResearchStore } from '@/store/research';
import { useUIStore } from '@/store/ui';
import { toast } from 'sonner';
import { selectSourcesForAI } from '@/lib/sources/selection';
import {
  Zap, Sparkles, ChevronDown, ChevronRight, CheckCircle2,
  AlertTriangle, HelpCircle, FileText, CheckSquare, Layers,
  RefreshCw, Cpu, BookOpen, ShieldCheck, BarChart2,
  ChevronsUpDown, ChevronsDownUp
} from 'lucide-react';
import type { ResearchSession } from '@/types/research';

interface BriefingPanelProps {
  session: ResearchSession;
  sessionId: string;
}

const SECTIONS = [
  { key: 'executiveSummary', label: 'Executive Summary', icon: FileText, color: '#6366f1' },
  { key: 'mainFindings', label: 'Primary Key Findings', icon: ShieldCheck, isList: true, color: '#10b981' },
  { key: 'importantFacts', label: 'Critical Facts & Evidence', icon: CheckCircle2, isList: true, color: '#06b6d4' },
  { key: 'keyArguments', label: 'Core Strategic Arguments', icon: BookOpen, isList: true, color: '#f59e0b' },
  { key: 'agreements', label: 'Points of Consensus', icon: CheckCircle2, isList: true, color: '#10b981' },
  { key: 'contradictions', label: 'Contradictions & Friction', icon: AlertTriangle, isList: true, color: '#f43f5e' },
  { key: 'differentViewpoints', label: 'Multilateral Perspectives', icon: BarChart2, isList: true, color: '#8b5cf6' },
  { key: 'openQuestions', label: 'Unresolved Research Questions', icon: HelpCircle, isList: true, color: '#ec4899' },
  { key: 'importantStatistics', label: 'Quantitative Data & Statistics', icon: BarChart2, isList: true, color: '#14b8a6' },
  { key: 'conclusion', label: 'Strategic Synthesis & Conclusion', icon: Zap, color: '#6366f1' },
];

const ALL_SECTION_KEYS = SECTIONS.map((s) => s.key);

export function BriefingPanel({ session, sessionId }: BriefingPanelProps) {
  const { setBriefing } = useResearchStore();
  const { aiSelectedSourceIds } = useUIStore();
  const [loading, setLoading] = useState(false);
  
  // Default is ALL sections open at once
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(ALL_SECTION_KEYS));
  const briefing = session.overallBriefing;

  // Re-open all sections by default when a new briefing arrives
  useEffect(() => {
    if (briefing) {
      setOpenSections(new Set(ALL_SECTION_KEYS));
    }
  }, [briefing?.generatedAt]);

  const toggleSection = (key: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const allOpen = openSections.size === ALL_SECTION_KEYS.length;
  const toggleAll = () => {
    if (allOpen) {
      setOpenSections(new Set());
    } else {
      setOpenSections(new Set(ALL_SECTION_KEYS));
    }
  };

  // Calculate intelligent source selection preview
  const selectionPreview = useMemo(() => {
    return selectSourcesForAI({
      sources: session.sources,
      selectedSourceIds: aiSelectedSourceIds,
      topic: session.topic,
      operation: 'brief',
      maxSources: 6,
    });
  }, [session.sources, aiSelectedSourceIds, session.topic]);

  const generate = async () => {
    if (session.sources.length === 0) {
      toast.error('No sources available to synthesize');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch('/api/brief', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: session.topic,
          sources: session.sources,
          selectedSourceIds: aiSelectedSourceIds,
        }),
      });
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.message || 'Briefing generation failed');
      }
      const data = await res.json();
      setBriefing(sessionId, data);
      setOpenSections(new Set(ALL_SECTION_KEYS));
      toast.success('Overall executive briefing generated!');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to generate briefing.';
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  if (!briefing) {
    return (
      <div
        className="rounded-3xl p-6 sm:p-10 text-center border shadow-xl relative overflow-hidden"
        style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
      >
        <div className="absolute top-0 right-0 w-64 h-64 rounded-full blur-3xl opacity-20 pointer-events-none" style={{ background: 'var(--accent)' }} />

        <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg shadow-indigo-500/25" style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}>
          <Zap className="w-7 h-7 text-white" />
        </div>

        <h3 className="text-xl sm:text-2xl font-extrabold mb-2" style={{ color: 'var(--text-primary)' }}>
          Comprehensive AI Executive Briefing
        </h3>

        <p className="text-xs sm:text-sm max-w-xl mx-auto mb-6 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Synthesize key findings, points of consensus, policy friction, and strategic conclusions across multimodal sources.
        </p>

        {/* AI Selection & Token Budget Transparency Box */}
        <div
          className="max-w-xl mx-auto mb-8 p-4 rounded-2xl border text-left"
          style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
        >
          <div className="flex items-center justify-between gap-2 mb-3 pb-2 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-indigo-400" />
              <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
                Groq Qwen 3.6 27B Synthesis Scope
              </span>
            </div>
            <span className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded-full" style={{ background: 'var(--accent-muted)', color: 'var(--accent)' }}>
              ~{(selectionPreview.estimatedInputTokens / 1000).toFixed(1)}k tokens
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between text-[var(--text-secondary)]">
              <span>Total sources to analyze:</span>
              <span className="font-bold text-[var(--text-primary)]">
                {selectionPreview.selectedSources.length} sources
              </span>
            </div>

            <div className="flex items-center gap-2 text-emerald-400 font-medium">
              <CheckSquare className="w-3.5 h-3.5 flex-shrink-0" />
              <span>
                {selectionPreview.manuallySelectedCount} manually prioritized by you
              </span>
            </div>

            <div className="flex items-center gap-2 text-[var(--text-muted)]">
              <Layers className="w-3.5 h-3.5 flex-shrink-0" />
              <span>
                {selectionPreview.autoSelectedCount} automatically chosen for modality diversity
              </span>
            </div>
          </div>
        </div>

        <button
          onClick={generate}
          disabled={loading || session.sources.length === 0}
          className="inline-flex items-center gap-2.5 px-6 py-3 rounded-2xl font-bold text-sm text-white shadow-lg shadow-indigo-500/25 transition-all hover:scale-105 disabled:opacity-50"
          style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }}
        >
          {loading ? (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Synthesizing with Qwen 3.6 27B...</span>
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4" />
              <span>Generate AI Briefing</span>
            </>
          )}
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-2xl overflow-hidden border shadow-xl" style={{ borderColor: 'var(--border)', background: 'var(--bg-elevated)' }}>
      {/* Header Banner */}
      <div
        className="flex items-center justify-between px-5 py-4 border-b gap-3 flex-wrap"
        style={{
          background: 'linear-gradient(90deg, rgba(99,102,241,0.12) 0%, rgba(168,85,247,0.12) 100%)',
          borderColor: 'var(--border)'
        }}
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center shadow-sm flex-shrink-0" style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}>
            <Zap className="w-4 h-4 text-white" />
          </div>
          <div>
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              Overall AI Research Briefing
            </h3>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              Unified synthesis via Groq Qwen 3.6 27B • Generated {new Date(briefing.generatedAt).toLocaleTimeString()}
            </p>
          </div>
        </div>

        {/* Action Controls: Expand/Collapse All + Regenerate */}
        <div className="flex items-center gap-2">
          <button
            onClick={toggleAll}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all hover:bg-[var(--bg-hover)]"
            style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', background: 'var(--bg-card)' }}
            title={allOpen ? 'Collapse all sections' : 'Expand all sections'}
          >
            {allOpen ? <ChevronsDownUp className="w-3.5 h-3.5 text-indigo-400" /> : <ChevronsUpDown className="w-3.5 h-3.5 text-indigo-400" />}
            <span>{allOpen ? 'Collapse All' : 'Expand All'}</span>
          </button>

          <button
            onClick={generate}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all hover:bg-[var(--bg-hover)]"
            style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', background: 'var(--bg-card)' }}
            title="Regenerate briefing"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Regenerate</span>
          </button>
        </div>
      </div>

      {/* Accordion Sections (Multiple Sections Open simultaneously) */}
      <div className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
        {SECTIONS.map(({ key, label, icon: Icon, isList, color }) => {
          const value = (briefing as unknown as Record<string, unknown>)[key];
          if (!value || (Array.isArray(value) && value.length === 0)) return null;
          const isOpen = openSections.has(key);

          return (
            <div key={key} className="transition-colors">
              <button
                onClick={() => toggleSection(key)}
                className={`w-full flex items-center justify-between gap-3 px-5 py-4 text-left transition-all ${
                  isOpen ? 'bg-indigo-500/5' : 'hover:bg-[var(--bg-hover)]'
                }`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: `${color}18` }}>
                    <Icon className="w-3.5 h-3.5" style={{ color }} />
                  </div>
                  <span className="text-xs sm:text-sm font-bold truncate" style={{ color: 'var(--text-primary)' }}>
                    {label}
                  </span>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                  {isList && Array.isArray(value) && (
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full" style={{ background: 'var(--bg-active)', color: 'var(--text-muted)' }}>
                      {value.length} items
                    </span>
                  )}
                  {isOpen ? <ChevronDown className="w-4 h-4 text-indigo-400" /> : <ChevronRight className="w-4 h-4 opacity-50" />}
                </div>
              </button>

              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ type: 'spring', bounce: 0, duration: 0.25 }}
                    className="overflow-hidden"
                  >
                    <div className="px-5 pb-5 pt-1">
                      {isList && Array.isArray(value) ? (
                        <div className="space-y-2.5">
                          {(value as string[]).map((item, i) => (
                            <div
                              key={i}
                              className="flex items-start gap-3 p-3.5 rounded-xl border text-xs leading-relaxed"
                              style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
                            >
                              <span
                                className="w-5 h-5 rounded-md flex items-center justify-center flex-shrink-0 text-[10px] font-mono font-bold mt-0.5"
                                style={{ background: `${color}20`, color }}
                              >
                                {i + 1}
                              </span>
                              <p className="flex-1" style={{ color: 'var(--text-primary)' }}>{item}</p>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div
                          className="p-4 rounded-xl border leading-relaxed text-xs sm:text-sm space-y-2.5"
                          style={{ background: 'var(--bg-card)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
                        >
                          {(value as string).split('\n\n').map((para, pi) => (
                            <p key={pi} className="leading-relaxed">{para}</p>
                          ))}
                        </div>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}
