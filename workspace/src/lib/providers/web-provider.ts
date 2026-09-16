// src/lib/providers/web-provider.ts
// Live Web Search (SerpAPI & DuckDuckGo — Never fabricates mock data)

import type { Source, ProviderResult } from '@/types/research';
import { assessSourceQuality, generateId } from '@/lib/utils/scoring';

export interface WebSearchOptions {
  page?: number;
  offset?: number;
  limit?: number;
}

export async function searchWeb(
  query: string,
  options: WebSearchOptions = {}
): Promise<ProviderResult & { sources: Source[]; offset?: number; page?: number }> {
  const serpApiKey = process.env.SERP_API_KEY;
  const page = options.page || 1;
  const offset = options.offset || 0;
  const limit = options.limit || 8;

  // 1. Try SerpAPI if configured
  if (serpApiKey) {
    try {
      const url = new URL('https://serpapi.com/search');
      url.searchParams.set('q', query);
      url.searchParams.set('api_key', serpApiKey);
      url.searchParams.set('start', String(offset));
      url.searchParams.set('num', String(limit));

      const res = await fetch(url.toString(), { next: { revalidate: 3600 } });
      if (!res.ok) throw new Error(`SerpAPI error: ${res.status}`);
      const data = await res.json();
      const organic = data.organic_results || [];

      if (organic.length > 0) {
        const sources: Source[] = organic.map((item: {
          link: string;
          title: string;
          snippet?: string;
          source?: string;
          date?: string;
          thumbnail?: string;
        }) => ({
          id: generateId(),
          type: 'web' as const,
          title: item.title,
          url: item.link,
          provider: item.source || 'Web',
          date: item.date,
          thumbnail: item.thumbnail,
          description: item.snippet || 'Web reference result.',
          relevanceScore: 75,
          quality: assessSourceQuality(item.link, 'web'),
          chatHistory: [],
          isSaved: false,
          isBookmarked: false,
          collectionIds: [],
        }));

        return {
          provider: 'SerpAPI Web Search',
          category: 'web',
          status: 'success',
          count: sources.length,
          sources,
          offset: offset + sources.length,
          page: page + 1,
        };
      }
    } catch (err) {
      console.warn('[WebProvider] SerpAPI failed, falling back to DuckDuckGo:', err);
    }
  }

  // 2. Try DuckDuckGo live HTML search
  try {
    const webVariants = [
      query,
      `${query} guide overview`,
      `${query} technical reference`,
      `${query} analysis documentation`,
      `${query} insights data`,
    ];
    const targetQuery = webVariants[(page - 1) % webVariants.length] || query;
    const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(targetQuery)}`;
    const res = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      },
      next: { revalidate: 3600 },
    });

    if (!res.ok) throw new Error(`DuckDuckGo returned status ${res.status}`);
    const html = await res.text();

    const results: Source[] = [];
    const linkRe = /class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)<\/a>/g;
    const snippetRe = /class="result__snippet"[^>]*>([^<]+)</g;
    let match: RegExpExecArray | null;
    const snippets: string[] = [];

    while ((match = snippetRe.exec(html)) !== null && snippets.length < limit) {
      snippets.push(match[1].trim());
    }

    let i = 0;
    while ((match = linkRe.exec(html)) !== null && i < limit) {
      const resultUrl = match[1];
      const title = match[2].trim();

      // Clean redirect URLs if present
      let finalUrl = resultUrl;
      try {
        if (resultUrl.includes('uddg=')) {
          const parsed = new URL(resultUrl, 'https://duckduckgo.com');
          finalUrl = decodeURIComponent(parsed.searchParams.get('uddg') || resultUrl);
        }
      } catch {
        finalUrl = resultUrl;
      }

      if (finalUrl.startsWith('http')) {
        results.push({
          id: generateId(),
          type: 'web' as const,
          title,
          url: finalUrl,
          provider: 'DuckDuckGo Web',
          description: snippets[i] || 'Web reference result.',
          relevanceScore: Math.max(50, 75 - i * 3),
          quality: assessSourceQuality(finalUrl, 'web'),
          chatHistory: [],
          isSaved: false,
          isBookmarked: false,
          collectionIds: [],
        });
        i++;
      }
    }

    if (results.length > 0) {
      return {
        provider: 'DuckDuckGo Live Search',
        category: 'web',
        status: 'success',
        count: results.length,
        sources: results,
        offset: offset + results.length,
        page: page + 1,
      };
    }

    return {
      provider: 'Web Search',
      category: 'web',
      status: 'empty',
      error: `No web references found matching "${query}".`,
      count: 0,
      sources: [],
    };
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : 'Web search unavailable';
    console.error('[WebProvider] Search Error:', errorMsg);
    return {
      provider: 'Web Search',
      category: 'web',
      status: serpApiKey ? 'error' : 'not_configured',
      error: serpApiKey ? errorMsg : 'SerpAPI key (SERP_API_KEY) is not configured and live web scraper was rate-limited.',
      count: 0,
      sources: [],
    };
  }
}
