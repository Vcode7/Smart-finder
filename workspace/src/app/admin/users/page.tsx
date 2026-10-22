'use client';
// src/app/admin/users/page.tsx — admins create user/admin accounts and choose which libraries each user can search

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check, KeyRound, Loader2, Shield, Trash2, User as UserIcon, UserPlus, Users as UsersIcon } from 'lucide-react';
import { toast } from 'sonner';
import Sidebar from '@/components/layout/Sidebar';
import { useAuthStore } from '@/store/auth';
import { apiErrorMessage, readJson } from '@/lib/utils/api';

interface ManagedUser {
  id: string;
  email: string;
  username: string;
  role: 'user' | 'admin';
  createdAt?: string | null;
  libraryIds: string[];
}

interface LibraryOption {
  id: string;
  name: string;
  kind: 'folder' | 'uploads' | 'linked';
}

async function api<T = Record<string, unknown>>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const data = await readJson<T>(res);
  if (!res.ok) throw new Error(apiErrorMessage(data, `Request failed (${res.status})`));
  return (data || {}) as T;
}

const jsonInit = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
});

const inputClass = 'px-3.5 py-2.5 rounded-xl text-sm outline-none';
const inputStyle = { background: 'var(--bg-base)', border: '1px solid var(--border)', color: 'var(--text-primary)' };

