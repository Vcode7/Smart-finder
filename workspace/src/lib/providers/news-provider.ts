// src/lib/providers/news-provider.ts
// Multi-Registry Live News & Articles Provider: NewsAPI -> Google News RSS
// (100% Real, live published articles — Zero mock data)

import type { Source, ProviderResult } from '@/types/research';
import { assessSourceQuality, generateId } from '@/lib/utils/scoring';

export interface NewsSearchResult {
  articleResult: ProviderResult;
  reportResult: ProviderResult;
  articles: Source[];
  reports: Source[];
}

export interface NewsSearchOptions {
  page?: number;
  offset?: number;
  limit?: number;
}

export async function searchNews(query: string, options: NewsSearchOptions = {}): Promise<NewsSearchResult> {
  const apiKey = process.env.NEWS_API_KEY;
  const page = options.page || 1;
  const pageSize = options.limit || 15;

  // 1. Try NewsAPI (if configured)
  if (apiKey) {
    try {
      console.log(`[NewsProvider] Querying NewsAPI for "${query}" (page ${page})...`);
      const url = new URL('https://newsapi.org/v2/everything');
      url.searchParams.set('q', query);
      url.searchParams.set('sortBy', 'relevancy');
      url.searchParams.set('pageSize', String(pageSize));
      url.searchParams.set('page', String(page));
      url.searchParams.set('language', 'en');

      const res = await fetch(url.toString(), {
        headers: {
          'User-Agent': 'AI-Research-Workspace/1.0',
          'X-Api-Key': apiKey,
        },
        next: { revalidate: 1800 },
      });

      if (res.ok) {
        const data = await res.json();
        const rawArticles = data.articles || [];

        if (rawArticles.length > 0) {
          const allSources: Source[] = rawArticles.map((item: {
            url: string;
            title: string;
            description?: string;
            author?: string;
            source: { name: string };
            publishedAt: string;
            urlToImage?: string;
          }) => ({
            id: generateId(),
            type: 'article' as const,
            title: item.title,
            url: item.url,
            provider: item.source?.name || 'NewsAPI',
            author: item.author || item.source?.name,
            date: item.publishedAt,
            thumbnail: item.urlToImage,
            description: item.description || `Live news report on ${query}.`,
            relevanceScore: 88,
            quality: assessSourceQuality(item.url, 'article'),
            chatHistory: [],
            isSaved: false,
            isBookmarked: false,
            collectionIds: [],
          }));

          return splitArticlesAndReports(allSources, 'NewsAPI');
        } else {
          console.warn(`[NewsProvider] NewsAPI returned 0 articles for "${query}". Falling back to live Google News feed.`);
        }
      } else {
        const errText = await res.text().catch(() => '');
        console.warn(`[NewsProvider] NewsAPI returned status ${res.status}: ${errText}. Falling back to Google News feed.`);
      }
    } catch (err) {
      console.warn('[NewsProvider] NewsAPI fetch error:', err);
    }
  } else {
    console.log('[NewsProvider] NEWS_API_KEY not configured in .env.local. Using live Google News search feed.');
  }

  // 2. Open Live News Fallback: Google News RSS Search Feed (100% Real, keyless live news)
  try {
    const pageSuffix = page > 1 ? ` ${page === 2 ? 'analysis' : page === 3 ? 'latest' : 'update'}` : '';
    const cleanQuery = encodeURIComponent(`${query.trim()}${pageSuffix}`);
    const gnewsUrl = `https://news.google.com/rss/search?q=${cleanQuery}&hl=en-US&gl=US&ceid=US:en`;

    const res = await fetch(gnewsUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      },
      next: { revalidate: 1800 },
    });

    if (res.ok) {
      const xml = await res.text();
      const sources = parseGoogleNewsRSS(xml, query);

      if (sources.length > 0) {
        return splitArticlesAndReports(sources, 'Google News Live Feed');
      }
    }
  } catch (err) {
    console.warn('[NewsProvider] Google News RSS error:', err);
  }

  // 3. If no live news articles were found across both feeds
  return {
    articleResult: {
      provider: 'News Publications (NewsAPI & Google News)',
      category: 'article',
      status: 'empty',
      error: `No live news articles found matching "${query}".`,
      count: 0,
    },
    reportResult: {
      provider: 'Policy Publications',
      category: 'reports',
      status: 'empty',
      error: `No policy reports found matching "${query}".`,
      count: 0,
    },
    articles: [],
    reports: [],
  };
}

interface RawNewsApiArticle {
  title: string;
  url: string;
  source: { name: string };
  author?: string;
  publishedAt: string;
  urlToImage?: string;
  description?: string;
}

/**
 * Specifically fetches more Articles & News items only.
 */
