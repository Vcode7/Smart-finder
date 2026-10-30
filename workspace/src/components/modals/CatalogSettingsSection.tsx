'use client';
// Library Integrations (admin only): the Koha catalog and DSpace repository that Smart Finder can
// search next to the local libraries. Secrets are never sent back by the server; leaving the
// field blank keeps the stored one.
//
// Each form has its own Save, and closing Settings (Done, ✕, Esc) saves whatever was left unsaved:
// see saveCatalogChanges.

import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Library, Loader2, Server, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { apiErrorMessage, readJson } from '@/lib/utils/api';
import { useSearchSourcesStore } from '@/store/searchSources';

type CatalogId = 'koha' | 'dspace';

interface CatalogConfig {
  source: CatalogId;
  label: string;
  available: boolean;
  enabled: boolean;
  baseUrl: string;
  apiUrl?: string;
  uiUrl?: string;
  authType?: 'none' | 'basic' | 'oauth2';
  username?: string;
  hasSecret?: boolean;
  /** The public demo server searched until an admin gives their own URL */
  demoUrl?: string;
  timeout: number;
  maxResults: number;
}

interface TestResult {
  success: boolean;
  latency_ms?: number;
  error?: string;
  version?: string | null;
  records?: number;
  total?: number | null;
  sample?: string | null;
}

const HELP: Record<CatalogId, { url: string; placeholder: string }> = {
  koha: { url: 'OPAC URL', placeholder: 'https://opac.library.example.org' },
  dspace: { url: 'REST API URL (ends in /server)', placeholder: 'https://repository.example.org/server' },
};

// The save of every form that has unsaved changes, so closing Settings can save them too
const pendingSaves = new Map<CatalogId, () => Promise<boolean>>();

/** Save the forms with unsaved changes. False when one could not be saved (its error is shown). */
export async function saveCatalogChanges(): Promise<boolean> {
  const results = await Promise.all([...pendingSaves.values()].map((save) => save()));
  return results.every(Boolean);
}

const bodyOf = (c: CatalogConfig, secret: string) => ({
  enabled: c.enabled, baseUrl: c.baseUrl.trim(), timeout: Number(c.timeout), maxResults: Number(c.maxResults),
  ...(c.source === 'koha'
    ? { apiUrl: (c.apiUrl ?? '').trim(), authType: c.authType ?? 'none', username: (c.username ?? '').trim(), secret }
    : { uiUrl: (c.uiUrl ?? '').trim() }),
});

export default function CatalogSettingsSection() {
  const [configs, setConfigs] = useState<CatalogConfig[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetch('/api/catalogs/settings')
      .then(async (res) => {
        const data = await readJson<{ sources: CatalogConfig[] }>(res);
        if (!res.ok || !data) throw new Error(apiErrorMessage(data, 'Could not load the library integrations'));
        if (live) setConfigs(data.sources);
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : 'Could not load the library integrations'));
    return () => { live = false; };
  }, []);

  return (
    <div className="p-5 rounded-2xl border space-y-4" style={{ background: 'var(--bg-surface, rgba(255,255,255,0.02))', borderColor: 'var(--border)' }}>
      <div className="flex items-center gap-2.5">
        <Library className="w-5 h-5 text-indigo-400" />
        <div>
          <span className="font-semibold text-sm">Library Integrations</span>
          <p className="text-[11px] text-[var(--text-muted)]">Search a Koha catalog and a DSpace repository together with local files. Internet search stays separate.</p>
        </div>
      </div>
      {error && <p className="text-xs text-amber-400">{error}</p>}
      {!configs && !error && <p className="text-xs flex items-center gap-2 text-[var(--text-muted)]"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…</p>}
      {configs?.map((c) => (
        <CatalogForm key={c.source} initial={c} onSaved={(next) => setConfigs((all) => all?.map((x) => (x.source === next.source ? next : x)) ?? null)} />
      ))}
    </div>
  );
}

