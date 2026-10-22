'use client';
// src/app/auth/admin-signup/page.tsx — create an administrator account with the server's setup code

import { useState, useEffect, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { ShieldCheck, Mail, Lock, User, KeyRound, ArrowRight, Eye, EyeOff, Sun, Moon } from 'lucide-react';
import { useAuthStore, type AuthUser } from '@/store/auth';
import { useUIStore } from '@/store/ui';
import { toast } from 'sonner';
import { apiErrorMessage, readJson } from '@/lib/utils/api';

const inputStyle = { background: 'var(--bg-surface, var(--bg-base))', border: '1px solid var(--border)', color: 'var(--text-primary)' };
const focusRing = {
  onFocus: (e: React.FocusEvent<HTMLInputElement>) => { e.target.style.borderColor = 'var(--accent)'; e.target.style.boxShadow = '0 0 0 3px var(--accent-muted)'; },
  onBlur: (e: React.FocusEvent<HTMLInputElement>) => { e.target.style.borderColor = 'var(--border)'; e.target.style.boxShadow = 'none'; },
};

export default function AdminSignupPage() {
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [setupCode, setSetupCode] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const { setUser } = useAuthStore();
  const { theme, setTheme } = useUIStore();
  const router = useRouter();

  useEffect(() => {
    fetch('/api/auth/config')
      .then((res) => (res.ok ? res.json() : null))
      .then((cfg) => setEnabled(Boolean(cfg?.allowAdminSignup)))
      .catch(() => setEnabled(false));
  }, []);

  const canSubmit = !isLoading && email.trim() && username.trim() && password.length >= 8 && setupCode.trim();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;

    setIsLoading(true);
    try {
      const res = await fetch('/api/auth/signup-admin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, username, password, setupCode }),
      });
      const data = await readJson<{ user: AuthUser }>(res);

      if (!res.ok || !data) {
        toast.error(apiErrorMessage(data, 'Could not create the admin account'));
        return;
      }

      setUser(data.user);
      toast.success('Admin account created');
      router.push('/');
    } catch {
      toast.error('Network error. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden py-8"
      style={{ background: 'var(--bg-base)' }}>
      <div className="absolute top-5 right-5 z-20">
        <button
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium transition-all hover:bg-[var(--bg-hover)] cursor-pointer"
          style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'var(--bg-elevated)', boxShadow: 'var(--shadow-sm)' }}
          aria-label="Toggle Theme"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-indigo-500" />}
          <span className="font-medium text-[11px]">{theme === 'dark' ? 'Light' : 'Dark'}</span>
        </button>
      </div>

      <div className="absolute inset-0 mesh-grid opacity-40 pointer-events-none" />

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', bounce: 0.15, duration: 0.7 }}
        className="relative z-10 w-full max-w-md mx-4"
      >
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl mb-4 shadow-xl"
            style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)', boxShadow: '0 0 40px rgba(99,102,241,0.4)' }}>
            <ShieldCheck className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
            Create an admin account
          </h1>
          <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
            Admins upload data, create user accounts and choose what each user can search.
          </p>
        </div>

        <div className="p-8 rounded-3xl shadow-2xl"
          style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', boxShadow: '0 25px 60px rgba(0,0,0,0.5), 0 0 0 1px rgba(99,102,241,0.1)' }}>
          {enabled === false ? (
            <p className="text-sm text-center" style={{ color: 'var(--text-secondary)' }}>
              Admin sign-up is turned off on this server. Set <code>ADMIN_SETUP_CODE</code> in <code>backend/.env</code> to
              enable it, or ask an existing administrator to create an account for you.
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <Field label="Username" icon={User}>
                <input id="admin-signup-username" type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                  placeholder="Your name" required disabled={isLoading}
                  className="w-full pl-10 pr-4 py-3 rounded-xl text-sm outline-none transition-all" style={inputStyle} {...focusRing} />
              </Field>
              <Field label="Email Address" icon={Mail}>
                <input id="admin-signup-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com" required disabled={isLoading}
                  className="w-full pl-10 pr-4 py-3 rounded-xl text-sm outline-none transition-all" style={inputStyle} {...focusRing} />
              </Field>
              <Field label="Password" icon={Lock}>
                <input id="admin-signup-password" type={showPassword ? 'text' : 'password'} value={password}
                  onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters" required disabled={isLoading}
                  className="w-full pl-10 pr-12 py-3 rounded-xl text-sm outline-none transition-all" style={inputStyle} {...focusRing} />
                <button type="button" onClick={() => setShowPassword((v) => !v)} aria-label={showPassword ? 'Hide password' : 'Show password'}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 p-1 rounded-lg transition-colors hover:bg-[var(--bg-hover)]"
                  style={{ color: 'var(--text-muted)' }}>
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </Field>
              <Field label="Admin setup code" icon={KeyRound}>
                <input id="admin-signup-code" type="password" value={setupCode} onChange={(e) => setSetupCode(e.target.value)}
                  placeholder="ADMIN_SETUP_CODE from backend/.env" required disabled={isLoading} autoComplete="off"
                  className="w-full pl-10 pr-4 py-3 rounded-xl text-sm outline-none transition-all" style={inputStyle} {...focusRing} />
              </Field>

              <motion.button
                type="submit"
                disabled={!canSubmit}
                whileHover={{ scale: 1.01 }}
                whileTap={{ scale: 0.99 }}
                className="w-full flex items-center justify-center gap-2.5 py-3.5 rounded-xl font-semibold text-sm text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg mt-2"
                style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)', boxShadow: '0 8px 24px rgba(99,102,241,0.35)' }}
              >
                {isLoading ? (
                  <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /><span>Creating account...</span></>
                ) : (
                  <><ShieldCheck className="w-4 h-4" /><span>Create Admin Account</span><ArrowRight className="w-4 h-4" /></>
                )}
              </motion.button>
            </form>
          )}

          <p className="text-center text-sm mt-6" style={{ color: 'var(--text-secondary)' }}>
            Already have an account?{' '}
            <Link href="/auth/login" className="font-semibold transition-colors hover:underline" style={{ color: 'var(--accent)' }}>
              Sign in
            </Link>
          </p>
        </div>
      </motion.div>
    </div>
  );
}

function Field({ label, icon: Icon, children }: {
  label: string; icon: typeof Mail; children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <label className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </label>
      <div className="relative">
        <div className="absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none">
          <Icon className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />
        </div>
        {children}
      </div>
    </div>
  );
}
