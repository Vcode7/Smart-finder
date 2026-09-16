// src/hooks/useChat.ts
'use client';

import { useState, useCallback, useRef } from 'react';
import { useResearchStore } from '@/store/research';
import { generateId } from '@/lib/utils/scoring';
import { isoNow } from '@/lib/utils/date';
import type { Source, ChatMessage } from '@/types/research';

export function useChat(sessionId: string, source: Source) {
  const { addChatMessage } = useResearchStore();
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(async (message: string) => {
    if (!message.trim() || isStreaming) return;

    // Add user message
    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: message,
      timestamp: isoNow(),
    };
    addChatMessage(sessionId, source.id, userMsg);

    setIsStreaming(true);
    setStreamingText('');
    abortRef.current = new AbortController();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source,
          message,
          history: source.chatHistory.slice(-10),
        }),
        signal: abortRef.current.signal,
      });

      if (!res.ok) throw new Error('Chat request failed');

      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let full = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        full += chunk;
        setStreamingText(full);
      }

      // Save complete AI response
      const aiMsg: ChatMessage = {
        id: generateId(),
        role: 'assistant',
        content: full,
        timestamp: isoNow(),
      };
      addChatMessage(sessionId, source.id, aiMsg);
      setStreamingText('');
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') {
        const errorMsg: ChatMessage = {
          id: generateId(),
          role: 'assistant',
          content: 'I encountered an error. Please try again.',
          timestamp: isoNow(),
        };
        addChatMessage(sessionId, source.id, errorMsg);
      }
    } finally {
      setIsStreaming(false);
      setStreamingText('');
    }
  }, [sessionId, source, isStreaming, addChatMessage]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { sendMessage, isStreaming, streamingText, stopStreaming };
}
