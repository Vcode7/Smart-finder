'use client';

import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useResearchStore } from '@/store/research';
import { toast } from 'sonner';
import {
  Zap, FileText, Hash, BarChart2, Quote, Users,
  AlertTriangle, HelpCircle, MessageSquare, GitCompare, X,
  Sparkles, CornerDownLeft
} from 'lucide-react';
import type { Source, InsightAction } from '@/types/research';

interface SourceContextMenuProps {
  source: Source;
  sessionId: string;
  x: number;
  y: number;
  onClose: () => void;
}

const ACTIONS: Array<{ action: InsightAction; label: string; icon: React.ElementType; desc: string; color: string }> = [
  { action: 'summarize', label: 'Summarize Key Content', icon: Zap, desc: 'Generate concise executive brief', color: '#6366f1' },
  { action: 'explain', label: 'Explain for Beginners', icon: FileText, desc: 'Plain-English concept breakdown', color: '#06b6d4' },
  { action: 'extract_facts', label: 'Extract Verifiable Facts', icon: Hash, desc: 'Core facts and verifiable data', color: '#10b981' },
  { action: 'extract_statistics', label: 'Extract Quantitative Data', icon: BarChart2, desc: 'Percentages, metrics and tables', color: '#f59e0b' },
  { action: 'find_claims', label: 'Analyze Key Claims', icon: Quote, desc: 'Underlying assertions & hypotheses', color: '#a855f7' },
  { action: 'find_people_orgs', label: 'Find Entities & Institutions', icon: Users, desc: 'Key figures and organizations', color: '#ec4899' },
  { action: 'find_contradictions', label: 'Detect Inconsistencies', icon: AlertTriangle, desc: 'Internal friction and opposing claims', color: '#f43f5e' },
  { action: 'why_important', label: 'Why Is This Significant?', icon: HelpCircle, desc: 'Contextual significance analysis', color: '#eab308' },
  { action: 'ask_question', label: 'Ask a Targeted Question', icon: MessageSquare, desc: 'Specific query against source', color: '#3b82f6' },
  { action: 'compare', label: 'Compare with Research Topic', icon: GitCompare, desc: 'Relevance to overall topic', color: '#14b8a6' },
];

export function SourceContextMenu({ source, sessionId, x, y, onClose }: SourceContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState<InsightAction | null>(null);
  const [result, setResult] = useState<{ action: InsightAction; text: string } | null>(null);
  const [customQuestion, setCustomQuestion] = useState('');
  const [showQuestionInput, setShowQuestionInput] = useState(false);

  // Position adjustment within viewport
  const [pos, setPos] = useState({ x, y });
  useEffect(() => {
    const el = menuRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    setPos({
      x: x + rect.width > vw ? Math.max(10, vw - rect.width - 20) : x,
      y: y + rect.height > vh ? Math.max(10, vh - rect.height - 20) : y,
    });
  }, [x, y]);

  // Click outside listener
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    window.addEventListener('mousedown', handler);
    return () => window.removeEventListener('mousedown', handler);
  }, [onClose]);

  const runAction = async (action: InsightAction, q?: string) => {
    setLoading(action);
    setResult(null);
    try {
      const res = await fetch('/api/insights', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, source, question: q }),
      });
      if (!res.ok) throw new Error('Insight failed');
      const data = await res.json();
      setResult({ action, text: data.result });
    } catch {
      toast.error('Failed to generate insight');
    } finally {
      setLoading(null);
      setShowQuestionInput(false);
    }
  };

  return (
    <div
      ref={menuRef}
      className="fixed z-50 w-80 rounded-2xl border shadow-2xl overflow-hidden backdrop-blur-2xl animate-in fade-in zoom-in-95 duration-150"
      style={{
        left: pos.x,
        top: pos.y,
        background: 'var(--bg-elevated)',
        borderColor: 'var(--border)',
        boxShadow: '0 20px 50px rgba(0, 0, 0, 0.65), 0 0 20px rgba(99, 102, 241, 0.15)',
      }}
    >
      {/* Menu Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b"
        style={{
          background: 'linear-gradient(90deg, rgba(99,102,241,0.15) 0%, rgba(168,85,247,0.15) 100%)',
          borderColor: 'var(--border)',
        }}
      >
        <div className="flex items-center gap-2">
          <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
          <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
            Right-Click AI Intelligence
          </span>
        </div>
        <button onClick={onClose} className="p-1 rounded-lg hover:bg-black/20 text-muted-foreground hover:text-foreground">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Target Source Identifier */}
      <div className="px-4 py-2 border-b" style={{ background: 'var(--bg-card)', borderColor: 'var(--border-subtle)' }}>
        <p className="text-[11px] font-semibold truncate leading-tight" style={{ color: 'var(--text-secondary)' }}>
          Target: {source.title}
        </p>
      </div>

      {/* Generated Result Viewport */}
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-b overflow-hidden"
            style={{ borderColor: 'var(--border)', background: 'var(--bg-base)' }}
          >
            <div className="p-4 max-h-48 overflow-y-auto space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-400">
                  Analysis Output
                </span>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(result.text);
                    toast.success('Copied output');
                  }}
                  className="text-[10px] text-muted-foreground hover:text-foreground"
                >
                  Copy
                </button>
              </div>
              <p className="text-xs leading-relaxed" style={{ color: 'var(--text-primary)' }}>
                {result.text}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Custom Question Sub-Form */}
      {showQuestionInput && (
        <div className="p-3 border-b" style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (customQuestion.trim()) runAction('ask_question', customQuestion.trim());
            }}
            className="flex items-center gap-2"
          >
            <input
              value={customQuestion}
              onChange={(e) => setCustomQuestion(e.target.value)}
              placeholder="Type your question..."
              className="flex-1 px-2.5 py-1.5 rounded-xl border text-xs bg-[var(--bg-base)] outline-none"
              style={{ color: 'var(--text-primary)', borderColor: 'var(--border)' }}
              autoFocus
            />
            <button
              type="submit"
              disabled={!customQuestion.trim() || !!loading}
              className="p-1.5 rounded-xl bg-indigo-600 text-white disabled:opacity-40"
            >
              <CornerDownLeft className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      )}

      {/* Action Options List */}
      <div className="max-h-64 overflow-y-auto p-1.5 space-y-0.5">
        {ACTIONS.map(({ action, label, icon: Icon, desc, color }) => (
          <button
            key={action}
            onClick={() => {
              if (action === 'ask_question') {
                setShowQuestionInput(!showQuestionInput);
              } else {
                runAction(action);
              }
            }}
            disabled={!!loading}
            className="w-full flex items-center gap-3 p-2 rounded-xl text-left transition-all hover:bg-[var(--bg-hover)] group"
          >
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 transition-transform group-hover:scale-110"
              style={{ background: `${color}18`, color }}
            >
              {loading === action ? (
                <div className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
              ) : (
                <Icon className="w-3.5 h-3.5" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-bold leading-tight" style={{ color: 'var(--text-primary)' }}>
                {label}
              </p>
              <p className="text-[10px] text-muted-foreground truncate">{desc}</p>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
