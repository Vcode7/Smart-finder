// src/lib/groq/service.ts
// Groq AI Service — Centralized operations powered by Qwen 3.6 27B with strict JSON Object Mode
// (Concise, Reliable Schemas — Never falls back to unstructured text or emits <think> tags)

import { getGroqClient, hasGroqKey } from './client';
import { GROQ_MODEL, GROQ_OUTPUT_BUDGETS } from './config';
import { executeGroqRequest } from './request';
import { parseAndValidateJSON } from './json';
import { selectSourcesForAI } from '@/lib/sources/selection';
import { buildSourceContext, buildMultiSourceContext } from '@/lib/sources/context-builder';
import {
  AIInsightsSchema,
  OverallBriefingSchema,
  ComparisonResultSchema,
  KnowledgeGraphSchema,
  TimelineSchema,
  ResearchReportSchema,
  InsightActionResultSchema,
} from './schemas';
import type {
  Source,
  AIInsights,
  OverallBriefing,
  ComparisonResult,
  KnowledgeGraph,
  TimelineEvent,
  ResearchReport,
  InsightAction,
  ChatMessage,
} from '@/types/research';
import { isoNow } from '@/lib/utils/date';

function checkGroqAuth() {
  if (!hasGroqKey()) {
    throw new Error('Groq API key (GROQ_API_KEY) is not configured in .env.local.');
  }
}

const STRICT_JSON_SYSTEM_PROMPT =
  'You are a precise AI research assistant. You must return ONLY a single valid JSON object. No markdown formatting, no code fences, no conversational text, and NO <think> tags. The output must begin with "{" and end with "}".';

// ─── summarizeSource ─────────────────────────────────────────────────────────

export async function summarizeSource(source: Source): Promise<AIInsights> {
  checkGroqAuth();

  if (!source) {
    throw new Error('No valid source provided for summarization.');
  }

  const context = buildSourceContext(source, 2500);

  const result = await executeGroqRequest({
    operation: 'summary',
    systemPrompt: STRICT_JSON_SYSTEM_PROMPT,
    userPrompt: `Summarize this research source into a JSON object matching this schema:
{
  "summary": "1-2 concise paragraphs summarizing the source's core message and findings.",
  "keyPoints": [
    {
      "text": "Key point (1-2 sentences)",
      "citation": {"sourceId": "${source.id}", "text": "Direct phrase or topic"}
    }
  ],
  "entities": [
    {"name": "Entity name", "type": "person|organization|concept|technology"}
  ],
  "statistics": ["Specific statistic if present, or leave array empty [] if none"],
  "claims": ["Key assertion or hypothesis (1-2 sentences)"],
  "importance": "1-2 sentences on why this source is significant.",
  "generatedAt": "${isoNow()}"
}

Rules:
- Keep keyPoints to max 4 items (1-2 sentences each).
- Keep entities to max 5 items.
- Keep claims to max 3 items.
- If no statistics are mentioned in the source, return an empty array [] for statistics. Do not invent numbers.
- Return ONLY the JSON object. No other text.

Source:
${context}`,
  });

  const parsed = parseAndValidateJSON(result.content, AIInsightsSchema);
  return parsed.data;
}

// ─── generateInsights (Right-Click Actions) ───────────────────────────────────

export async function generateInsights(
  action: InsightAction,
  source: Source,
  options: { question?: string; compareWith?: Source } = {}
): Promise<{ result: string }> {
  checkGroqAuth();

  if (!source) {
    throw new Error('No valid source provided for insight generation.');
  }

  const context = buildSourceContext(source, 2000);

  const actionPrompts: Record<InsightAction, string> = {
    summarize: 'Provide a concise summary of this source (1-2 paragraphs).',
    explain: 'Explain this source clearly for a general audience (1-2 paragraphs).',
    extract_facts: 'Extract the key verifiable facts (3-5 bullet points).',
    extract_statistics: 'Extract any numerical data points or statistics mentioned. If none, state that no statistics are present.',
    find_claims: 'Identify the main assertions and arguments put forward (2-4 items).',
    find_people_orgs: 'Identify key individuals, institutions, and organizations mentioned.',
    find_contradictions: 'Identify any trade-offs, tensions, or conflicting points mentioned.',
    why_important: 'Explain in 1-2 concise paragraphs why this source is significant.',
    ask_question: `Answer this question based on the source (1-2 paragraphs): ${options.question || ''}`,
    compare: `Compare this source concisely with: ${options.compareWith ? buildSourceContext(options.compareWith, 1000) : 'other sources'}.`,
  };

  const result = await executeGroqRequest({
    operation: 'insights',
    systemPrompt: STRICT_JSON_SYSTEM_PROMPT,
    userPrompt: `${actionPrompts[action] || 'Analyze this source.'}

Return ONLY a JSON object in this format:
{"result": "Your concise response here (1-3 paragraphs maximum)."}

Source:
${context}`,
  });

  const parsed = parseAndValidateJSON(result.content, InsightActionResultSchema);
  return parsed.data;
}

