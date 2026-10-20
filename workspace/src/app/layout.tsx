// src/app/layout.tsx
import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { ThemeProvider } from '@/components/providers/ThemeProvider';
import { AuthProvider } from '@/components/providers/AuthProvider';
import { CommandPalette } from '@/components/layout/CommandPalette';
import { Toaster } from 'sonner';

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
});

export const metadata: Metadata = {
  title: 'Smart Finder — AI Knowledge Platform',
  description:
    'Smart Finder: AI-powered knowledge retrieval and chat platform. Search local documents, videos, and the internet with advanced AI synthesis.',
  keywords: ['Smart Finder', 'AI research', 'knowledge base', 'Groq AI', 'RAG', 'document search', 'face recognition'],
  openGraph: {
    title: 'Smart Finder AI',
    description: 'Smart Finder: Premium AI-powered knowledge retrieval and chat platform',
    type: 'website',
  },
};

// Applies the saved theme before first paint (ThemeProvider takes over after hydration),
// so light-mode users don't see a dark flash. Reads the persisted UI store (store/ui.ts).
const themeScript = `try{var s=JSON.parse(localStorage.getItem('ai-research-ui')||'{}').state||{};var t=s.theme||'dark';var d=t==='system'?matchMedia('(prefers-color-scheme: dark)').matches:t!=='light';var e=document.documentElement;e.classList.toggle('dark',d);e.classList.toggle('light',!d);e.style.colorScheme=d?'dark':'light'}catch(_){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <ThemeProvider>
          <AuthProvider>
            {children}
          </AuthProvider>
          <CommandPalette />
          <Toaster
            position="bottom-right"
            toastOptions={{
              style: {
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border)',
                color: 'var(--text-primary)',
              },
            }}
          />
        </ThemeProvider>
      </body>
    </html>
  );
}
