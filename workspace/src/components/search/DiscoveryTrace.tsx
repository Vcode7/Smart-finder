'use client';
// src/components/search/DiscoveryTrace.tsx — Interactive visual flowchart showing the result discovery lineage:
// Uploaded Media → Signal/Face Detection → Local Match → Entity/Context Extraction → Enhanced Internet Query → Live Results

import { motion } from 'framer-motion';
import {
  Sparkles, ArrowRight, Video, FileText, Globe, UserCheck,
  Play, Eye, ExternalLink, Cpu, CheckCircle2, Search,
  Music, Image as ImageIcon, Layers, FileCode, Tag
} from 'lucide-react';

export interface DiscoveryTraceProps {
  trace: {
    inputType: 'image' | 'video' | 'audio' | 'document' | 'clipping' | 'text';
    inputName?: string;
    inputPreview?: string;
    extractedSignals: {
      hasFace?: boolean;
      faceCount?: number;
      ocrSnippet?: string;
      speechSnippet?: string;
      visualDescription?: string;
      extractedEntities?: string[];
    };
    topLocalMatch?: {
      id: string;
      sourceId: string;
      title: string;
      category: string;
      relevanceScore: number;
      timestamp?: number;
      isFaceMatch?: boolean;
      faceSimilarity?: number;
      snippet?: string;
    };
    enhancedQuery: string;
    queryVariants?: string[];
    discoveredEntities?: string[];
    contextSummary?: string;
    lineage?: Array<{
      step: number;
      title: string;
      description: string;
      badge?: string;
      type: 'upload' | 'vision_face' | 'local_match' | 'context_extraction' | 'internet_query' | 'internet_results';
    }>;
  };
  onOpenVideoTimestamp?: (sourceId: string, timestamp: number) => void;
}