export default function UsersPage() {
  const { user: me } = useAuthStore();
  const router = useRouter();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [libraries, setLibraries] = useState<LibraryOption[]>([]);
  const [loading, setLoading] = useState(true);

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'user' | 'admin'>('user');
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const [u, l] = await Promise.all([
        api<{ users: ManagedUser[] }>('/api/users'),
        api<{ libraries: LibraryOption[] }>('/api/libraries'),
      ]);
      setUsers(u.users || []);
      setLibraries(l.libraries || []);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not load users');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (me && me.role !== 'admin') { router.push('/'); return; }
    load();
  }, [me, router, load]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (creating) return;
    setCreating(true);
    try {
      await api('/api/users', jsonInit('POST', { username, email, password, role }));
      toast.success(`${role === 'admin' ? 'Admin' : 'User'} account created for ${email}`);
      setUsername(''); setEmail(''); setPassword(''); setRole('user');
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not create the account');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex flex-col md:flex-row h-dvh overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 space-y-6">
          <header className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl flex items-center justify-center"
              style={{ background: 'linear-gradient(135deg, #6366f1 0%, #06b6d4 100%)' }}>
              <UsersIcon className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>Users</h1>
              <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                Create accounts and choose which libraries each user can search. Users can only query what you share; only admins upload.
              </p>
            </div>
          </header>

          <form onSubmit={create} className="rounded-2xl p-4 space-y-3"
            style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
            <p className="text-sm font-semibold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
              <UserPlus className="w-4 h-4" /> Add an account
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Name" required
                aria-label="Name" className={inputClass} style={inputStyle} />
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" required
                aria-label="Email" className={inputClass} style={inputStyle} />
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8}
                placeholder="Temporary password (min 8 characters)" aria-label="Password" autoComplete="new-password"
                className={inputClass} style={inputStyle} />
              <select value={role} onChange={(e) => setRole(e.target.value as 'user' | 'admin')} aria-label="Role"
                className={inputClass} style={inputStyle}>
                <option value="user">User — can search shared libraries</option>
                <option value="admin">Admin — full access, can upload and manage users</option>
              </select>
            </div>
            <button type="submit" disabled={creating || !username.trim() || !email.trim() || password.length < 8}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-white disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
              {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
              Create {role === 'admin' ? 'admin' : 'user'}
            </button>
          </form>

          <section className="space-y-3" aria-label="Accounts">
            {loading ? (
              <div className="flex justify-center py-16">
                <Loader2 className="w-7 h-7 animate-spin" style={{ color: 'var(--accent)' }} />
              </div>
            ) : (
              users.map((u) => (
                <UserCard key={u.id} u={u} isSelf={u.id === me?.id} libraries={libraries} onChanged={load} />
              ))
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

function UserCard({ u, isSelf, libraries, onChanged }: {
  u: ManagedUser; isSelf: boolean; libraries: LibraryOption[]; onChanged: () => Promise<void>;
}) {
  const [shared, setShared] = useState<string[]>(u.libraryIds);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [newPassword, setNewPassword] = useState('');

  useEffect(() => setShared(u.libraryIds), [u.libraryIds]);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
      await onChanged();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Request failed');
    }
  };

  const toggleLibrary = async (libraryId: string) => {
    const next = shared.includes(libraryId) ? shared.filter((id) => id !== libraryId) : [...shared, libraryId];
    const previous = shared;
    setShared(next);
    setSaving(true);
    try {
      const res = await api<{ libraryIds: string[] }>(`/api/users/${u.id}/libraries`, jsonInit('PUT', { libraryIds: next }));
      setShared(res.libraryIds);
    } catch (e) {
      setShared(previous);
      toast.error(e instanceof Error ? e.message : 'Could not update sharing');
    } finally {
      setSaving(false);
    }
  };

  const remove = () => {
    if (!window.confirm(`Delete ${u.username} (${u.email})? Their chats are removed too.`)) return;
    run(() => api(`/api/users/${u.id}`, { method: 'DELETE' }), 'Account deleted');
  };

  const changeRole = () => {
    const next = u.role === 'admin' ? 'user' : 'admin';
    if (!window.confirm(`Make ${u.username} ${next === 'admin' ? 'an admin' : 'a regular user'}?`)) return;
    run(() => api(`/api/users/${u.id}`, jsonInit('PATCH', { role: next })), 'Role updated');
  };

  const resetPassword = async (e: FormEvent) => {
    e.preventDefault();
    await run(() => api(`/api/users/${u.id}`, jsonInit('PATCH', { password: newPassword })), 'Password updated');
    setResetting(false);
    setNewPassword('');
  };

  const isAdmin = u.role === 'admin';
  const actionClass = 'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[var(--bg-hover)]';
  const actionStyle = { border: '1px solid var(--border)', color: 'var(--text-secondary)' };

  return (
    <div className="rounded-2xl p-4 space-y-3" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          {isAdmin
            ? <Shield className="w-5 h-5 flex-shrink-0" style={{ color: 'var(--accent)' }} />
            : <UserIcon className="w-5 h-5 flex-shrink-0" style={{ color: 'var(--text-muted)' }} />}
          <div className="min-w-0">
            <p className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
              {u.username}{isSelf && <span style={{ color: 'var(--text-muted)' }}> (you)</span>}
              <span className="ml-2 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded"
                style={{ background: 'var(--bg-active)', color: isAdmin ? 'var(--accent)' : 'var(--text-secondary)' }}>
                {isAdmin ? 'Admin' : 'User'}
              </span>
            </p>
            <p className="text-xs truncate" style={{ color: 'var(--text-secondary)' }}>{u.email}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setResetting((v) => !v)} className={actionClass} style={actionStyle}>
            <KeyRound className="w-3.5 h-3.5" /> Reset password
          </button>
          {!isSelf && (
            <>
              <button onClick={changeRole} className={actionClass} style={actionStyle}>
                {isAdmin ? 'Make user' : 'Make admin'}
              </button>
              <button onClick={remove} className={actionClass} style={{ ...actionStyle, color: 'var(--error)' }}>
                <Trash2 className="w-3.5 h-3.5" /> Delete
              </button>
            </>
          )}
        </div>
      </div>

      {resetting && (
        <form onSubmit={resetPassword} className="flex gap-2">
          <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} minLength={8} required
            autoComplete="new-password" placeholder="New password (min 8 characters)" aria-label="New password"
            className={`${inputClass} flex-1`} style={inputStyle} />
          <button type="submit" disabled={newPassword.length < 8}
            className="px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-40 hover:bg-[var(--bg-hover)]"
            style={{ border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
            Save
          </button>
        </form>
      )}

      {isAdmin ? (
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Admins can search and manage every library.</p>
      ) : (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider mb-2 flex items-center gap-2" style={{ color: 'var(--text-secondary)' }}>
            Can search {saving && <Loader2 className="w-3 h-3 animate-spin" />}
          </p>
          {libraries.length === 0 ? (
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>No libraries yet. Add or upload data first, then share it here.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {libraries.map((lib) => {
                const on = shared.includes(lib.id);
                return (
                  <button key={lib.id} type="button" onClick={() => toggleLibrary(lib.id)} aria-pressed={on}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors"
                    style={{
                      border: `1px solid ${on ? 'var(--accent)' : 'var(--border)'}`,
                      background: on ? 'var(--accent-muted)' : 'transparent',
                      color: on ? 'var(--accent)' : 'var(--text-secondary)',
                    }}>
                    {on && <Check className="w-3 h-3" />}
                    {lib.name}
                  </button>
                );
              })}
            </div>
          )}
          {shared.length === 0 && libraries.length > 0 && (
            <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>Nothing shared yet: this user sees no data.</p>
          )}
        </div>
      )}
    </div>
  );
}