export async function searchArticlesOnly(
  query: string,
  options: NewsSearchOptions = {}
): Promise<{ sources: Source[]; providerResult: ProviderResult; page?: number }> {
  const apiKey = process.env.NEWS_API_KEY;
  const page = options.page || 1;
  const pageSize = options.limit || 8;

  if (apiKey) {
    try {
      const url = new URL('https://newsapi.org/v2/everything');
      url.searchParams.set('q', query);
      url.searchParams.set('sortBy', 'relevancy');
      url.searchParams.set('pageSize', String(pageSize));
      url.searchParams.set('page', String(page));
      url.searchParams.set('language', 'en');

      const res = await fetch(url.toString(), {
        headers: { 'User-Agent': 'AI-Research-Workspace/1.0', 'X-Api-Key': apiKey },
        next: { revalidate: 1800 },
      });

      if (res.ok) {
        const data = await res.json();
        const rawArticles: RawNewsApiArticle[] = data.articles || [];
        if (rawArticles.length > 0) {
          const sources: Source[] = rawArticles.map((item: RawNewsApiArticle) => ({
            id: generateId(),
            type: 'article' as const,
            title: item.title,
            url: item.url,
            provider: item.source?.name || 'NewsAPI',
            author: item.author || item.source?.name,
            date: item.publishedAt,
            thumbnail: item.urlToImage,
            description: item.description || `Article on ${query}.`,
            relevanceScore: 88,
            quality: assessSourceQuality(item.url, 'article'),
            chatHistory: [],
            isSaved: false,
            isBookmarked: false,
            collectionIds: [],
          }));

          return {
            sources,
            providerResult: {
              provider: 'NewsAPI Articles',
              category: 'article',
              status: 'success',
              count: sources.length,
            },
            page: page + 1,
          };
        }
      }
    } catch (err) {
      console.warn('[searchArticlesOnly] NewsAPI error:', err);
    }
  }

  // Google News RSS fallback for articles
  try {
    const queryVariants = [query, `${query} news`, `${query} analysis`, `${query} coverage`, `${query} 2025`];
    const targetQuery = queryVariants[(page - 1) % queryVariants.length] || query;
    const gnewsUrl = `https://news.google.com/rss/search?q=${encodeURIComponent(targetQuery)}&hl=en-US&gl=US&ceid=US:en`;

    const res = await fetch(gnewsUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      },
      next: { revalidate: 1800 },
    });

    if (res.ok) {
      const xml = await res.text();
      const sources = parseGoogleNewsRSS(xml, query, Math.max(25, pageSize));
      const articles = sources.map((s) => ({ ...s, type: 'article' as const }));

      if (articles.length > 0) {
        return {
          sources: articles,
          providerResult: {
            provider: 'Google News Articles Feed',
            category: 'article',
            status: 'success',
            count: articles.length,
          },
          page: page + 1,
        };
      }
    }
  } catch (err) {
    console.warn('[searchArticlesOnly] Google News error:', err);
  }

  return {
    sources: [],
    providerResult: {
      provider: 'News Publications',
      category: 'article',
      status: 'empty',
      error: `No more news articles found for "${query}".`,
      count: 0,
    },
    page,
  };
}

/**
 * Specifically fetches more Policy Reports & Institutional Publications only.
 */
export async function searchReportsOnly(
  query: string,
  options: NewsSearchOptions = {}
): Promise<{ sources: Source[]; providerResult: ProviderResult; page?: number }> {
  const apiKey = process.env.NEWS_API_KEY;
  const page = options.page || 1;
  const pageSize = options.limit || 8;
  const policyQuery = `${query} AND (policy OR report OR framework OR directive OR whitepaper OR analysis)`;

  if (apiKey) {
    try {
      const url = new URL('https://newsapi.org/v2/everything');
      url.searchParams.set('q', policyQuery);
      url.searchParams.set('sortBy', 'relevancy');
      url.searchParams.set('pageSize', String(pageSize));
      url.searchParams.set('page', String(page));
      url.searchParams.set('language', 'en');

      const res = await fetch(url.toString(), {
        headers: { 'User-Agent': 'AI-Research-Workspace/1.0', 'X-Api-Key': apiKey },
        next: { revalidate: 1800 },
      });

      if (res.ok) {
        const data = await res.json();
        const rawArticles: RawNewsApiArticle[] = data.articles || [];
        if (rawArticles.length > 0) {
          const sources: Source[] = rawArticles.map((item: RawNewsApiArticle) => ({
            id: generateId(),
            type: 'report' as const,
            title: item.title,
            url: item.url,
            provider: item.source?.name || 'Policy Report',
            author: item.author || item.source?.name,
            date: item.publishedAt,
            thumbnail: item.urlToImage,
            description: item.description || `Policy whitepaper on ${query}.`,
            relevanceScore: 90,
            quality: assessSourceQuality(item.url, 'report'),
            chatHistory: [],
            isSaved: false,
            isBookmarked: false,
            collectionIds: [],
          }));

          return {
            sources,
            providerResult: {
              provider: 'NewsAPI Policy Reports',
              category: 'reports',
              status: 'success',
              count: sources.length,
            },
            page: page + 1,
          };
        }
      }
    } catch (err) {
      console.warn('[searchReportsOnly] NewsAPI error:', err);
    }
  }

  // Google News RSS fallback for reports
  try {
    const reportVariants = [
      `${query} policy report`,
      `${query} government whitepaper`,
      `${query} strategic framework`,
      `${query} institutional directive`,
    ];
    const targetQuery = reportVariants[(page - 1) % reportVariants.length] || `${query} policy report`;
    const gnewsUrl = `https://news.google.com/rss/search?q=${encodeURIComponent(targetQuery)}&hl=en-US&gl=US&ceid=US:en`;

    const res = await fetch(gnewsUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      },
      next: { revalidate: 1800 },
    });

    if (res.ok) {
      const xml = await res.text();
      const sources = parseGoogleNewsRSS(xml, query, Math.max(25, pageSize));
      const reports = sources.map((s) => ({ ...s, type: 'report' as const }));

      if (reports.length > 0) {
        return {
          sources: reports,
          providerResult: {
            provider: 'Google News Policy Feed',
            category: 'reports',
            status: 'success',
            count: reports.length,
          },
          page: page + 1,
        };
      }
    }
  } catch (err) {
    console.warn('[searchReportsOnly] Google News error:', err);
  }

  return {
    sources: [],
    providerResult: {
      provider: 'Policy Publications',
      category: 'reports',
      status: 'empty',
      error: `No more policy reports found for "${query}".`,
      count: 0,
    },
    page,
  };
}

