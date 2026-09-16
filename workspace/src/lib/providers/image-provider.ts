// src/lib/providers/image-provider.ts
// Live Internet Image Search using SerpAPI Google Images

import { generateId } from '@/lib/utils/scoring';

export interface InternetImageResult {
  id: string;
  title: string;
  url: string;
  thumbnail: string;
  sourceUrl: string;
  domain: string;
  sourceType: 'image';
  relevanceScore: number;
}

export async function searchInternetImages(query: string, limit = 8): Promise<InternetImageResult[]> {
  const serpApiKey = process.env.SERP_API_KEY;
  if (!serpApiKey) return [];

  try {
    const url = new URL('https://serpapi.com/search');
    url.searchParams.set('engine', 'google_images');
    url.searchParams.set('q', query);
    url.searchParams.set('api_key', serpApiKey);
    url.searchParams.set('num', String(limit));

    const res = await fetch(url.toString(), { next: { revalidate: 3600 } });
    if (!res.ok) return [];

    const data = await res.json();
    const imagesResults = data.images_results || [];

    return imagesResults.slice(0, limit).map((img: {
      title?: string;
      original?: string;
      thumbnail?: string;
      source?: string;
      link?: string;
    }) => {
      let domain = 'web';
      try {
        if (img.link) domain = new URL(img.link).hostname.replace(/^www\./, '');
      } catch {
        // ignore
      }

      return {
        id: generateId(),
        title: img.title || query,
        url: img.original || img.thumbnail || '',
        thumbnail: img.thumbnail || img.original || '',
        sourceUrl: img.link || img.original || '',
        domain,
        sourceType: 'image' as const,
        relevanceScore: 0.85,
      };
    });
  } catch (err) {
    console.warn('[ImageProvider] SerpAPI image search failed:', err);
    return [];
  }
}
