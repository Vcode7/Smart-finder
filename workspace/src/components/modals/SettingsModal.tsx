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
  ShieldCheck,
  Sparkles,
  Loader2,
  Check,
  KeyRound,
  Lock
} from 'lucide-react';
import { useUIStore } from '@/store/ui';
import { useAuthStore } from '@/store/auth';
import { toast } from 'sonner';
import { apiErrorMessage, readJson } from '@/lib/utils/api';
import CatalogSettingsSection, { saveCatalogChanges } from '@/components/modals/CatalogSettingsSection';

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

function AccountSection() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [saving, setSaving] = useState(false);

  const handleChangePassword = async () => {
    if (newPassword.length < 8) { toast.error('The new password must be at least 8 characters'); return; }
    if (newPassword !== confirmPassword) { toast.error('The new passwords do not match'); return; }
    setSaving(true);
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ currentPassword, newPassword }),
      });
      if (!res.ok) {
        toast.error(apiErrorMessage(await readJson(res), 'Could not change the password'));
        return;
      }
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('');
      toast.success('Password changed');
    } catch {
      toast.error('Could not change the password');
    } finally {
      setSaving(false);
    }
  };

  const inputClass = 'w-full px-3 py-2 rounded-xl border bg-[var(--bg-base)] text-xs outline-none';
  return (
    <div className="p-5 rounded-2xl border space-y-4" style={{ background: 'var(--bg-surface, rgba(255,255,255,0.02))', borderColor: 'var(--border, rgba(255,255,255,0.08))' }}>
      <div className="flex items-center gap-2.5">
        <KeyRound className="w-5 h-5 text-indigo-400" />
        <span className="font-semibold text-sm">Account</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <input type="password" autoComplete="current-password" placeholder="Current password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} className={inputClass} style={{ borderColor: 'var(--border)' }} />
        <input type="password" autoComplete="new-password" placeholder="New password (8+ characters)" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className={inputClass} style={{ borderColor: 'var(--border)' }} />
        <input type="password" autoComplete="new-password" placeholder="Confirm new password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className={inputClass} style={{ borderColor: 'var(--border)' }} />
      </div>
      <div className="flex justify-end">
        <button type="button" onClick={handleChangePassword} disabled={saving || !currentPassword || !newPassword}
          className="px-4 py-2 rounded-xl text-xs font-semibold text-white disabled:opacity-50" style={{ background: 'var(--accent)' }}>
          {saving ? 'Saving...' : 'Change password'}
        </button>
      </div>
    </div>
  );
}

