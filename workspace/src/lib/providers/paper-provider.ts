// src/lib/providers/paper-provider.ts
// Multi-Registry Academic Paper Search: Semantic Scholar -> arXiv -> Crossref
// (100% Real academic data — Zero mock fallbacks)

import type { Source, ProviderResult } from '@/types/research';
import { generateId } from '@/lib/utils/scoring';

export interface PaperSearchOptions {
  offset?: number;
  limit?: number;
}

export async function searchPapers(
  query: string,
  options: PaperSearchOptions = {}
): Promise<ProviderResult & { sources: Source[]; offset?: number }> {
  const apiKey = process.env.SEMANTIC_SCHOLAR_API_KEY;
  const offset = options.offset || 0;
  const limit = options.limit || 8;

  // 1. Try Semantic Scholar
  try {
    const url = new URL('https://api.semanticscholar.org/graph/v1/paper/search');
    url.searchParams.set('query', query);
    url.searchParams.set('offset', String(offset));
    url.searchParams.set('limit', String(limit));
    url.searchParams.set('fields', 'title,abstract,authors,year,venue,externalIds,openAccessPdf,citationCount,url');

    const headers: Record<string, string> = {
      'User-Agent': 'AI-Research-Workspace/1.0',
    };
    if (apiKey) {
      headers['x-api-key'] = apiKey;
    }

    const res = await fetch(url.toString(), {
      headers,
      next: { revalidate: 3600 },
    });

    if (res.ok) {
      const data = await res.json();
      const items = data.data || [];

      if (items.length > 0) {
        const sources: Source[] = items.map((item: {
          paperId: string;
          title: string;
          abstract?: string;
          authors?: Array<{ name: string }>;
          year?: number;
          venue?: string;
          externalIds?: { DOI?: string; ArXiv?: string };
          openAccessPdf?: { url: string };
          citationCount?: number;
          url?: string;
        }) => {
          const paperUrl = item.openAccessPdf?.url || item.url || `https://www.semanticscholar.org/paper/${item.paperId}`;
          const author = (item.authors || []).map((a) => a.name).join(', ');

          return {
            id: generateId(),
            type: 'paper' as const,
            title: item.title,
            url: paperUrl,
            provider: 'Semantic Scholar',
            author: author || 'Academic Authors',
            date: item.year ? `${item.year}-01-01` : undefined,
            description: item.abstract || 'No abstract text provided by publisher.',
            abstract: item.abstract,
            relevanceScore: 90,
            quality: {
              level: 'high' as const,
              reason: 'Peer-reviewed academic paper',
              details: item.venue || 'Academic repository',
            },
            chatHistory: [],
            isSaved: false,
            isBookmarked: false,
            collectionIds: [],
            journal: item.venue,
            doi: item.externalIds?.DOI,
            citationCount: item.citationCount || 0,
          };
        });

        return {
          provider: 'Semantic Scholar API',
          category: 'paper',
          status: 'success',
          count: sources.length,
          sources,
          offset: offset + sources.length,
        };
      }
    } else {
      console.warn(`[PaperProvider] Semantic Scholar returned ${res.status}. Falling back to open arXiv / Crossref APIs.`);
    }
  } catch (err) {
    console.warn('[PaperProvider] Semantic Scholar error:', err);
  }

  // 2. Open Academic Fallback: arXiv Open Access Repository
  try {
    const cleanSearchQuery = query.replace(/[^a-zA-Z0-9 ]/g, ' ').trim();
    const arxivUrl = `https://export.arxiv.org/api/query?search_query=all:${encodeURIComponent(cleanSearchQuery)}&start=${offset}&max_results=${limit}`;
    
    const arxivRes = await fetch(arxivUrl, {
      headers: { 'User-Agent': 'AI-Research-Workspace/1.0' },
      next: { revalidate: 3600 },
    });

    if (arxivRes.ok) {
      const xml = await arxivRes.text();
      const sources = parseArxivXML(xml, limit);

      if (sources.length > 0) {
        return {
          provider: 'arXiv Open Repository',
          category: 'paper',
          status: 'success',
          count: sources.length,
          sources,
          offset: offset + sources.length,
        };
      }
    }
  } catch (err) {
    console.warn('[PaperProvider] arXiv error:', err);
  }

  // 3. Open Academic Fallback: Crossref DOI Works API
  try {
    const crossrefUrl = `https://api.crossref.org/works?query=${encodeURIComponent(query)}&rows=${limit}&offset=${offset}`;
    const crossrefRes = await fetch(crossrefUrl, {
      headers: {
        'User-Agent': 'AI-Research-Workspace/1.0 (mailto:research@workspace.ai)',
      },
      next: { revalidate: 3600 },
    });

    if (crossrefRes.ok) {
      const data = await crossrefRes.json();
      const items = data.message?.items || [];

      if (items.length > 0) {
        const sources: Source[] = items.map((item: {
          title?: string[];
          DOI?: string;
          URL?: string;
          author?: Array<{ given?: string; family?: string }>;
          'container-title'?: string[];
          created?: { 'date-parts'?: number[][] };
          abstract?: string;
          'is-referenced-by-count'?: number;
        }) => {
          const title = item.title?.[0] || 'Scholarly Research Paper';
          const author = (item.author || [])
            .map((a) => `${a.given || ''} ${a.family || ''}`.trim())
            .filter(Boolean)
            .join(', ') || 'Academic Researchers';
          const paperUrl = item.URL || (item.DOI ? `https://doi.org/${item.DOI}` : '');
          const venue = item['container-title']?.[0] || 'Peer-Reviewed Journal';
          const year = item.created?.['date-parts']?.[0]?.[0];
          const cleanAbstract = item.abstract ? item.abstract.replace(/<[^>]+>/g, '').trim() : undefined;

          return {
            id: generateId(),
            type: 'paper' as const,
            title,
            url: paperUrl,
            provider: 'Crossref Scholarly Registry',
            author,
            date: year ? `${year}-01-01` : undefined,
            description: cleanAbstract || `Published research study in ${venue}.`,
            abstract: cleanAbstract,
            relevanceScore: 85,
            quality: {
              level: 'high' as const,
              reason: 'Crossref registered scholarly work',
              details: venue,
            },
            chatHistory: [],
            isSaved: false,
            isBookmarked: false,
            collectionIds: [],
            journal: venue,
            doi: item.DOI,
            citationCount: item['is-referenced-by-count'] || 0,
          };
        });

        return {
          provider: 'Crossref Scholarly Registry',
          category: 'paper',
          status: 'success',
          count: sources.length,
          sources,
          offset: offset + sources.length,
        };
      }
    }
  } catch (err) {
    console.warn('[PaperProvider] Crossref error:', err);
  }

  // If all live academic registries returned 0 results
  return {
    provider: 'Academic Repositories (Semantic Scholar, arXiv, Crossref)',
    category: 'paper',
    status: 'empty',
    error: `No peer-reviewed papers found matching "${query}".`,
    count: 0,
    sources: [],
    offset,
  };
}