/**
 * Splits raw news items into mainstream Articles and institutional Policy Reports.
 */
function splitArticlesAndReports(sources: Source[], providerName: string): NewsSearchResult {
  const reports: Source[] = sources
    .filter((a) =>
      a.title.toLowerCase().includes('report') ||
      a.title.toLowerCase().includes('policy') ||
      a.title.toLowerCase().includes('directive') ||
      a.title.toLowerCase().includes('ministry') ||
      a.title.toLowerCase().includes('whitepaper') ||
      a.title.toLowerCase().includes('survey') ||
      a.title.toLowerCase().includes('government') ||
      a.quality.level === 'high'
    )
    .slice(0, 6)
    .map((s) => ({ ...s, type: 'report' as const }));

  const reportIds = new Set(reports.map((r) => r.id));
  const articles = sources.filter((a) => !reportIds.has(a.id)).slice(0, 8);

  return {
    articleResult: {
      provider: providerName,
      category: 'article',
      status: articles.length > 0 ? 'success' : 'empty',
      count: articles.length,
    },
    reportResult: {
      provider: `${providerName} (Policy & Reports)`,
      category: 'reports',
      status: reports.length > 0 ? 'success' : 'empty',
      count: reports.length,
    },
    articles,
    reports,
  };
}

/**
 * Parses Google News XML RSS feed into structured Source items.
 */
function parseGoogleNewsRSS(xml: string, query: string, limit: number = 30): Source[] {
  const sources: Source[] = [];
  const itemRegex = /<item>([\s\S]*?)<\/item>/g;
  let itemMatch: RegExpExecArray | null;

  while ((itemMatch = itemRegex.exec(xml)) !== null && sources.length < limit) {
    const itemContent = itemMatch[1];

    const titleMatch = itemContent.match(/<title>([\s\S]*?)<\/title>/);
    const linkMatch = itemContent.match(/<link>([\s\S]*?)<\/link>/);
    const pubDateMatch = itemContent.match(/<pubDate>([\s\S]*?)<\/pubDate>/);
    const sourceMatch = itemContent.match(/<source[^>]*>([\s\S]*?)<\/source>/);

    if (titleMatch && linkMatch) {
      const rawTitle = titleMatch[1].replace(/<!\[CDATA\[(.*?)\]\]>/g, '$1').trim();
      const rawLink = linkMatch[1].replace(/<!\[CDATA\[(.*?)\]\]>/g, '$1').trim();
      const rawPublisher = sourceMatch ? sourceMatch[1].replace(/<!\[CDATA\[(.*?)\]\]>/g, '$1').trim() : '';

      // Strip publisher suffix from title if present (e.g. "Title - Times of India")
      let cleanTitle = rawTitle;
      let publisher = rawPublisher || 'News Publisher';
      if (rawTitle.includes(' - ')) {
        const lastDash = rawTitle.lastIndexOf(' - ');
        if (!rawPublisher) {
          publisher = rawTitle.slice(lastDash + 3).trim();
        }
        cleanTitle = rawTitle.slice(0, lastDash).trim();
      }

      let formattedDate: string | undefined;
      if (pubDateMatch) {
        try {
          formattedDate = new Date(pubDateMatch[1]).toISOString().split('T')[0];
        } catch {
          // ignore date parse error
        }
      }

      sources.push({
        id: generateId(),
        type: 'article' as const,
        title: cleanTitle,
        url: rawLink,
        provider: publisher,
        author: publisher,
        date: formattedDate,
        description: `Published news article regarding ${query} by ${publisher}.`,
        relevanceScore: 85,
        quality: assessSourceQuality(rawLink, 'article'),
        chatHistory: [],
        isSaved: false,
        isBookmarked: false,
        collectionIds: [],
      });
    }
  }

  return sources;
}