// ─── chatWithSource (Streaming) ───────────────────────────────────────────────

export async function chatWithSource(
  source: Source,
  message: string,
  history: ChatMessage[]
): Promise<ReadableStream<Uint8Array>> {
  checkGroqAuth();

  if (!source) {
    throw new Error('No valid source provided for chat.');
  }

  const context = buildSourceContext(source, 2500);
  const groq = getGroqClient();

  const messages = [
    {
      role: 'system' as const,
      content: `You are an AI research assistant powered by Qwen on Groq. Answer questions directly and concisely about this source: "${source.title}" (${source.provider}). Ground answers in the provided context. No <think> tags.

Context:
${context}`,
    },
    ...history.slice(-6).map((m) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
    })),
    { role: 'user' as const, content: message },
  ];

  const stream = await (groq.chat.completions.create as any)({
    model: GROQ_MODEL,
    messages,
    stream: true,
    reasoning_format: 'hidden',
    reasoning_effort: 'none',
    max_tokens: GROQ_OUTPUT_BUDGETS.chat,
  });

  return new ReadableStream({
    async start(controller) {
      for await (const chunk of stream) {
        const content = chunk.choices[0]?.delta?.content || '';
        if (content) {
          controller.enqueue(new TextEncoder().encode(content));
        }
      }
      controller.close();
    },
  });
}

// ─── compareSources ───────────────────────────────────────────────────────────

export async function compareSources(
  sources: Source[],
  selectedSourceIds: string[] = []
): Promise<ComparisonResult> {
  checkGroqAuth();

  if (!sources || sources.length === 0) {
    throw new Error('No sources available to compare.');
  }

  const selection = selectSourcesForAI({
    sources,
    selectedSourceIds,
    operation: 'compare',
    maxSources: Math.max(8, selectedSourceIds.length || sources.length),
  });

  const activeSources = selection.selectedSources.length > 0 ? selection.selectedSources : sources.slice(0, 4);
  if (activeSources.length < 2) {
    throw new Error('At least 2 live sources are required to perform comparative analysis.');
  }

  const contexts = buildMultiSourceContext(activeSources, 16000);

  const result = await executeGroqRequest({
    operation: 'compare',
    maxTokens: 2500,
    systemPrompt: STRICT_JSON_SYSTEM_PROMPT,
    userPrompt: `Compare the provided research sources into a concise JSON object matching this schema:
{
  "sourceIds": [${activeSources.map((s) => `"${s.id}"`).join(', ')}],
  "similarities": [
    "Core area of consensus or common ground (1-2 sentences)"
  ],
  "differences": [
    "Key difference in perspective or methodology (1-2 sentences)"
  ],
  "conflictingClaims": [
    "Identified debate or conflicting argument (1-2 sentences)"
  ],
  "evidenceComparison": [
    "Assessment of evidence strength across sources (1-2 sentences)"
  ],
  "topicTable": [
    {
      "topic": "Key Subtopic Theme",
      ${activeSources.map((s) => `"${s.id}": "Stance of source (1 sentence)"`).join(',\n      ')}
    }
  ],
  "aiConclusion": "1-2 concise concluding sentences on the comparison.",
  "generatedAt": "${isoNow()}"
}

Rules:
- Max 4 similarities (1-2 sentences each).
- Max 4 differences (1-2 sentences each).
- Max 3 conflictingClaims (1-2 sentences each).
- Max 4 topicTable rows comparing the key dimensions across all included sources.
- Return ONLY the JSON object.

Sources:
${contexts}`,
  });

  const parsed = parseAndValidateJSON(result.content, ComparisonResultSchema);
  return parsed.data;
}

// ─── generateOverallBrief ─────────────────────────────────────────────────────

