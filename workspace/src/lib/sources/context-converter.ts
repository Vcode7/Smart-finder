// src/lib/sources/context-converter.ts
// Converts ContextItem[] (from Smart Find & Chat activeContext) into standard Source[] objects for Groq AI analysis

import type { Source, SourceType, SourceQuality } from '@/types/research';
import type { ContextItem } from '@/store/chat';

export function convertContextItemsToSources(items: ContextItem[]): Source[] {
  if (!items || items.length === 0) return [];

  return items.map((item, index) => {
    let type: SourceType = 'article';
    if (item.type === 'video') type = 'video';
    else if (item.type === 'image') type = 'report';
    else if (item.type === 'web') type = 'web';
    else if (item.type === 'document') type = 'paper';

    const sourceId = (item.metadata?.sourceId as string) || item.id || `ctx-${index + 1}`;
    const url = (item.metadata?.url as string) || (item.type === 'document' ? `/api/knowledge/${sourceId}/file` : '#');
    const provider = (item.metadata?.domain as string) || (item.metadata?.fileType as string)?.toUpperCase() || (item.type === 'document' ? 'Local Knowledge' : 'Live Web');
    const snippet = item.snippet || (item.metadata?.fullContext as string) || item.title;

    const quality: SourceQuality = {
      level: (item.relevanceScore || 0) > 0.8 ? 'high' : (item.relevanceScore || 0) > 0.5 ? 'medium' : 'low',
      reason: 'Retrieved via Smart Finder Dual Retrieval',
    };

    return {
      id: sourceId,
      type,
      title: item.title || `Source #${index + 1}`,
      url,
      provider,
      description: snippet,
      transcript: item.type === 'video' || item.type === 'document' ? snippet : undefined,
      relevanceScore: Math.round((item.relevanceScore || 0.85) * 100),
      quality,
      chatHistory: [],
      isSaved: true,
      isBookmarked: false,
      collectionIds: [],
    };
  });
}
