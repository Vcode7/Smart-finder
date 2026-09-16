// src/types/research.ts
// Core type definitions for the AI Research Workspace

export type SourceType = 'video' | 'paper' | 'article' | 'report' | 'web';

export type SourceQualityLevel = 'high' | 'medium' | 'low';

export interface SourceQuality {
  level: SourceQualityLevel;
  reason: string;
  details?: string;
}

export interface Citation {
  sourceId: string;
  text: string;
  timestamp?: string; // for videos: "2:34"
  page?: string;      // for papers: "p.5" or "Section 3.2"
  section?: string;   // for articles
}

export interface KeyPoint {
  text: string;
  citation?: Citation;
}

export interface Entity {
  name: string;
  type: 'person' | 'organization' | 'location' | 'concept' | 'technology' | 'event';
  relevance: number; // 0-1
}

export interface VideoChapter {
  timestamp: string; // "2:34"
  timestampSeconds: number;
  title: string;
  summary?: string;
}

export interface VideoKeyMoment {
  timestamp: string;
  timestampSeconds: number;
  text: string;
  importance: 'high' | 'medium' | 'low';
}

export interface VideoIntelligence {
  transcript?: string;
  chapters: VideoChapter[];
  keyMoments: VideoKeyMoment[];
  speakers?: string[];
  topics: string[];
}

export interface PaperIntelligence {
  abstract?: string;
  problem?: string;
  methodology?: string;
  results?: string;
  keyFindings: string[];
  limitations?: string;
  statistics: string[];
  relatedConcepts: string[];
  beginnerExplanation?: string;
}

export interface AIInsights {
  summary: string;
  keyPoints: KeyPoint[];
  entities: Entity[];
  statistics?: string[];
  claims?: string[];
  importance?: string;
  videoIntelligence?: VideoIntelligence;
  paperIntelligence?: PaperIntelligence;
  generatedAt: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  citations?: Citation[];
}

export interface Source {
  id: string;
  type: SourceType;
  title: string;
  url: string;
  provider: string;      // "YouTube", "arXiv", "BBC News", etc.
  author?: string;
  channel?: string;
  date?: string;
  thumbnail?: string;
  description?: string;
  relevanceScore: number; // 0-100
  quality: SourceQuality;
  aiInsights?: AIInsights;
  chatHistory: ChatMessage[];
  isSaved: boolean;
  isBookmarked: boolean;
  collectionIds: string[];
  // Video-specific
  duration?: string;
  viewCount?: number;
  transcript?: string;
  hasTranscript?: boolean;
  // Paper-specific
  journal?: string;
  doi?: string;
  citationCount?: number;
  abstract?: string;
  // Article-specific
  wordCount?: number;
}

export interface KnowledgeGraphNode {
  id: string;
  label: string;
  type: 'topic' | 'person' | 'organization' | 'source' | 'concept';
  sourceIds?: string[];
  x?: number;
  y?: number;
}

export interface KnowledgeGraphEdge {
  source: string;
  target: string;
  label?: string;
  strength: number; // 0-1
}

export interface KnowledgeGraph {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
}

export interface TimelineEvent {
  id: string;
  date: string;
  title: string;
  description: string;
  sourceIds: string[];
  importance: 'high' | 'medium' | 'low';
}

export interface ResearchCollection {
  id: string;
  name: string;
  description?: string;
  sourceIds: string[];
  createdAt: string;
  updatedAt: string;
}

export interface OverallBriefing {
  executiveSummary: string;
  mainFindings: string[];
  importantFacts: string[];
  keyArguments: string[];
  agreements: string[];
  contradictions: string[];
  differentViewpoints: string[];
  openQuestions: string[];
  importantStatistics: string[];
  conclusion: string;
  generatedAt: string;
}

export interface ComparisonResult {
  sourceIds: string[];
  similarities: string[];
  differences: string[];
  conflictingClaims: string[];
  evidenceComparison: string[];
  topicTable: Array<Record<string, string>>;
  aiConclusion: string;
  generatedAt: string;
}

export interface ResearchReport {
  topic: string;
  executiveSummary: string;
  background: string;
  keyFindings: string[];
  evidence: Array<{ claim: string; sources: Citation[] }>;
  perspectives: Array<{ viewpoint: string; sources: string[] }>;
  contradictions: string[];
  statistics: string[];
  conclusion: string;
  sources: Source[];
  generatedAt: string;
}

export type PaneContentType =
  | 'insights'
  | 'video'
  | 'paper'
  | 'timeline'
  | 'source'
  | 'graph'
  | 'compare'
  | 'chat'
  | 'article'
  | 'report';