export async function generateOverallBrief(
  topic: string,
  sources: Source[],
  selectedSourceIds: string[] = []
): Promise<OverallBriefing> {
  checkGroqAuth();

  if (!sources || sources.length === 0) {
    throw new Error('No live sources available to synthesize executive briefing.');
  }

  const selection = selectSourcesForAI({
    sources,
    selectedSourceIds,
    topic,
    operation: 'brief',
    maxSources: 6,
  });

  const activeSources = selection.selectedSources.length > 0 ? selection.selectedSources : sources.slice(0, 5);
  const contexts = buildMultiSourceContext(activeSources, 10000);

  const result = await executeGroqRequest({
    operation: 'brief',
    maxTokens: 2200,
    systemPrompt: STRICT_JSON_SYSTEM_PROMPT,
    userPrompt: `Topic: ${topic}

Synthesize the provided sources into a structured, concise JSON research briefing matching this exact schema:
{
  "executiveSummary": "1-2 concise paragraphs summarizing the research topic and key insights based on the sources.",
  "mainFindings": [
    "Key finding 1 (1-2 sentences)",
    "Key finding 2 (1-2 sentences)",
    "Key finding 3 (1-2 sentences)"
  ],
  "importantFacts": [
    "Fact 1 (1-2 sentences)",
    "Fact 2 (1-2 sentences)",
    "Fact 3 (1-2 sentences)"
  ],
  "keyArguments": [
    "Core argument 1 (1-2 sentences)",
    "Core argument 2 (1-2 sentences)"
  ],
  "agreements": [
    "Point of consensus 1 (1-2 sentences)",
    "Point of consensus 2 (1-2 sentences)"
  ],
  "contradictions": [
    "Point of debate or tension 1 (1-2 sentences)",
    "Point of debate or tension 2 (1-2 sentences)"
  ],
  "differentViewpoints": [
    "Policy / Governmental viewpoint (1-2 sentences)",
    "Academic / Technical viewpoint (1-2 sentences)"
  ],
  "openQuestions": [
    "Unresolved challenge or question 1 (1-2 sentences)",
    "Unresolved challenge or question 2 (1-2 sentences)"
  ],
  "importantStatistics": [
    "Statistic or metric from the sources, or leave array empty [] if none exist"
  ],
  "conclusion": "1-2 concise sentences summarizing the takeaway.",
  "generatedAt": "${isoNow()}"
}

Strict Rules:
- mainFindings: max 3 items (1-3 sentences each).
- importantFacts: max 4 items (1-2 sentences each).
- keyArguments: max 3 items (1-2 sentences each).
- agreements: max 3 items (1-2 sentences each).
- contradictions: max 3 items (1-2 sentences each).
- differentViewpoints: max 3 items (1-2 sentences each).
- openQuestions: max 3 items (1-2 sentences each).
- importantStatistics: max 4 items. If the sources do not mention explicit statistics, return an empty array []. Do NOT fabricate statistics.
- conclusion: 1-2 sentences.
- Return ONLY the JSON object. No markdown, no commentary, no <think> tags.

Sources:
${contexts}`,
  });

  const parsed = parseAndValidateJSON(result.content, OverallBriefingSchema);
  return parsed.data;
}

// ─── extractEntities (Knowledge Graph) ────────────────────────────────────────

export async function extractEntities(
  topic: string,
  sources: Source[],
  selectedSourceIds: string[] = []
): Promise<KnowledgeGraph> {
  checkGroqAuth();

  if (!sources || sources.length === 0) {
    return { nodes: [], edges: [] };
  }

  const selection = selectSourcesForAI({
    sources,
    selectedSourceIds,
    topic,
    operation: 'entities',
    maxSources: 5,
  });

  const activeSources = selection.selectedSources.length > 0 ? selection.selectedSources : sources.slice(0, 4);
  const contexts = buildMultiSourceContext(activeSources, 6000);

  const result = await executeGroqRequest({
    operation: 'entities',
    maxTokens: 1200,
    systemPrompt: STRICT_JSON_SYSTEM_PROMPT,
    userPrompt: `Extract key entities and relationships for "${topic}" into a JSON object:
{
  "nodes": [
    {"id": "n1", "label": "Entity Name", "type": "topic|person|organization|source|concept", "sourceIds": ["${activeSources[0]?.id || 's1'}"]}
  ],
  "edges": [
    {"source": "n1", "target": "n2", "label": "relationship", "strength": 0.8}
  ]
}

Rules:
- Max 8 nodes total.
- Max 8 edges total.
- Use actual entity names mentioned in the sources.
- Return ONLY the JSON object.

Sources:
${contexts}`,
  });

  const parsed = parseAndValidateJSON(result.content, KnowledgeGraphSchema);
  return parsed.data;
}

