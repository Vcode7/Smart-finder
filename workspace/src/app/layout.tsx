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

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body className={inter.variable}>
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
