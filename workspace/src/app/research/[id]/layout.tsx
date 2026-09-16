'use client';

import { useEffect } from 'react';
import { useParams, notFound } from 'next/navigation';
import { useResearchStore } from '@/store/research';
import { useKeyboard } from '@/hooks/useKeyboard';
import { Sidebar } from '@/components/layout/Sidebar';
import { TopBar } from '@/components/layout/TopBar';
import { CommandPalette } from '@/components/layout/CommandPalette';
import { useUIStore } from '@/store/ui';

export default function ResearchLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const sessionId = params?.id as string;
  const { sessions, setActiveSession } = useResearchStore();
  const { sidebarOpen } = useUIStore();

  useKeyboard();

  useEffect(() => {
    if (sessionId) setActiveSession(sessionId);
  }, [sessionId, setActiveSession]);

  const session = sessions.find(s => s.id === sessionId);
  if (!session && sessions.length > 0) notFound();

  return (
    <div className="h-screen w-screen flex overflow-hidden relative" style={{ background: 'var(--bg-base)' }}>
      <Sidebar sessionId={sessionId} />
      <div
        className="flex flex-col flex-1 min-w-0 h-full overflow-hidden transition-all duration-300 relative"
        style={{ marginLeft: sidebarOpen ? 'var(--sidebar-width)' : '0' }}
      >
        <TopBar session={session || null} />
        <main className="flex-1 overflow-hidden relative flex flex-col min-h-0">
          {children}
        </main>
      </div>
    </div>
  );
}
