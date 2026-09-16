'use client';
// src/app/auth/login/page.tsx — Premium animated login page

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { Sparkles, Mail, Lock, ArrowRight, Eye, EyeOff, Zap, Shield, Sun, Moon } from 'lucide-react';
import { useAuthStore } from '@/store/auth';
import { useUIStore } from '@/store/ui';
import { toast } from 'sonner';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const { setUser } = useAuthStore();
  const { theme, setTheme } = useUIStore();
  const router = useRouter();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password.trim()) return;

    setIsLoading(true);
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();

      if (!res.ok) {
        toast.error(data.error || 'Login failed');
        return;
      }

      setUser(data.user);
      toast.success(`Welcome back, ${data.user.username}!`);
      router.push('/');
    } catch {
      toast.error('Network error. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden"
      style={{ background: 'var(--bg-base)' }}>

      {/* Top right theme toggle */}
      <div className="absolute top-5 right-5 z-20">
        <button
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium transition-all hover:bg-[var(--bg-hover)] cursor-pointer"
          style={{
            border: '1px solid var(--border)',
            color: 'var(--text-secondary)',
            background: 'var(--bg-elevated)',
            boxShadow: 'var(--shadow-sm)',
          }}
          title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
          aria-label="Toggle Theme"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-indigo-500" />}
          <span className="font-medium text-[11px]">{theme === 'dark' ? 'Light' : 'Dark'}</span>
        </button>
      </div>

      {/* Animated background orbs */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full opacity-20 blur-3xl animate-pulse"
          style={{ background: 'radial-gradient(circle, #6366f1 0%, transparent 70%)' }} />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 rounded-full opacity-15 blur-3xl animate-pulse"
          style={{ background: 'radial-gradient(circle, #a855f7 0%, transparent 70%)', animationDelay: '1s' }} />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full opacity-5 blur-3xl"
          style={{ background: 'radial-gradient(circle, #06b6d4 0%, transparent 70%)' }} />
      </div>

      {/* Mesh grid overlay */}
      <div className="absolute inset-0 mesh-grid opacity-40 pointer-events-none" />

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', bounce: 0.15, duration: 0.7 }}
        className="relative z-10 w-full max-w-md mx-4"
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.1 }}
            className="inline-flex items-center justify-center w-14 h-14 rounded-2xl mb-4 shadow-xl"
            style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)', boxShadow: '0 0 40px rgba(99,102,241,0.4)' }}
          >
            <Sparkles className="w-7 h-7 text-white" />
          </motion.div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
            Welcome to Smart Finder
          </h1>
          <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
            Sign in to your AI research platform
          </p>
        </div>

        {/* Card */}
        <div className="p-8 rounded-3xl shadow-2xl"
          style={{
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            boxShadow: '0 25px 60px rgba(0,0,0,0.5), 0 0 0 1px rgba(99,102,241,0.1)',
          }}
        >
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email field */}
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-secondary)' }}>
                Email Address
              </label>
              <div className="relative">
                <div className="absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none">
                  <Mail className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />
                </div>
                <input
                  id="login-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  disabled={isLoading}
                  className="w-full pl-10 pr-4 py-3 rounded-xl text-sm outline-none transition-all"
                  style={{
                    background: 'var(--bg-surface, var(--bg-base))',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                  }}
                  onFocus={(e) => { e.target.style.borderColor = 'var(--accent)'; e.target.style.boxShadow = '0 0 0 3px var(--accent-muted)'; }}
                  onBlur={(e) => { e.target.style.borderColor = 'var(--border)'; e.target.style.boxShadow = 'none'; }}
                />
              </div>
            </div>

            {/* Password field */}
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-secondary)' }}>
                Password
              </label>
              <div className="relative">
                <div className="absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none">
                  <Lock className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />
                </div>
                <input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  disabled={isLoading}
                  className="w-full pl-10 pr-12 py-3 rounded-xl text-sm outline-none transition-all"
                  style={{
                    background: 'var(--bg-surface, var(--bg-base))',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                  }}
                  onFocus={(e) => { e.target.style.borderColor = 'var(--accent)'; e.target.style.boxShadow = '0 0 0 3px var(--accent-muted)'; }}
                  onBlur={(e) => { e.target.style.borderColor = 'var(--border)'; e.target.style.boxShadow = 'none'; }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 p-1 rounded-lg transition-colors hover:bg-[var(--bg-hover)]"
                  style={{ color: 'var(--text-muted)' }}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Submit */}
            <motion.button
              type="submit"
              disabled={isLoading || !email.trim() || !password.trim()}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              className="w-full flex items-center justify-center gap-2.5 py-3.5 rounded-xl font-semibold text-sm text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg"
              style={{
                background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
                boxShadow: '0 8px 24px rgba(99,102,241,0.35)',
              }}
            >
              {isLoading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Signing in...</span>
                </>
              ) : (
                <>
                  <Zap className="w-4 h-4" />
                  <span>Sign In</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </motion.button>
          </form>

          {/* Quick Admin fill */}
          {/* <div className="mt-4 p-3 rounded-2xl flex items-center justify-between gap-2 text-xs"
            style={{ background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.15)' }}>
            <div>
              <p className="font-semibold" style={{ color: 'var(--text-primary)' }}>Admin Demo Account</p>
              <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>admin@smartfind.ai</p>
            </div>
            <button
              type="button"
              onClick={() => {
                setEmail('admin@smartfind.ai');
                setPassword('Admin@123456');
              }}
              className="px-2.5 py-1.5 rounded-xl text-xs font-semibold transition-all hover:scale-105"
              style={{ background: 'var(--accent)', color: '#fff' }}
            >
              Fill Credentials
            </button>
          </div> */}

          {/* Sign up link */}
          <p className="text-center text-sm mt-4" style={{ color: 'var(--text-secondary)' }}>
            Don&apos;t have an account?{' '}
            <Link href="/auth/signup"
              className="font-semibold transition-colors hover:underline"
              style={{ color: 'var(--accent)' }}>
              Create one free
            </Link>
          </p>
        </div>

        {/* Security note */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4 }}
          className="mt-4 flex items-center justify-center gap-2 text-xs"
          style={{ color: 'var(--text-muted)' }}
        >
          <Shield className="w-3.5 h-3.5" />
          <span>Secured with JWT + bcrypt encryption</span>
        </motion.div>
      </motion.div>
    </div>
  );
}
