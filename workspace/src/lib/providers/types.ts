// src/lib/providers/types.ts
import type { Source } from '@/types/research';

export interface SearchProvider {
  name: string;
  searchVideos(query: string): Promise<Source[]>;
  searchPapers(query: string): Promise<Source[]>;
  searchNews(query: string): Promise<Source[]>;
  searchWeb(query: string): Promise<Source[]>;
}

export interface VideoSearchProvider {
  name: string;
  search(query: string): Promise<Source[]>;
}

export interface PaperSearchProvider {
  name: string;
  search(query: string): Promise<Source[]>;
}

export interface NewsSearchProvider {
  name: string;
  search(query: string): Promise<Source[]>;
}

export interface WebSearchProvider {
  name: string;
  search(query: string): Promise<Source[]>;
}