function CatalogForm({ initial, onSaved }: { initial: CatalogConfig; onSaved: (c: CatalogConfig) => void }) {
  const [form, setForm] = useState({ ...initial });
  const [saved, setSaved] = useState(initial);
  const [secret, setSecret] = useState('');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);
  const set = <K extends keyof CatalogConfig>(k: K, v: CatalogConfig[K]) => setForm((f) => ({ ...f, [k]: v }));
  const isKoha = form.source === 'koha';
  const help = HELP[form.source];

  const body = () => bodyOf(form, secret);
  const dirty = JSON.stringify(body()) !== JSON.stringify(bodyOf(saved, ''));

  const setUrl = (url: string) => setForm((f) => ({
    ...f, baseUrl: url,
    // The first URL given to a source that was never set up switches it on: that is why it is typed
    ...(!saved.baseUrl && !saved.enabled ? { enabled: url.trim() !== '' } : {}),
  }));

  const save = async (): Promise<boolean> => {
    setSaving(true);
    try {
      const res = await fetch(`/api/catalogs/settings/${form.source}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body()),
      });
      const data = await readJson<CatalogConfig>(res);
      if (!res.ok || !data) throw new Error(apiErrorMessage(data, 'Could not save'));
      setForm({ ...data });
      setSaved(data);
      setSecret('');
      onSaved(data);
      useSearchSourcesStore.getState().load();
      toast.success(`${data.label} ${data.available ? 'saved: searched with your files' : data.baseUrl ? 'saved (switched off)' : 'saved'}`);
      return true;
    } catch (e) {
      toast.error(`${form.label}: ${e instanceof Error ? e.message : 'Could not save'}`);
      return false;
    } finally {
      setSaving(false);
    }
  };

  // While there are unsaved changes, closing Settings saves them (the latest form, via the ref)
  const saveRef = useRef(save);
  useEffect(() => { saveRef.current = save; });
  useEffect(() => {
    if (!dirty) return;
    pendingSaves.set(form.source, () => saveRef.current());
    return () => { pendingSaves.delete(form.source); };
  }, [dirty, form.source]);

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      const res = await fetch(`/api/catalogs/${form.source}/test`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body()),
      });
      const data = await readJson<TestResult>(res);
      if (!res.ok || !data) throw new Error(apiErrorMessage(data, `Test failed (${res.status})`));
      setTest(data);
    } catch (e) {
      setTest({ success: false, error: e instanceof Error ? e.message : 'Test failed' });
    } finally {
      setTesting(false);
    }
  };

  const input = 'w-full px-3 py-2 rounded-xl border bg-[var(--bg-base)] text-xs outline-none font-mono';
  return (
    <fieldset className="p-4 rounded-xl border space-y-3" style={{ borderColor: 'var(--border)' }}>
      <legend className="sr-only">{form.label}</legend>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold">{form.label}</span>
        <label className="flex items-center gap-2 text-[11px] text-[var(--text-secondary)] cursor-pointer">
          Search it
          <button type="button" role="switch" aria-checked={form.enabled} aria-label={`Search ${form.label}`}
            onClick={() => set('enabled', !form.enabled)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${form.enabled ? 'bg-emerald-500' : 'bg-zinc-600'}`}>
            <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${form.enabled ? 'translate-x-[18px]' : 'translate-x-1'}`} />
          </button>
        </label>
      </div>

      <label className="block space-y-1">
        <span className="text-[11px] text-[var(--text-secondary)]">{help.url}</span>
        <div className="flex items-center gap-2 px-3 rounded-xl border bg-[var(--bg-base)]" style={{ borderColor: 'var(--border)' }}>
          <Server className="w-3.5 h-3.5 text-[var(--text-muted)] flex-shrink-0" aria-hidden />
          <input value={form.baseUrl} onChange={(e) => setUrl(e.target.value)} placeholder={help.placeholder}
            className="w-full bg-transparent py-2 outline-none text-xs font-mono" />
        </div>
        {form.demoUrl && form.baseUrl.trim().replace(/\/+$/, '') === form.demoUrl && (
          <span className="block text-[11px] text-amber-400">Public demo server with sample records (slow). Replace it with your library&apos;s URL.</span>
        )}
      </label>

      {isKoha ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <label className="block space-y-1 sm:col-span-2">
            <span className="text-[11px] text-[var(--text-secondary)]">REST API URL (if not on the OPAC host)</span>
            <input value={form.apiUrl ?? ''} onChange={(e) => set('apiUrl', e.target.value)} placeholder="Same as the OPAC URL"
              className={input} style={{ borderColor: 'var(--border)' }} />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] text-[var(--text-secondary)]">API login (optional)</span>
            <select value={form.authType ?? 'none'} onChange={(e) => set('authType', e.target.value as CatalogConfig['authType'])}
              className={input} style={{ borderColor: 'var(--border)' }}>
              <option value="none">None: public OPAC and REST</option>
              <option value="basic">Basic (user and password)</option>
              <option value="oauth2">OAuth2 client credentials</option>
            </select>
          </label>
          {form.authType && form.authType !== 'none' && (
            <>
              <label className="block space-y-1">
                <span className="text-[11px] text-[var(--text-secondary)]">{form.authType === 'oauth2' ? 'Client ID' : 'User name'}</span>
                <input value={form.username ?? ''} onChange={(e) => set('username', e.target.value)} autoComplete="off"
                  className={input} style={{ borderColor: 'var(--border)' }} />
              </label>
              <label className="block space-y-1 sm:col-span-2">
                <span className="text-[11px] text-[var(--text-secondary)]">{form.authType === 'oauth2' ? 'Client secret' : 'Password'}</span>
                <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="new-password"
                  placeholder={form.hasSecret ? 'Stored (leave blank to keep it)' : ''}
                  className={input} style={{ borderColor: 'var(--border)' }} />
              </label>
            </>
          )}
        </div>
      ) : (
        <label className="block space-y-1">
          <span className="text-[11px] text-[var(--text-secondary)]">Site URL for item links (optional)</span>
          <input value={form.uiUrl ?? ''} onChange={(e) => set('uiUrl', e.target.value)} placeholder="Derived from the REST URL"
            className={input} style={{ borderColor: 'var(--border)' }} />
        </label>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <label className="space-y-1">
          <span className="block text-[11px] text-[var(--text-secondary)]">Timeout (s)</span>
          <input type="number" min={2} max={60} value={form.timeout} onChange={(e) => set('timeout', Number(e.target.value))}
            className={`${input} w-20`} style={{ borderColor: 'var(--border)' }} />
        </label>
        <label className="space-y-1">
          <span className="block text-[11px] text-[var(--text-secondary)]">Records per search</span>
          <input type="number" min={5} max={100} value={form.maxResults} onChange={(e) => set('maxResults', Number(e.target.value))}
            className={`${input} w-24`} style={{ borderColor: 'var(--border)' }} />
        </label>
        <div className="flex items-center gap-2 ml-auto">
          <button type="button" onClick={runTest} disabled={testing || !form.baseUrl.trim()}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border hover:bg-[var(--bg-hover)] disabled:opacity-50"
            style={{ borderColor: 'var(--border)' }}>
            {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5 text-indigo-400" />}
            Test
          </button>
          <button type="button" onClick={save} disabled={saving || !dirty}
            className="px-3 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50">
            {saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}
          </button>
        </div>
      </div>

      {test && (
        <p className={`flex items-start gap-1.5 text-[11px] p-2.5 rounded-xl ${test.success ? 'bg-emerald-500/10 text-emerald-300' : 'bg-red-500/10 text-red-300'}`}
          role="status">
          {test.success ? <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" /> : <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />}
          <span>
            {test.success
              ? `Connected${test.version ? ` to ${test.version}` : ''} in ${test.latency_ms} ms. A sample search found ${test.total ?? test.records ?? 0} record${(test.total ?? test.records) === 1 ? '' : 's'}${test.sample ? `, e.g. “${test.sample}”` : ''}.`
              : test.error}
          </span>
        </p>
      )}
    </fieldset>
  );
}
