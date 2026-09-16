// src/lib/groq/schemas.ts
// Resilient Zod schemas for structured AI JSON responses with normalization transforms

import { z } from 'zod';

export const KeyPointSchema = z.object({
  text: z.string(),
  citation: z.object({
    sourceId: z.string().default(''),
    text: z.string().default(''),
    timestamp: z.string().optional(),
    page: z.string().optional(),
    section: z.string().optional(),
  }).optional(),
});

export const EntitySchema = z.object({
  name: z.string(),
  type: z.string().optional().transform((val) => {
    const lower = (val || '').toLowerCase();
    if (lower.includes('person') || lower.includes('author') || lower.includes('leader')) return 'person';
    if (lower.includes('org') || lower.includes('gov') || lower.includes('company') || lower.includes('institution')) return 'organization';
    if (lower.includes('loc') || lower.includes('city') || lower.includes('country')) return 'location';
    if (lower.includes('tech') || lower.includes('platform') || lower.includes('software')) return 'technology';
    if (lower.includes('event') || lower.includes('summit')) return 'event';
    return 'concept';
  }),
  relevance: z.number().optional().default(0.8),
});

export const AIInsightsSchema = z.object({
  summary: z.string(),
  keyPoints: z.array(KeyPointSchema),
  entities: z.array(EntitySchema).optional().default([]),
  statistics: z.array(z.string()).optional().default([]),
  claims: z.array(z.string()).optional().default([]),
  importance: z.string().optional(),
  generatedAt: z.string(),
});

export const VideoIntelligenceSchema = z.object({
  chapters: z.array(z.object({
    timestamp: z.string(),
    timestampSeconds: z.number().optional().default(0),
    title: z.string(),
    summary: z.string().optional(),
  })).optional().default([]),
  keyMoments: z.array(z.object({
    timestamp: z.string(),
    timestampSeconds: z.number().optional().default(0),
    text: z.string(),
    importance: z.string().optional().transform((val): 'high' | 'medium' | 'low' => {
      const lower = (val || '').toLowerCase();
      if (lower.includes('high') || lower.includes('major')) return 'high';
      if (lower.includes('low')) return 'low';
      return 'medium';
    }),
  })).optional().default([]),
  speakers: z.array(z.string()).optional(),
  topics: z.array(z.string()).optional().default([]),
  transcript: z.string().optional(),
});

export const PaperIntelligenceSchema = z.object({
  abstract: z.string().optional(),
  problem: z.string().optional(),
  methodology: z.string().optional(),
  results: z.string().optional(),
  keyFindings: z.array(z.string()).optional().default([]),
  limitations: z.string().optional(),
  statistics: z.array(z.string()).optional().default([]),
  relatedConcepts: z.array(z.string()).optional().default([]),
  beginnerExplanation: z.string().optional(),
});

export const OverallBriefingSchema = z.object({
  executiveSummary: z.string(),
  mainFindings: z.array(z.string()).optional().default([]),
  importantFacts: z.array(z.string()).optional().default([]),
  keyArguments: z.array(z.string()).optional().default([]),
  agreements: z.array(z.string()).optional().default([]),
  contradictions: z.array(z.string()).optional().default([]),
  differentViewpoints: z.array(z.string()).optional().default([]),
  openQuestions: z.array(z.string()).optional().default([]),
  importantStatistics: z.array(z.string()).optional().default([]),
  conclusion: z.string(),
  generatedAt: z.string(),
});

export const ComparisonResultSchema = z.object({
  sourceIds: z.array(z.string()).optional().default([]),
  similarities: z.array(z.string()).optional().default([]),
  differences: z.array(z.string()).optional().default([]),
  conflictingClaims: z.array(z.string()).optional().default([]),
  evidenceComparison: z.array(z.string()).optional().default([]),
  topicTable: z.array(z.record(z.string(), z.string())).optional().default([]),
  aiConclusion: z.string(),
  generatedAt: z.string(),
});

export const KnowledgeGraphNodeSchema = z.object({
  id: z.string(),
  label: z.string(),
  type: z.string().transform((val): 'topic' | 'person' | 'organization' | 'source' | 'concept' => {
    const lower = (val || '').toLowerCase();
    if (lower.includes('person') || lower.includes('author') || lower.includes('individual') || lower.includes('leader')) return 'person';
    if (lower.includes('org') || lower.includes('company') || lower.includes('gov') || lower.includes('institution') || lower.includes('broadcaster')) return 'organization';
    if (lower.includes('source') || lower.includes('video') || lower.includes('paper') || lower.includes('article') || lower.includes('channel')) return 'source';
    if (lower.includes('topic') || lower.includes('event') || lower.includes('theme') || lower.includes('exam') || lower.includes('program') || lower.includes('initiative')) return 'topic';
    return 'concept';
  }),
  sourceIds: z.array(z.string()).optional(),
});

export const KnowledgeGraphEdgeSchema = z.object({
  source: z.string(),
  target: z.string(),
  label: z.string().optional(),
  strength: z.number().optional().default(0.8),
});

export const KnowledgeGraphSchema = z.object({
  nodes: z.array(KnowledgeGraphNodeSchema),
  edges: z.array(KnowledgeGraphEdgeSchema),
});

export const TimelineEventSchema = z.object({
  id: z.string(),
  date: z.string(),
  title: z.string(),
  description: z.string(),
  sourceIds: z.array(z.string()).optional().default([]),
  importance: z.string().optional().transform((val): 'high' | 'medium' | 'low' => {
    const lower = (val || '').toLowerCase();
    if (lower.includes('high') || lower.includes('crit') || lower.includes('major')) return 'high';
    if (lower.includes('low') || lower.includes('minor')) return 'low';
    return 'medium';
  }),
});

export const TimelineSchema = z.object({
  events: z.array(TimelineEventSchema),
});

export const ResearchReportSchema = z.object({
  topic: z.string(),
  executiveSummary: z.string(),
  background: z.string().optional().default(''),
  keyFindings: z.array(z.string()).optional().default([]),
  evidence: z.array(z.object({
    claim: z.string(),
    sources: z.array(z.object({
      sourceId: z.string().optional().default(''),
      text: z.string(),
      timestamp: z.string().optional(),
      page: z.string().optional(),
      section: z.string().optional(),
    })).optional().default([]),
  })).optional().default([]),
  perspectives: z.array(z.object({
    viewpoint: z.string(),
    sources: z.array(z.string()).optional().default([]),
  })).optional().default([]),
  contradictions: z.array(z.string()).optional().default([]),
  statistics: z.array(z.string()).optional().default([]),
  conclusion: z.string(),
  generatedAt: z.string(),
});

export const InsightActionResultSchema = z.object({
  result: z.string(),
  citations: z.array(z.object({
    sourceId: z.string(),
    text: z.string(),
    timestamp: z.string().optional(),
    page: z.string().optional(),
  })).optional(),
});

export const ChatResponseSchema = z.object({
  message: z.string(),
  citations: z.array(z.object({
    sourceId: z.string(),
    text: z.string(),
    timestamp: z.string().optional(),
    page: z.string().optional(),
    section: z.string().optional(),
  })).optional(),
});