export interface WorkspacePane {
  id: string;
  contentType?: PaneContentType;
  sourceId?: string;
  isMinimized: boolean;
  isMaximized: boolean;
  chatOpen: boolean;
  insightsOpen: boolean;
}

export type WorkspaceLayout = '1' | '2' | '3' | '4';

export type ProviderStatus = 'success' | 'not_configured' | 'error' | 'empty';

export interface ProviderResult {
  provider: string;
  category: SourceType | 'all' | 'reports';
  status: ProviderStatus;
  count: number;
  error?: string;
  message?: string;
}

export interface ResearchSession {
  id: string;
  topic: string;
  sources: Source[];
  collections: ResearchCollection[];
  overallBriefing?: OverallBriefing;
  knowledgeGraph?: KnowledgeGraph;
  timeline?: TimelineEvent[];
  reports: ResearchReport[];
  comparisons: ComparisonResult[];
  providerStatuses?: Record<string, ProviderResult>;
  createdAt: string;
  updatedAt: string;
  // UI state
  activeTab: TabType;
  workspacePanes: WorkspacePane[];
  workspaceLayout: WorkspaceLayout;
}

export type TabType = 'overview' | 'videos' | 'papers' | 'articles' | 'reports' | 'sources';

export interface SearchResults {
  videos: Source[];
  papers: Source[];
  articles: Source[];
  reports: Source[];
  web: Source[];
}

// API request/response types
export interface SearchRequest {
  topic: string;
  sessionId: string;
}

export interface SummarizeRequest {
  sourceId: string;
  source: Source;
}

export interface InsightRequest {
  action: InsightAction;
  sourceId: string;
  source: Source;
  compareWithId?: string;
  compareWith?: Source;
  question?: string;
}

export type InsightAction =
  | 'summarize'
  | 'explain'
  | 'extract_facts'
  | 'extract_statistics'
  | 'find_claims'
  | 'find_people_orgs'
  | 'find_contradictions'
  | 'why_important'
  | 'ask_question'
  | 'compare';

export interface ChatRequest {
  sourceId: string;
  source: Source;
  message: string;
  history: ChatMessage[];
}

export interface CompareRequest {
  sources: Source[];
}

export interface ReportRequest {
  topic: string;
  sources: Source[];
  briefing?: OverallBriefing;
}

export interface BriefRequest {
  topic: string;
  sources: Source[];
}

export interface EntitiesRequest {
  sources: Source[];
}

export interface TimelineRequest {
  topic: string;
  sources: Source[];
}

export interface ScrapedSourceItem {
  id: string;
  category: 'paper' | 'article' | 'report' | 'web' | 'video' | 'image' | string;
  title: string;
  url: string;
  snippet: string;
  domain: string;
  platform: string;
  publishedDate?: string;
  author?: string;
  thumbnail?: string;
  relevanceScore: number;
}

export interface MatchingFrame {
  id: string;
  frameNumber: number;
  sceneId: number;
  timestamp: number;
  framePath: string;
  similarity: number;
  isFaceMatch?: boolean;
  faceSimilarity?: number;
  visualDescription?: string;
}

export interface CrossSourceItem {
  id: string;
  sourceId: string;
  category: 'document' | 'video' | 'image' | 'audio' | string;
  title: string;
  originalName: string;
  fileType: string;
  fileSize: number;
  uploadDate: string;
  snippet: string;
  relevanceScore: number;
  pageNum?: number;
  timestamp?: number;
}

export interface LocalCategorizedItem {
  id: string;
  sourceId: string;
  category: 'video' | 'document' | 'image' | 'audio' | string;
  title: string;
  originalName: string;
  fileType: string;
  fileSize: number;
  uploadDate: string;
  relevanceScore: number;
  snippet: string;
  fullContext?: string;
  isFaceMatch?: boolean;
  faceSimilarity?: number;
  detectedEntity?: string;
  sectionTitle?: string;
  pageNum?: number;
  pageCount?: number;
  startTime?: number;
  endTime?: number;
  duration?: number;
  matchingFrames?: MatchingFrame[];
  primaryFrame?: MatchingFrame;
  thumbnail?: string;
  description?: string;
  ocrText?: string;
  relatedCrossSources?: CrossSourceItem[];
}

export interface InternetCategorizedItem {
  id: string;
  category: 'web' | 'news' | 'paper' | 'video' | 'image';
  title: string;
  url: string;
  snippet: string;
  domain: string;
  publishedDate?: string;
  author?: string;
  thumbnail?: string;
  relevanceScore: number;
}
