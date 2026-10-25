// src/types/insights.ts — shapes returned by /api/search/{topics,dashboard,summary}

export interface FileTopics {
  topics: string[];
  events: string[];
  origin?: 'index' | 'llm';
}

export interface DashboardFile {
  id: string;
  sourceId: string;
  libraryId?: string | null;
  libraryName?: string | null;
  category: string;                 // document | image | video | audio
  title: string;
  fileType: string;                 // extension
  fileSize: number;
  relPath?: string;
  folder: string;
  relevanceScore: number;           // 0..1
  modifiedAt?: string | null;
  takenAt?: string | null;
  indexedAt?: string | null;
  topics: string[];
  events: string[];
}

export interface DashboardData {
  query: string;
  totals: {
    candidates: number;             // every ranked file of the search
    kept: number;                   // within the threshold
    topScore: number;
    relativeThreshold: number;
    minScore: number;
    totalBytes: number;
    topicsFor: number;              // files (best first) whose topics were derived
  };
  files: DashboardFile[];
}

export type SummaryStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled';

export interface SummaryDoc {
  id: string;
  sourceId: string;
  libraryId?: string | null;
  libraryName?: string | null;
  title: string;
  category: string;
  fileType: string;
  relevanceScore: number;
  folder?: string;
  relPath?: string;
  state: 'pending' | 'done';
  summary: string | null;
  topics: string[];
  events: string[];
  source: 'llm' | 'cache' | 'extractive' | null;
  error?: string;
}

export interface SummaryJob {
  jobId: string;
  status: SummaryStatus;
  progress: { done: number; total: number };
  docs: SummaryDoc[];
  overall: string | null;
  overallSource: 'llm' | 'extractive' | null;
  usage: { calls: number; promptTokens: number; completionTokens: number; cachedDocs: number };
  warnings: string[];
  error: string | null;
}

/** loading keeps the previous data (a new threshold re-fetches over the old chart) */
export interface AsyncData<T> {
  status: 'idle' | 'loading' | 'ready' | 'error';
  data: T | null;
  error: string | null;
}
