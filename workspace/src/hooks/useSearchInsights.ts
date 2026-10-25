'use client';
// src/hooks/useSearchInsights.ts
// Runs the search page's background work once its results are on screen: topics for the
// result cards, the Dashboard data, and the Summary job. The three are independent (each has
// its own request, loading and error state) and none of them delays or blocks the results.
// A new search, or leaving the page, aborts the requests and cancels a summary still running.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchViewStore } from '@/store/searchView';
import type { AsyncData, DashboardData, FileTopics, SummaryJob } from '@/types/insights';

export interface InsightFileRef {
  libraryId?: string | null;
  sourceId: string;
}

const JSON_HEADERS = { 'Content-Type': 'application/json' };
const POLL_FAST_MS = 1500;
const POLL_SLOW_MS = 4000;
const FAST_POLLS = 20;

async function failure(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body?.detail) return String(body.detail);
  } catch { /* not JSON */ }
  return `Request failed (${res.status})`;
}

function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError';
}

/** The value, once it has stopped changing for `ms`. */
function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

interface Result<T> {
  key: string;            // the request this answers: search id plus whatever else it depends on
  searchId: string;
  data: T | null;
  error: string | null;
}

/** Loading until a result for the current key arrives; the previous search's data is never shown. */
function settle<T>(searchId: string | null, key: string, last: Result<T> | null): AsyncData<T> {
  if (!searchId) return { status: 'idle', data: null, error: null };
  const sameSearch = last && last.searchId === searchId;
  if (sameSearch && last.key === key) {
    return last.error
      ? { status: 'error', data: null, error: last.error }
      : { status: 'ready', data: last.data, error: null };
  }
  return { status: 'loading', data: sameSearch ? last.data : null, error: null };
}

export function useSearchInsights(searchId: string | null, query: string, files: InsightFileRef[]) {
  const threshold = useSearchViewStore((s) => s.dashboardThreshold);
  const debouncedThreshold = useDebounced(threshold, 300);

  const [dashNonce, setDashNonce] = useState(0);
  const [sumNonce, setSumNonce] = useState(0);
  const [dashRes, setDashRes] = useState<Result<DashboardData> | null>(null);
  const [sumRes, setSumRes] = useState<Result<SummaryJob> | null>(null);
  const [topicsRes, setTopicsRes] = useState<{ searchId: string; map: Record<string, FileTopics> } | null>(null);

  // ── topics for the result cards ────────────────────────────────────────────
  const filesKey = useMemo(() => files.map((f) => f.sourceId).join(','), [files]);
  useEffect(() => {
    if (!searchId || !filesKey) return;
    const ctl = new AbortController();
    const id = searchId;
    fetch('/api/search/topics', {
      method: 'POST', headers: JSON_HEADERS, signal: ctl.signal,
      body: JSON.stringify({ searchId: id, ids: files.map((f) => ({ libraryId: f.libraryId ?? null, sourceId: f.sourceId })) }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { topics?: Record<string, FileTopics> } | null) => {
        if (d?.topics) setTopicsRes({ searchId: id, map: d.topics });
      })
      .catch(() => { /* topics are a nicety: cards simply show none */ });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchId, filesKey]);

  // ── dashboard ──────────────────────────────────────────────────────────────
  const dashKey = `${searchId}|${debouncedThreshold}|${dashNonce}`;
  useEffect(() => {
    if (!searchId) return;
    const ctl = new AbortController();
    const key = dashKey;
    const id = searchId;
    fetch('/api/search/dashboard', {
      method: 'POST', headers: JSON_HEADERS, signal: ctl.signal,
      body: JSON.stringify({ searchId: id, relativeThreshold: debouncedThreshold / 100 }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(await failure(r));
        return r.json() as Promise<DashboardData>;
      })
      .then((data) => setDashRes({ key, searchId: id, data, error: null }))
      .catch((e) => {
        if (!isAbort(e)) setDashRes({ key, searchId: id, data: null, error: e instanceof Error ? e.message : 'Dashboard failed' });
      });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchId, debouncedThreshold, dashNonce]);

  // ── summary job: start, poll until finished, cancel when superseded ────────
  const sumKey = `${searchId}|${sumNonce}`;
  useEffect(() => {
    if (!searchId) return;
    const key = sumKey;
    const id = searchId;
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let jobId: string | null = null;
    let running = false;

    const publish = (job: SummaryJob) => {
      running = job.status === 'queued' || job.status === 'running';
      setSumRes({ key, searchId: id, data: job, error: null });
    };
    const fail = (e: unknown) => {
      if (!isAbort(e)) setSumRes({ key, searchId: id, data: null, error: e instanceof Error ? e.message : 'Summary failed' });
    };
    const poll = async (n: number) => {
      try {
        const r = await fetch(`/api/search/summary/${jobId}`, { signal: ctl.signal });
        if (!r.ok) throw new Error(await failure(r));
        const job = (await r.json()) as SummaryJob;
        publish(job);
        if (running) timer = setTimeout(() => poll(n + 1), n < FAST_POLLS ? POLL_FAST_MS : POLL_SLOW_MS);
      } catch (e) {
        fail(e);
      }
    };

    fetch('/api/search/summary', {
      method: 'POST', headers: JSON_HEADERS, signal: ctl.signal,
      body: JSON.stringify({ searchId: id, query, force: sumNonce > 0 }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(await failure(r));
        return r.json() as Promise<SummaryJob>;
      })
      .then((job) => {
        jobId = job.jobId;
        publish(job);
        if (running) timer = setTimeout(() => poll(0), POLL_FAST_MS);
      })
      .catch(fail);

    return () => {
      clearTimeout(timer);
      ctl.abort();
      if (jobId && running) {
        // The user moved on: stop spending tokens on a summary nobody will read
        fetch(`/api/search/summary/${jobId}`, { method: 'DELETE', keepalive: true }).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchId, sumNonce]);

  const dashboard = settle(searchId, dashKey, dashRes);
  const summary = settle(searchId, sumKey, sumRes);

  // Topics: from the index for every card, replaced by the AI's once a file has been summarised
  const topicsBySource = useMemo(() => {
    const map: Record<string, FileTopics> = topicsRes && topicsRes.searchId === searchId ? { ...topicsRes.map } : {};
    for (const d of summary.data?.docs ?? []) {
      if (d.state === 'done' && (d.source === 'llm' || d.source === 'cache') && (d.topics.length || d.events.length)) {
        map[d.sourceId] = { topics: d.topics, events: d.events, origin: 'llm' };
      }
    }
    return map;
  }, [topicsRes, searchId, summary.data]);

  const retryDashboard = useCallback(() => setDashNonce((n) => n + 1), []);
  const retrySummary = useCallback(() => setSumNonce((n) => n + 1), []);

  return { dashboard, summary, topicsBySource, retryDashboard, retrySummary };
}