export function SettingsModal() {
  const { settingsModalOpen, setSettingsModalOpen } = useUIStore();
  // Changing or testing the model is admin-only on the backend
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin');

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

  const applyStatus = useCallback((data: OllamaSettingsData) => {
    setEndpoint(data.endpoint || 'http://localhost:11434');
    setConnected(data.connected);
    setModels(data.models || []);
    setSelectedModel(data.selected_model || '');
    setActiveProvider(data.active_provider || (data.connected ? 'ollama' : 'groq'));
    setActiveModel(data.active_model || '');
    setFallbackModel(data.fallback_model || 'llama-3.3-70b-versatile');
    setErrorMsg(data.error || null);
  }, []);

  useEffect(() => {
    if (!settingsModalOpen) return;
    let current = true;
    fetch('/api/settings/ollama')
      .then(async (res) => {
        const data = await readJson<OllamaSettingsData>(res);
        if (!res.ok || !data) throw new Error(apiErrorMessage(data, 'Failed to load Ollama settings'));
        if (current) applyStatus(data);
      })
      .catch((err) => { if (current) toast.error(err instanceof Error ? err.message : 'Error fetching Ollama status'); });
    return () => { current = false; };
  }, [settingsModalOpen, applyStatus]);

  // Done, ✕ and Esc first save Library Integrations left unsaved; a failed save keeps Settings open
  const [closing, setClosing] = useState(false);
  const close = useCallback(async () => {
    setClosing(true);
    const saved = await saveCatalogChanges();
    setClosing(false);
    if (!saved) return;
    setSettingsModalOpen(false);
    setTestResult(null);
  }, [setSettingsModalOpen]);

  useEffect(() => {
    if (!settingsModalOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [settingsModalOpen, close]);

  // POST to a settings route; the backend answers with the full status
  const postSettings = async (url: string, body?: object): Promise<OllamaSettingsData> => {
    const res = await fetch(url, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await readJson<OllamaSettingsData>(res);
    if (!res.ok || !data) throw new Error(apiErrorMessage(data, `Request failed (${res.status})`));
    return data;
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const data = await postSettings('/api/settings/ollama/refresh');
      applyStatus(data);
      toast.success(
        data.connected
          ? `Discovered ${data.models.length} Ollama model${data.models.length === 1 ? '' : 's'}`
          : 'Ollama endpoint is unreachable'
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to refresh models');
    } finally {
      setRefreshing(false);
    }
  };

  const handleSaveModel = async (newModel: string) => {
    if (newModel === selectedModel) return;
    const previous = selectedModel;
    setSelectedModel(newModel);
    setSaving(true);
    try {
      applyStatus(await postSettings('/api/settings/ollama', { selected_model: newModel }));
      toast.success(`Selected model updated: ${newModel}`);
    } catch (err) {
      setSelectedModel(previous);
      toast.error(err instanceof Error ? err.message : 'Failed to update selected model');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveEndpoint = async () => {
    setSaving(true);
    try {
      applyStatus(await postSettings('/api/settings/ollama', { endpoint: endpoint.trim() }));
      toast.success('Ollama endpoint updated');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update endpoint');
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch('/api/settings/ollama/test', { method: 'POST' });
      const data = await readJson<TestResult>(res);
      if (!res.ok || !data) throw new Error(apiErrorMessage(data, `Request failed (${res.status})`));
      setTestResult(data);
      if (data.success) {
        toast.success(`Test passed via ${data.provider?.toUpperCase()} (${data.latency_ms}ms)`);
      } else {
        toast.error(`Test failed: ${data.error || 'Unknown error'}`);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Test request encountered an error';
      setTestResult({ success: false, error: message });
      toast.error(message);
    } finally {
      setTesting(false);
    }
  };

  if (!settingsModalOpen) return null;

  const usingOllama = activeProvider === 'ollama';

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 md:p-8">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={close}
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
              onClick={close}
              aria-label="Close settings"
              className="p-2 rounded-xl transition-colors hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* ─── Body ───────────────────────────────────────────── */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <AccountSection />

            {isAdmin && <CatalogSettingsSection />}

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

              {!isAdmin && (
                <p className="flex items-center gap-2 text-[11px] px-3 py-2 rounded-xl"
                  style={{ background: 'var(--bg-base)', color: 'var(--text-muted)' }}>
                  <Lock className="w-3.5 h-3.5 flex-shrink-0" />
                  Only an administrator can change or test the AI model.
                </p>
              )}

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
                      disabled={!isAdmin}
                      aria-label="Ollama endpoint URL"
                      className="w-full bg-transparent outline-none text-xs font-mono disabled:opacity-60"
                    />
                  </div>
                  <button
                    onClick={handleSaveEndpoint}
                    disabled={saving || !isAdmin}
                    className="px-3 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-all disabled:opacity-50"
                  >
                    Save
                  </button>
                  <button
                    onClick={handleRefresh}
                    disabled={refreshing || !isAdmin}
                    title="Refresh Models"
                    aria-label="Refresh models"
                    className="p-2 rounded-xl border hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all flex items-center gap-1 text-xs disabled:opacity-50"
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
                    {errorMsg && (
                      <p className="text-[11px] font-mono break-all opacity-80">{errorMsg}</p>
                    )}
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
                          disabled={saving || !isAdmin}
                          aria-label="Selected Ollama model"
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
                            <button
                              type="button"
                              key={m.name}
                              onClick={() => handleSaveModel(m.name)}
                              disabled={saving || !isAdmin}
                              aria-pressed={isSelected}
                              className={`w-full text-left flex items-center justify-between p-3 rounded-xl border transition-all enabled:cursor-pointer disabled:cursor-default ${
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
                            </button>
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
                    {usingOllama ? (
                      <>
                        <Zap className="w-3.5 h-3.5 text-emerald-400" />
                        <span className="text-emerald-400">Ollama Local</span>
                        <span className="text-[var(--text-muted)] font-mono text-[11px]">
                          ({activeModel || selectedModel})
                        </span>
                      </>
                    ) : (
                      <>
                        <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
                        <span className="text-indigo-400">Groq Cloud API</span>
                        <span className="text-[var(--text-muted)] font-mono text-[11px]">
                          ({activeModel || fallbackModel})
                        </span>
                      </>
                    )}
                  </p>
                </div>

                <button
                  onClick={handleTestConnection}
                  disabled={testing || !isAdmin}
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
                          &ldquo;{testResult.response}&rdquo;
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
              onClick={close}
              disabled={closing}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-all shadow-md disabled:opacity-60"
            >
              {closing ? 'Saving…' : 'Done'}
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}

export default SettingsModal;
