'use client';
// src/components/modals/SettingsModal.tsx — Ollama Configuration & Local/Cloud LLM Routing Settings

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  Settings,
  Cpu,
  Server,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  Zap,
  HardDrive,
  Layers,
  ChevronDown,
  ExternalLink,
  ShieldCheck,
  Sparkles,
  Loader2,
  Check
} from 'lucide-react';
import { useUIStore } from '@/store/ui';
import { toast } from 'sonner';

interface OllamaModel {
  name: string;
  model: string;
  size_bytes?: number;
  size_formatted: string;
  family: string;
  parameter_size: string;
  quantization_level: string;
  modified_at: string;
}

interface OllamaSettingsData {
  endpoint: string;
  connected: boolean;
  models: OllamaModel[];
  selected_model: string;
  active_provider: string;
  active_model: string;
  fallback_provider: string;
  fallback_model: string;
  error?: string | null;
}

interface TestResult {
  success: boolean;
  provider?: string;
  model?: string;
  response?: string;
  latency_ms?: number;
  error?: string;
}

export function SettingsModal() {
  const { settingsModalOpen, setSettingsModalOpen } = useUIStore();

  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const [endpoint, setEndpoint] = useState('http://localhost:11434');
  const [connected, setConnected] = useState(false);
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [activeProvider, setActiveProvider] = useState('ollama');
  const [activeModel, setActiveModel] = useState('');
  const [fallbackModel, setFallbackModel] = useState('llama-3.3-70b-versatile');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/settings/ollama');
      if (res.ok) {
        const data: OllamaSettingsData = await res.json();
        setEndpoint(data.endpoint || 'http://localhost:11434');
        setConnected(data.connected);
        setModels(data.models || []);
        setSelectedModel(data.selected_model || '');
        setActiveProvider(data.active_provider || (data.connected ? 'ollama' : 'groq'));
        setActiveModel(data.active_model || '');
        setFallbackModel(data.fallback_model || 'llama-3.3-70b-versatile');
        setErrorMsg(data.error || null);
      } else {
        toast.error('Failed to load Ollama settings');
      }
    } catch (err: any) {
      toast.error(err.message || 'Error fetching Ollama status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (settingsModalOpen) {
      fetchSettings();
      setTestResult(null);
    }
  }, [settingsModalOpen, fetchSettings]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const res = await fetch('/api/settings/ollama/refresh', { method: 'POST' });
      if (res.ok) {
        const data: OllamaSettingsData = await res.json();
        setConnected(data.connected);
        setModels(data.models || []);
        setSelectedModel(data.selected_model || '');
        setActiveProvider(data.active_provider);
        setActiveModel(data.active_model);
        setErrorMsg(data.error || null);
        toast.success(
          data.connected
            ? `Discovered ${data.models.length} Ollama model${data.models.length === 1 ? '' : 's'}`
            : 'Ollama endpoint is unreachable'
        );
      }
    } catch {
      toast.error('Failed to refresh models');
    } finally {
      setRefreshing(false);
    }
  };

  const handleSaveModel = async (newModel: string) => {
    setSelectedModel(newModel);
    setSaving(true);
    try {
      const res = await fetch('/api/settings/ollama', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected_model: newModel }),
      });
      if (res.ok) {
        const data: OllamaSettingsData = await res.json();
        setSelectedModel(data.selected_model);
        setActiveProvider(data.active_provider);
        setActiveModel(data.active_model);
        toast.success(`Selected model updated: ${newModel}`);
      }
    } catch {
      toast.error('Failed to update selected model');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveEndpoint = async () => {
    setSaving(true);
    try {
      const res = await fetch('/api/settings/ollama', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint: endpoint.trim() }),
      });
      if (res.ok) {
        const data: OllamaSettingsData = await res.json();
        setConnected(data.connected);
        setModels(data.models || []);
        setSelectedModel(data.selected_model);
        setActiveProvider(data.active_provider);
        toast.success('Ollama endpoint updated');
      }
    } catch {
      toast.error('Failed to update endpoint');
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch('/api/settings/ollama/test', { method: 'POST' });
      const data: TestResult = await res.json();
      setTestResult(data);
      if (data.success) {
        toast.success(`Test passed via ${data.provider?.toUpperCase()} (${data.latency_ms}ms)`);
      } else {
        toast.error(`Test failed: ${data.error || 'Unknown error'}`);
      }
    } catch (err: any) {
      setTestResult({ success: false, error: err.message });
      toast.error('Test request encountered an error');
    } finally {
      setTesting(false);
    }
  };

  if (!settingsModalOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 md:p-8">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => setSettingsModalOpen(false)}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm"
        />

        {/* Modal Window */}
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 10 }}
          transition={{ type: 'spring', duration: 0.3 }}
          className="relative w-full max-w-2xl rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh] z-10"
          style={{
            background: 'var(--bg-elevated, #16181d)',
            border: '1px solid var(--border, rgba(255,255,255,0.1))',
            color: 'var(--text-primary, #f3f4f6)',
          }}
        >
          {/* ─── Header ─────────────────────────────────────────── */}
          <div
            className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0"
            style={{ borderColor: 'var(--border, rgba(255,255,255,0.08))' }}
          >
            <div className="flex items-center gap-3">
              <div
                className="w-9 h-9 rounded-xl flex items-center justify-center shadow-md"
                style={{
                  background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
                }}
              >
                <Settings className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="font-bold text-base tracking-tight">Application Settings</h2>
                <p className="text-xs text-[var(--text-muted)]">
                  Configure local LLM inference via Ollama and fallback routing
                </p>
              </div>
            </div>

            <button
              onClick={() => setSettingsModalOpen(false)}
              className="p-2 rounded-xl transition-colors hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* ─── Body ───────────────────────────────────────────── */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {/* Section: Ollama Configuration */}
            <div
              className="p-5 rounded-2xl border space-y-5"
              style={{
                background: 'var(--bg-surface, rgba(255,255,255,0.02))',
                borderColor: 'var(--border, rgba(255,255,255,0.08))',
              }}
            >
              {/* Title & Connection Status */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <Cpu className="w-5 h-5 text-indigo-400" />
                  <span className="font-semibold text-sm">Ollama Configuration</span>
                </div>

                {/* Status Badge */}
                <div className="flex items-center gap-2">
                  {connected ? (
                    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
                      <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                      Connected
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/20">
                      <span className="w-2 h-2 rounded-full bg-amber-400" />
                      Not Connected
                    </span>
                  )}
                </div>
              </div>

              {/* Endpoint Input */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--text-secondary)]">
                  Endpoint URL
                </label>
                <div className="flex items-center gap-2">
                  <div
                    className="flex-1 flex items-center gap-2 px-3 py-2 rounded-xl border bg-[var(--bg-base)] text-xs"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    <Server className="w-4 h-4 text-[var(--text-muted)] flex-shrink-0" />
                    <input
                      type="text"
                      value={endpoint}
                      onChange={(e) => setEndpoint(e.target.value)}
                      placeholder="http://localhost:11434"
                      className="w-full bg-transparent outline-none text-xs font-mono"
                    />
                  </div>
                  <button
                    onClick={handleSaveEndpoint}
                    disabled={saving}
                    className="px-3 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-all disabled:opacity-50"
                  >
                    Save
                  </button>
                  <button
                    onClick={handleRefresh}
                    disabled={refreshing}
                    title="Refresh Models"
                    className="p-2 rounded-xl border hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all flex items-center gap-1 text-xs"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    <RefreshCw
                      className={`w-4 h-4 ${refreshing ? 'animate-spin text-indigo-400' : ''}`}
                    />
                  </button>
                </div>
              </div>

              {/* Ollama Offline / Fallback Banner */}
              {!connected && (
                <motion.div
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="p-3.5 rounded-xl border flex items-start gap-3 bg-amber-500/10 border-amber-500/20 text-amber-300 text-xs leading-relaxed"
                >
                  <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5 text-amber-400" />
                  <div className="space-y-1">
                    <p className="font-semibold text-amber-200">
                      Ollama unavailable — Groq fallback will be used.
                    </p>
                    <p className="text-[11px] text-amber-300/80">
                      The application will automatically route requests to the configured Groq API (
                      <span className="font-mono text-amber-200">{fallbackModel}</span>) with no
                      interruption. Start Ollama and click Refresh to switch back to local inference.
                    </p>
                  </div>
                </motion.div>
              )}

              {/* Available Models List & Selector */}
              {connected && (
                <div className="space-y-3 pt-1">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-[var(--text-secondary)]">
                      Selected Model (Single Source of Truth)
                    </label>
                    <span className="text-[11px] text-[var(--text-muted)]">
                      {models.length} model{models.length === 1 ? '' : 's'} detected
                    </span>
                  </div>

                  {models.length === 0 ? (
                    <div
                      className="p-4 rounded-xl border text-center space-y-2 bg-[var(--bg-base)]"
                      style={{ borderColor: 'var(--border)' }}
                    >
                      <HardDrive className="w-6 h-6 mx-auto text-[var(--text-muted)]" />
                      <p className="text-xs text-[var(--text-secondary)]">
                        No models found in your Ollama installation.
                      </p>
                      <p className="text-[11px] text-[var(--text-muted)]">
                        Run <code className="px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] font-mono">ollama pull &lt;model&gt;</code> in your terminal, then click Refresh.
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {/* Model Selector Dropdown */}
                      <div className="relative">
                        <select
                          value={selectedModel}
                          onChange={(e) => handleSaveModel(e.target.value)}
                          disabled={saving}
                          className="w-full appearance-none px-3.5 py-2.5 rounded-xl border bg-[var(--bg-base)] text-xs font-medium cursor-pointer outline-none transition-all focus:border-indigo-500 pr-9"
                          style={{ borderColor: 'var(--border)' }}
                        >
                          {models.map((m) => (
                            <option key={m.name} value={m.name}>
                              {m.name} ({m.size_formatted || 'Local'})
                            </option>
                          ))}
                        </select>
                        <ChevronDown className="w-4 h-4 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-[var(--text-muted)]" />
                      </div>

                      {/* Model Cards / Details */}
                      <div className="grid grid-cols-1 gap-2 pt-1">
                        {models.map((m) => {
                          const isSelected = selectedModel === m.name;
                          return (
                            <div
                              key={m.name}
                              onClick={() => handleSaveModel(m.name)}
                              className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-all ${
                                isSelected
                                  ? 'border-indigo-500/60 bg-indigo-500/10'
                                  : 'hover:border-[var(--border)] hover:bg-[var(--bg-hover)]'
                              }`}
                              style={{
                                borderColor: isSelected ? undefined : 'var(--border)',
                              }}
                            >
                              <div className="flex items-center gap-3 min-w-0">
                                <div
                                  className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${
                                    isSelected
                                      ? 'bg-indigo-600 text-white'
                                      : 'bg-[var(--bg-base)] text-[var(--text-muted)]'
                                  }`}
                                >
                                  {isSelected ? (
                                    <Check className="w-4 h-4" />
                                  ) : (
                                    <Cpu className="w-3.5 h-3.5" />
                                  )}
                                </div>
                                <div className="min-w-0">
                                  <p className="text-xs font-semibold truncate leading-tight">
                                    {m.name}
                                  </p>
                                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                                    {m.family && (
                                      <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-[var(--bg-base)] text-indigo-400 font-bold border border-indigo-500/20">
                                        {m.family}
                                      </span>
                                    )}
                                    {m.parameter_size && (
                                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-base)] text-[var(--text-secondary)]">
                                        {m.parameter_size}
                                      </span>
                                    )}
                                    {m.quantization_level && m.quantization_level !== 'unknown' && (
                                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-base)] text-[var(--text-muted)]">
                                        {m.quantization_level}
                                      </span>
                                    )}
                                    <span className="text-[10px] text-[var(--text-muted)]">
                                      {m.size_formatted}
                                    </span>
                                  </div>
                                </div>
                              </div>

                              {isSelected && (
                                <span className="text-[10px] font-semibold text-indigo-400 px-2 py-0.5 rounded-full bg-indigo-500/15 border border-indigo-500/20 flex-shrink-0">
                                  Active
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Active Routing Summary Card */}
              <div
                className="p-3.5 rounded-xl border flex items-center justify-between text-xs bg-[var(--bg-base)]"
                style={{ borderColor: 'var(--border)' }}
              >
                <div className="space-y-0.5">
                  <p className="text-[11px] font-medium text-[var(--text-muted)]">Active LLM Provider</p>
                  <p className="font-semibold flex items-center gap-1.5">
                    {connected && selectedModel ? (
                      <>
                        <Zap className="w-3.5 h-3.5 text-emerald-400" />
                        <span className="text-emerald-400">Ollama Local</span>
                        <span className="text-[var(--text-muted)] font-mono text-[11px]">
                          ({selectedModel})
                        </span>
                      </>
                    ) : (
                      <>
                        <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
                        <span className="text-indigo-400">Groq Cloud API</span>
                        <span className="text-[var(--text-muted)] font-mono text-[11px]">
                          ({fallbackModel})
                        </span>
                      </>
                    )}
                  </p>
                </div>

                <button
                  onClick={handleTestConnection}
                  disabled={testing}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[var(--bg-elevated)] hover:bg-[var(--bg-hover)] border transition-all disabled:opacity-50"
                  style={{ borderColor: 'var(--border)' }}
                >
                  {testing ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-400" />
                  ) : (
                    <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                  )}
                  {testing ? 'Testing...' : 'Test Connection'}
                </button>
              </div>

              {/* Test Connection Output Box */}
              {testResult && (
                <motion.div
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`p-3.5 rounded-xl border text-xs space-y-1.5 ${
                    testResult.success
                      ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300'
                      : 'bg-red-500/10 border-red-500/20 text-red-300'
                  }`}
                >
                  <div className="flex items-center justify-between font-semibold">
                    <span className="flex items-center gap-1.5">
                      {testResult.success ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      ) : (
                        <AlertTriangle className="w-4 h-4 text-red-400" />
                      )}
                      {testResult.success ? 'Inference Test Succeeded' : 'Inference Test Failed'}
                    </span>
                    {testResult.latency_ms && (
                      <span className="text-[10px] font-mono opacity-80">
                        {testResult.latency_ms} ms
                      </span>
                    )}
                  </div>
                  {testResult.success ? (
                    <div className="text-[11px] opacity-90 space-y-0.5">
                      <p>
                        Provider: <strong className="uppercase">{testResult.provider}</strong> | Model:{' '}
                        <code className="font-mono">{testResult.model}</code>
                      </p>
                      {testResult.response && (
                        <p className="italic bg-black/20 p-2 rounded border border-emerald-500/10 mt-1">
                          "{testResult.response}"
                        </p>
                      )}
                    </div>
                  ) : (
                    <p className="text-[11px] opacity-90">{testResult.error}</p>
                  )}
                </motion.div>
              )}
            </div>

            {/* Architecture Explainer Card */}
            <div
              className="p-4 rounded-2xl border text-xs space-y-2 bg-[var(--bg-surface)]"
              style={{ borderColor: 'var(--border)' }}
            >
              <div className="flex items-center gap-2 text-[var(--text-secondary)] font-semibold">
                <Layers className="w-4 h-4 text-indigo-400" />
                <span>Automatic Routing Priority</span>
              </div>
              <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)] font-mono">
                <span className="px-2 py-1 rounded bg-[var(--bg-base)] text-emerald-400 font-semibold border border-emerald-500/20">
                  1. Ollama (Selected Local Model)
                </span>
                <span>→</span>
                <span className="px-2 py-1 rounded bg-[var(--bg-base)] text-indigo-400 font-semibold border border-indigo-500/20">
                  2. Groq Cloud Fallback
                </span>
              </div>
              <p className="text-[11px] text-[var(--text-muted)] leading-relaxed">
                All features (multimodal research, search synthesis, chat generation, and entity analysis) route through this unified layer. If Ollama is offline or the model is unavailable, Groq takes over automatically without requiring configuration changes.
              </p>
            </div>
          </div>

          {/* ─── Footer ─────────────────────────────────────────── */}
          <div
            className="flex items-center justify-between px-6 py-4 border-t flex-shrink-0 bg-[var(--bg-surface)]"
            style={{ borderColor: 'var(--border)' }}
          >
            <span className="text-[11px] text-[var(--text-muted)]">
              Smart Finder AI • LLM Router
            </span>
            <button
              onClick={() => setSettingsModalOpen(false)}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-all shadow-md"
            >
              Done
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}

export default SettingsModal;