// ─── generateTimeline ─────────────────────────────────────────────────────────

export async function generateTimeline(
  topic: string,
  sources: Source[],
  selectedSourceIds: string[] = []
): Promise<TimelineEvent[]> {
  checkGroqAuth();

  if (!sources || sources.length === 0) {
    return [];
  }

  const selection = selectSourcesForAI({
    sources,
    selectedSourceIds,
    topic,
    operation: 'timeline',
    maxSources: 8,
  });

  const activeSources = selection.selectedSources.length > 0 ? selection.selectedSources : sources.slice(0, 6);
  const contexts = buildMultiSourceContext(activeSources, 12000);

  const result = await executeGroqRequest({
    operation: 'timeline',
    maxTokens: 3000,
    systemPrompt: STRICT_JSON_SYSTEM_PROMPT,
    userPrompt: `Extract all chronological milestones, historical events, policy announcements, edition rollouts, and future targets for "${topic}" into a JSON object:
{
  "events": [
    {
      "id": "e1",
      "date": "YYYY, YYYY-MM, or YYYY-MM-DD",
      "title": "Clear Milestone Title",
      "description": "1-2 concise sentences describing what occurred and its significance.",
      "sourceIds": ["${activeSources[0]?.id || 's1'}"],
      "importance": "high"
    }
  ]
}

Strict Rules:
- Capture ALL important milestones, dates, and developments mentioned across the sources. Do NOT artificially cap the timeline.
- Sort all events chronologically from earliest to newest.
- Keep each description concise (1-2 sentences).
- Use real dates or years mentioned in the text.
- Return ONLY the JSON object.

Sources:
${contexts}`,
  });

  const parsed = parseAndValidateJSON(result.content, TimelineSchema);
  return parsed.data.events;
}

// ─── generateResearchReport ───────────────────────────────────────────────────

export async function generateResearchReport(
  topic: string,
  sources: Source[],
  selectedSourceIds: string[] = []
): Promise<ResearchReport> {
  checkGroqAuth();

  if (!sources || sources.length === 0) {
    throw new Error('No live sources available to compile research report.');
  }

  const selection = selectSourcesForAI({
    sources,
    selectedSourceIds,
    topic,
    operation: 'report',
    maxSources: 6,
  });

  const activeSources = selection.selectedSources.length > 0 ? selection.selectedSources : sources.slice(0, 5);
  const contexts = buildMultiSourceContext(activeSources, 10000);

  const result = await executeGroqRequest({
    operation: 'report',
    maxTokens: 3000,
    systemPrompt: STRICT_JSON_SYSTEM_PROMPT,
    userPrompt: `Generate a structured research report for "${topic}" into a JSON object:
{
  "topic": "${topic}",
  "executiveSummary": "1-2 concise paragraphs summarizing the research report.",
  "background": "1-2 concise paragraphs providing context.",
  "keyFindings": [
    "Finding 1 (1-2 sentences)",
    "Finding 2 (1-2 sentences)",
    "Finding 3 (1-2 sentences)"
  ],
  "evidence": [
    {
      "claim": "Claim 1 (1 sentence)",
      "sources": [{"sourceId": "${activeSources[0]?.id || 's1'}", "text": "Evidence excerpt"}]
    }
  ],
  "perspectives": [
    {
      "viewpoint": "Perspective 1 (1-2 sentences)",
      "sources": ["${activeSources[0]?.id || 's1'}"]
    }
  ],
  "contradictions": [
    "Contradiction or tension 1 (1-2 sentences)"
  ],
  "statistics": [
    "Statistic from sources, or leave array empty [] if none"
  ],
  "conclusion": "1-2 concise concluding sentences.",
  "generatedAt": "${isoNow()}"
}

Rules:
- Max 4 keyFindings (1-2 sentences each).
- Max 3 evidence items.
- Max 3 perspectives.
- Max 2 contradictions.
- If no statistics are mentioned in the sources, return an empty array [].
- Return ONLY the JSON object.

Sources:
${contexts}`,
  });

  const parsed = parseAndValidateJSON(result.content, ResearchReportSchema);

  return {
    ...parsed.data,
    sources: activeSources,
  };
}