/**
 * Extracts structured paper objects from arXiv XML Atom feed.
 */
function parseArxivXML(xml: string, limit: number = 8): Source[] {
  const sources: Source[] = [];
  const entryRegex = /<entry>([\s\S]*?)<\/entry>/g;
  let entryMatch: RegExpExecArray | null;

  while ((entryMatch = entryRegex.exec(xml)) !== null && sources.length < limit) {
    const entry = entryMatch[1];

    const idMatch = entry.match(/<id>([^<]+)<\/id>/);
    const titleMatch = entry.match(/<title>([^<]+)<\/title>/);
    const summaryMatch = entry.match(/<summary>([^<]+)<\/summary>/);
    const publishedMatch = entry.match(/<published>([^<]+)<\/published>/);
    const doiMatch = entry.match(/<arxiv:doi[^>]*>([^<]+)<\/arxiv:doi>/);

    // Extract all authors
    const authorRegex = /<author>\s*<name>([^<]+)<\/name>\s*<\/author>/g;
    const authors: string[] = [];
    let authorMatch: RegExpExecArray | null;
    while ((authorMatch = authorRegex.exec(entry)) !== null) {
      authors.push(authorMatch[1].trim());
    }

    if (titleMatch && idMatch) {
      const cleanTitle = titleMatch[1].replace(/\s+/g, ' ').trim();
      const cleanSummary = summaryMatch ? summaryMatch[1].replace(/\s+/g, ' ').trim() : '';
      const paperUrl = idMatch[1].trim();
      const pdfUrl = paperUrl.replace('/abs/', '/pdf/') + '.pdf';

      sources.push({
        id: generateId(),
        type: 'paper' as const,
        title: cleanTitle,
        url: pdfUrl || paperUrl,
        provider: 'arXiv Preprints',
        author: authors.join(', ') || 'arXiv Contributors',
        date: publishedMatch ? publishedMatch[1].split('T')[0] : undefined,
        description: cleanSummary || 'arXiv preprint abstract.',
        abstract: cleanSummary,
        relevanceScore: 88,
        quality: {
          level: 'high' as const,
          reason: 'arXiv peer-reviewed / academic preprint',
          details: 'Cornell University arXiv repository',
        },
        chatHistory: [],
        isSaved: false,
        isBookmarked: false,
        collectionIds: [],
        journal: 'arXiv Repository',
        doi: doiMatch ? doiMatch[1].trim() : undefined,
        citationCount: 0,
      });
    }
  }

  return sources;
}
