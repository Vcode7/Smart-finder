'use client';
// src/app/people/page.tsx — people found in photos and videos (faces grouped across every library)

import { useCallback, useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowLeft, Check, Eye, EyeOff, GitMerge, Loader2, Pencil, RefreshCw, UserRound, Users, X,
} from 'lucide-react';
import { toast } from 'sonner';
import Sidebar from '@/components/layout/Sidebar';
import { DocumentMetadataModal } from '@/components/modals/DocumentMetadataModal';
import { useAuthStore } from '@/store/auth';
import { apiErrorMessage, readJson } from '@/lib/utils/api';

interface Person {
  id: string;
  name: string | null;
  faceCount: number;
  hidden: boolean;
  coverUrl: string | null;
}

interface PersonMedia {
  sourceId: string;
  libraryName: string;
  title: string;
  kind: string;
  relPath: string;
  faces: number;
  timestamps: number[];
  page: number | null;
  thumbnail: string;
  faceCrop: string | null;
}

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const data = await readJson<T>(res);
  if (!res.ok) throw new Error(apiErrorMessage(data, `Request failed (${res.status})`));
  return data as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const label = (p: Person) => p.name || 'Unnamed person';

export default function PeoplePage() {
  const { user } = useAuthStore();
  const isAdmin = user?.role === 'admin';
  const [people, setPeople] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);
  const [showHidden, setShowHidden] = useState(false);
  const [selected, setSelected] = useState<Person | null>(null);
  const [regrouping, setRegrouping] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    api<{ people: Person[] }>(`/api/people${showHidden ? '?includeHidden=true' : ''}`)
      .then((d) => { if (active) setPeople(d.people || []); })
      .catch(() => { if (active) setPeople([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [showHidden, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  const regroup = async () => {
    setRegrouping(true);
    try {
      const r = await api<{ people: number; faces: number }>('/api/people/recluster', { method: 'POST' });
      toast.success(`${r.people} people from ${r.faces} faces`);
      reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Regrouping failed');
    } finally {
      setRegrouping(false);
    }
  };

  return (
    <div className="flex flex-col md:flex-row h-dvh overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-6">
          <AnimatePresence mode="wait">
            {selected ? (
              <PersonDetail key={selected.id} person={selected} people={people} isAdmin={isAdmin}
                onBack={() => { setSelected(null); reload(); }}
                onChanged={(p) => { setSelected(p); reload(); }} />
            ) : (
              <motion.div key="grid" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-6">
                <header className="flex flex-wrap items-start justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-2xl flex items-center justify-center"
                      style={{ background: 'linear-gradient(135deg, #f43f5e 0%, #a855f7 100%)' }}>
                      <Users className="w-5 h-5 text-white" />
                    </div>
                    <div>
                      <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>People</h1>
                      <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                        Faces found in your photos, videos and documents, grouped by person. Name someone once and
                        search for them by name everywhere.
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => { setLoading(true); setShowHidden(!showHidden); }}
                      className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs hover:bg-[var(--bg-hover)]"
                      style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                      {showHidden ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                      {showHidden ? 'Hide hidden' : 'Show hidden'}
                    </button>
                    {isAdmin && (
                      <button onClick={regroup} disabled={regrouping}
                        className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs hover:bg-[var(--bg-hover)] disabled:opacity-50"
                        style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                        title="Regroup all faces now (also happens automatically after indexing)">
                        <RefreshCw className={`w-3.5 h-3.5 ${regrouping ? 'animate-spin' : ''}`} /> Regroup
                      </button>
                    )}
                  </div>
                </header>

                {loading ? (
                  <div className="flex justify-center py-20">
                    <Loader2 className="w-7 h-7 animate-spin" style={{ color: 'var(--accent)' }} />
                  </div>
                ) : people.length === 0 ? (
                  <div className="text-center py-20 rounded-2xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                    <UserRound className="w-10 h-10 mx-auto mb-3 opacity-40" style={{ color: 'var(--text-muted)' }} />
                    <p className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>No people yet</p>
                    <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                      People appear here once photos or videos with faces have been indexed.
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
                    {people.map((p) => (
                      <button key={p.id} onClick={() => setSelected(p)}
                        className="group text-left rounded-2xl p-3 transition-colors hover:bg-[var(--bg-hover)]"
                        style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', opacity: p.hidden ? 0.5 : 1 }}>
                        <div className="aspect-square rounded-xl overflow-hidden mb-2 flex items-center justify-center"
                          style={{ background: 'var(--bg-active)' }}>
                          {p.coverUrl ? (
                            /* eslint-disable-next-line @next/next/no-img-element */
                            <img src={p.coverUrl} alt={label(p)} loading="lazy" className="w-full h-full object-cover" />
                          ) : (
                            <UserRound className="w-10 h-10 opacity-40" style={{ color: 'var(--text-muted)' }} />
                          )}
                        </div>
                        <p className="text-sm font-semibold truncate" style={{ color: p.name ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                          {label(p)}
                        </p>
                        <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                          {p.faceCount} appearance{p.faceCount === 1 ? '' : 's'}
                        </p>
                      </button>
                    ))}
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}

function PersonDetail({ person, people, isAdmin, onBack, onChanged }: {
  person: Person; people: Person[]; isAdmin: boolean; onBack: () => void; onChanged: (p: Person) => void;
}) {
  const [media, setMedia] = useState<PersonMedia[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(person.name || '');
  const [merging, setMerging] = useState(false);
  const [inspect, setInspect] = useState<{ id: string; t?: number } | null>(null);

  useEffect(() => {
    let active = true;
    api<{ media: { total: number; items: PersonMedia[] } }>(`/api/people/${person.id}?limit=200`)
      .then((d) => { if (active) { setMedia(d.media.items); setTotal(d.media.total); } })
      .catch(() => { if (active) setMedia([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [person.id]);

  const save = async (patch: Partial<Pick<Person, 'name' | 'hidden'>>) => {
    try {
      const p = await api<Person>(`/api/people/${person.id}`, json('PATCH', patch));
      setEditing(false);
      onChanged(p);
      toast.success('Saved');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save');
    }
  };

  const mergeInto = async (target: Person) => {
    const n = person.faceCount;
    if (!window.confirm(`Move ${n} appearance${n === 1 ? '' : 's'} of “${label(person)}” to “${label(target)}”?`)) return;
    try {
      await api(`/api/people/${person.id}/merge`, json('POST', { targetId: target.id }));
      toast.success(`Merged into ${label(target)}`);
      onBack();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Merge failed');
    }
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-6">
      <div className="flex flex-wrap items-center gap-4">
        <button onClick={onBack} className="p-2 rounded-xl hover:bg-[var(--bg-hover)]" aria-label="Back to people">
          <ArrowLeft className="w-5 h-5" style={{ color: 'var(--text-secondary)' }} />
        </button>
        <div className="w-16 h-16 rounded-2xl overflow-hidden flex items-center justify-center" style={{ background: 'var(--bg-active)' }}>
          {person.coverUrl
            /* eslint-disable-next-line @next/next/no-img-element */
            ? <img src={person.coverUrl} alt={label(person)} className="w-full h-full object-cover" />
            : <UserRound className="w-8 h-8 opacity-40" />}
        </div>
        <div className="flex-1 min-w-0">
          {editing ? (
            <form onSubmit={(e) => { e.preventDefault(); save({ name }); }} className="flex items-center gap-2">
              <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Name this person"
                className="px-3 py-1.5 rounded-lg text-lg font-semibold outline-none"
                style={{ background: 'var(--bg-elevated)', border: '1px solid var(--accent)', color: 'var(--text-primary)' }} />
              <button type="submit" className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)]" aria-label="Save name">
                <Check className="w-4 h-4" style={{ color: 'var(--success)' }} />
              </button>
              <button type="button" onClick={() => setEditing(false)} className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)]" aria-label="Cancel">
                <X className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />
              </button>
            </form>
          ) : (
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold truncate" style={{ color: person.name ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                {label(person)}
              </h1>
              {isAdmin && (
                <button onClick={() => setEditing(true)} className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)]" aria-label="Rename">
                  <Pencil className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />
                </button>
              )}
            </div>
          )}
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            {person.faceCount} appearance{person.faceCount === 1 ? '' : 's'} in {total} file{total === 1 ? '' : 's'}
            {person.name && <> · search for <code className="px-1 rounded" style={{ background: 'var(--bg-active)' }}>{person.name}</code> anywhere</>}
          </p>
        </div>
        {isAdmin && (
          <div className="flex gap-2">
            <button onClick={() => save({ hidden: !person.hidden })}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs hover:bg-[var(--bg-hover)]"
              style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
              {person.hidden ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
              {person.hidden ? 'Unhide' : 'Hide'}
            </button>
            <button onClick={() => setMerging(!merging)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs hover:bg-[var(--bg-hover)]"
              style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
              <GitMerge className="w-3.5 h-3.5" /> Same person as…
            </button>
          </div>
        )}
      </div>

      {merging && (
        <div className="p-3 rounded-2xl" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
          <p className="text-xs mb-2" style={{ color: 'var(--text-secondary)' }}>
            Choose who this is — all of these appearances move to that person:
          </p>
          <div className="flex flex-wrap gap-2">
            {people.filter((p) => p.id !== person.id).map((p) => (
              <button key={p.id} onClick={() => mergeInto(p)}
                className="flex items-center gap-2 px-2 py-1 rounded-xl text-xs hover:bg-[var(--bg-hover)]"
                style={{ border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
                {p.coverUrl
                  /* eslint-disable-next-line @next/next/no-img-element */
                  ? <img src={p.coverUrl} alt="" className="w-6 h-6 rounded-full object-cover" />
                  : <UserRound className="w-4 h-4" />}
                {label(p)}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-20"><Loader2 className="w-7 h-7 animate-spin" style={{ color: 'var(--accent)' }} /></div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
          {media.map((m) => (
            <div key={m.sourceId} className="rounded-2xl overflow-hidden" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
              <button onClick={() => setInspect({ id: m.sourceId, t: m.timestamps[0] })} className="block w-full aspect-video relative"
                style={{ background: 'var(--bg-active)' }} aria-label={`Open ${m.title}`}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={m.thumbnail} alt="" loading="lazy" className="w-full h-full object-cover"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden'; }} />
                {m.faceCrop && (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img src={m.faceCrop} alt="" className="absolute bottom-2 right-2 w-10 h-10 rounded-full object-cover"
                    style={{ border: '2px solid var(--bg-elevated)' }} />
                )}
              </button>
              <div className="p-2.5">
                <p className="text-xs font-semibold truncate" style={{ color: 'var(--text-primary)' }} title={m.relPath}>{m.title}</p>
                <p className="text-[10px] truncate" style={{ color: 'var(--text-muted)' }}>{m.libraryName} · {m.relPath}</p>
                {m.timestamps.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {m.timestamps.slice(0, 6).map((t) => (
                      <button key={t} onClick={() => setInspect({ id: m.sourceId, t })}
                        className="px-1.5 py-0.5 rounded text-[10px] font-mono hover:bg-[var(--accent-muted)]"
                        style={{ background: 'var(--bg-active)', color: 'var(--accent)' }}>
                        {clock(t)}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <DocumentMetadataModal sourceId={inspect?.id ?? null} initialTimestamp={inspect?.t}
        isOpen={Boolean(inspect)} onClose={() => setInspect(null)} />
    </motion.div>
  );
}
