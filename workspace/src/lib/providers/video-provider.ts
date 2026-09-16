// src/lib/providers/video-provider.ts
// YouTube Data API v3 (Real API client — Never fabricates mock data)

import type { Source, ProviderResult } from '@/types/research';
import { assessSourceQuality, generateId } from '@/lib/utils/scoring';

export interface VideoSearchOptions {
  pageToken?: string;
  maxResults?: number;
  offset?: number;
}

export async function searchVideos(
  query: string,
  options: VideoSearchOptions = {}
): Promise<ProviderResult & { sources: Source[]; nextPageToken?: string }> {
  const apiKey = process.env.YOUTUBE_API_KEY;

  if (!apiKey) {
    console.warn('[VideoProvider] YOUTUBE_API_KEY is not configured in environment.');
    return {
      provider: 'YouTube Data API v3',
      category: 'video',
      status: 'not_configured',
      error: 'YouTube API key (YOUTUBE_API_KEY) is not configured in .env.local.',
      count: 0,
      sources: [],
    };
  }

  try {
    const url = new URL('https://www.googleapis.com/youtube/v3/search');
    url.searchParams.set('part', 'snippet');
    url.searchParams.set('q', query);
    url.searchParams.set('type', 'video');
    url.searchParams.set('maxResults', String(options.maxResults || 8));
    url.searchParams.set('relevanceLanguage', 'en');
    url.searchParams.set('key', apiKey);
    if (options.pageToken) {
      url.searchParams.set('pageToken', options.pageToken);
    }

    const res = await fetch(url.toString(), { next: { revalidate: 3600 } });
    if (!res.ok) {
      const errorText = await res.text().catch(() => '');
      throw new Error(`YouTube API returned status ${res.status}: ${errorText || res.statusText}`);
    }
    const data = await res.json();
    const nextPageToken = data.nextPageToken;

    const items = data.items || [];
    if (items.length === 0) {
      return {
        provider: 'YouTube Data API v3',
        category: 'video',
        status: 'empty',
        error: `No YouTube videos found matching "${query}".`,
        count: 0,
        sources: [],
        nextPageToken: undefined,
      };
    }

    // Fetch video details for duration/view count
    const ids = items.map((item: { id: { videoId: string } }) => item.id.videoId).join(',');
    const detailUrl = new URL('https://www.googleapis.com/youtube/v3/videos');
    detailUrl.searchParams.set('part', 'contentDetails,statistics');
    detailUrl.searchParams.set('id', ids);
    detailUrl.searchParams.set('key', apiKey);

    const detailRes = await fetch(detailUrl.toString(), { next: { revalidate: 3600 } });
    const detailData = detailRes.ok ? await detailRes.json() : { items: [] };
    const detailMap: Record<string, { duration: string; viewCount: string }> = {};

    for (const item of detailData.items || []) {
      detailMap[item.id] = {
        duration: parseDuration(item.contentDetails?.duration || ''),
        viewCount: item.statistics?.viewCount || '0',
      };
    }

    const sources: Source[] = items.map((item: {
      id: { videoId: string };
      snippet: {
        title: string;
        description: string;
        channelTitle: string;
        publishedAt: string;
        thumbnails: { high?: { url: string }; medium?: { url: string } };
      };
    }) => {
      const videoId = item.id.videoId;
      const videoUrl = `https://www.youtube.com/watch?v=${videoId}`;
      const details = detailMap[videoId] || { duration: '', viewCount: '0' };

      return {
        id: generateId(),
        type: 'video' as const,
        title: item.snippet.title,
        url: videoUrl,
        provider: 'YouTube',
        channel: item.snippet.channelTitle,
        author: item.snippet.channelTitle,
        date: item.snippet.publishedAt,
        thumbnail: item.snippet.thumbnails?.high?.url || item.snippet.thumbnails?.medium?.url,
        description: item.snippet.description,
        relevanceScore: 85,
        quality: assessSourceQuality(videoUrl, 'video'),
        chatHistory: [],
        isSaved: false,
        isBookmarked: false,
        collectionIds: [],
        duration: details.duration,
        viewCount: parseInt(details.viewCount || '0', 10),
      };
    });

    return {
      provider: 'YouTube Data API v3',
      category: 'video',
      status: 'success',
      count: sources.length,
      sources,
      nextPageToken,
    };
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : 'Unknown YouTube API error';
    console.error('[VideoProvider] API Error:', errorMsg);
    return {
      provider: 'YouTube Data API v3',
      category: 'video',
      status: 'error',
      error: errorMsg,
      count: 0,
      sources: [],
    };
  }
}

function parseDuration(iso: string): string {
  const match = iso.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
  if (!match) return '';
  const h = parseInt(match[1] || '0', 10);
  const m = parseInt(match[2] || '0', 10);
  const s = parseInt(match[3] || '0', 10);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}