function formatTime(seconds?: number): string {
  if (seconds === undefined || seconds === null) return '00:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function DiscoveryTrace({ trace, onOpenVideoTimestamp }: DiscoveryTraceProps) {
  if (!trace) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="rounded-2xl p-5 space-y-5 relative overflow-hidden shadow-2xl border"
      style={{
        background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.85) 100%)',
        borderColor: 'rgba(99, 102, 241, 0.25)',
        boxShadow: '0 12px 36px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.05)',
      }}
    >
      {/* Glow highlight */}
      <div
        className="absolute -top-24 -right-24 w-72 h-72 rounded-full pointer-events-none opacity-20 blur-3xl"
        style={{ background: 'radial-gradient(circle, #6366f1 0%, #06b6d4 100%)' }}
      />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 relative z-10">
        <div className="flex items-center gap-2.5">
          <div
            className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0 font-bold text-white shadow-md"
            style={{ background: 'linear-gradient(135deg, #6366f1, #06b6d4)' }}
          >
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <div>
            <h3 className="text-sm font-bold tracking-tight text-white flex items-center gap-2">
              <span>Multimodal Result Linking & Discovery Trace</span>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                Local → Internet Layer
              </span>
            </h3>
            <p className="text-xs text-slate-400">
              Local knowledge context discovered and refined the internet search query
            </p>
          </div>
        </div>

        {/* Input Preview Pill */}
        {trace.inputPreview && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-800/80 border border-slate-700/80 w-fit">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={trace.inputPreview}
              alt="Query input"
              className="w-6 h-6 rounded-md object-cover border border-indigo-400/40"
            />
            <span className="text-xs text-slate-300 font-medium truncate max-w-[140px]">
              {trace.inputName || 'Uploaded Query'}
            </span>
          </div>
        )}
      </div>

      {/* Flowchart Steps Progression */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 relative z-10">
        {/* Step 1: Upload & Signals */}
        <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between gap-2.5">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold uppercase text-indigo-400">Step 1 · Input Analysis</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-300">
              {trace.inputType.toUpperCase()}
            </span>
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-200">
              {trace.extractedSignals.hasFace ? 'Face & Visual Detected' : 'Multimodal Content Parsed'}
            </p>
            <p className="text-[11px] text-slate-400 mt-0.5 line-clamp-2">
              {trace.extractedSignals.faceCount
                ? `${trace.extractedSignals.faceCount} face(s) isolated and vector embedded`
                : trace.extractedSignals.ocrSnippet || trace.extractedSignals.speechSnippet || 'Extracted multimodal feature vectors'}
            </p>
          </div>
          <div className="flex flex-wrap gap-1 mt-1">
            {trace.extractedSignals.hasFace && (
              <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-md bg-pink-500/15 text-pink-300 font-medium">
                <UserCheck className="w-2.5 h-2.5" /> Face Crop
              </span>
            )}
            {trace.extractedSignals.ocrSnippet && (
              <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-md bg-amber-500/15 text-amber-300 font-medium">
                <FileText className="w-2.5 h-2.5" /> OCR
              </span>
            )}
          </div>
        </div>

        {/* Step 2: Local Knowledge Discovery */}
        <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between gap-2.5 relative">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold uppercase text-cyan-400">Step 2 · Local Retrieval</span>
            {trace.topLocalMatch && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300 font-semibold">
                {Math.round(trace.topLocalMatch.relevanceScore * 100)}% Match
              </span>
            )}
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-200 truncate">
              {trace.topLocalMatch?.title || 'Local Knowledge Base'}
            </p>
            <p className="text-[11px] text-slate-400 mt-0.5 line-clamp-2">
              {trace.topLocalMatch?.snippet || 'Matched indexed documents and multimedia items'}
            </p>
          </div>

          {/* Interactive Play Button for Video Timestamps */}
          {trace.topLocalMatch?.timestamp !== undefined && onOpenVideoTimestamp && (
            <button
              onClick={() => onOpenVideoTimestamp(trace.topLocalMatch!.sourceId, trace.topLocalMatch!.timestamp!)}
              className="flex items-center justify-center gap-1.5 w-full py-1.5 rounded-lg text-[11px] font-semibold text-cyan-300 bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/30 transition-all"
            >
              <Play className="w-3 h-3 fill-current" />
              <span>Jump to {formatTime(trace.topLocalMatch.timestamp)}</span>
            </button>
          )}
        </div>

        {/* Step 3: Context & Entity Discovery */}
        <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between gap-2.5">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold uppercase text-amber-400">Step 3 · Context Extraction</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 font-semibold">
              Discovered
            </span>
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-200">
              Discovered Entities & Topics
            </p>
            <div className="flex flex-wrap gap-1 mt-1.5">
              {(trace.discoveredEntities && trace.discoveredEntities.length > 0
                ? trace.discoveredEntities
                : ['Identified Identity', 'Subject Context']
              ).slice(0, 3).map((ent, idx) => (
                <span
                  key={idx}
                  className="text-[10px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20 font-medium truncate max-w-[130px]"
                >
                  {ent}
                </span>
              ))}
            </div>
          </div>
          <p className="text-[10px] text-slate-400">Contextual entities generated from local match</p>
        </div>

        {/* Step 4: Enhanced Internet Query */}
        <div className="p-3.5 rounded-xl bg-slate-900/60 border border-indigo-500/30 flex flex-col justify-between gap-2.5 relative shadow-inner">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold uppercase text-emerald-400">Step 4 · Internet Search</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 font-semibold flex items-center gap-1">
              <Globe className="w-2.5 h-2.5" /> Enriched Query
            </span>
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold text-slate-400">Target Query:</p>
            <p className="text-xs font-bold text-emerald-300 truncate mt-0.5">
              &quot;{trace.enhancedQuery}&quot;
            </p>
            <p className="text-[10px] text-slate-400 mt-1">
              Live Web, News, Papers, Videos & Images
            </p>
          </div>
          <div className="flex items-center gap-1 text-[10px] text-emerald-400 font-medium">
            <CheckCircle2 className="w-3 h-3" />
            <span>Multi-Registry Live Search</span>
          </div>
        </div>
      </div>

      {/* Context Summary Narrative */}
      {trace.contextSummary && (
        <div className="px-4 py-3 rounded-xl bg-indigo-950/40 border border-indigo-500/20 flex items-start gap-2.5 text-xs text-indigo-200">
          <Cpu className="w-4 h-4 text-indigo-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1 leading-relaxed">
            <span className="font-semibold text-white">Discovery Lineage: </span>
            {trace.contextSummary}
          </div>
        </div>
      )}
    </motion.div>
  );
}

export default DiscoveryTrace;
