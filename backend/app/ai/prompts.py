STRICT_JSON_SYSTEM_PROMPT = (
    "You are a precise AI research assistant. You must return ONLY a single valid JSON object. "
    "No markdown formatting, no code fences, no conversational text, and NO <think> tags. "
    'The output must begin with "{" and end with "}".'
)

SUMMARY_TEMPLATE = """Summarize this research source into a JSON object matching this schema:
{{
  "summary": "1-2 concise paragraphs summarizing the source's core message and findings.",
  "keyPoints": [
    {{
      "text": "Key point (1-2 sentences)",
      "citation": {{"sourceId": "{source_id}", "text": "Direct phrase or topic"}}
    }}
  ],
  "entities": [
    {{"name": "Entity name", "type": "person|organization|concept|technology"}}
  ],
  "statistics": ["Specific statistic if present, or leave array empty [] if none"],
  "claims": ["Key assertion or hypothesis (1-2 sentences)"],
  "importance": "1-2 sentences on why this source is significant.",
  "generatedAt": "{iso_now}"
}}

Rules:
- Keep keyPoints to max 4 items (1-2 sentences each).
- Keep entities to max 5 items.
- Keep claims to max 3 items.
- If no statistics are mentioned in the source, return an empty array [] for statistics. Do not invent numbers.
- Return ONLY the JSON object. No other text.

Source:
{context}"""

INSIGHTS_ACTION_PROMPTS = {
    "summarize": "Provide a concise summary of this source (1-2 paragraphs).",
    "explain": "Explain this source clearly for a general audience (1-2 paragraphs).",
    "extract_facts": "Extract the key verifiable facts (3-5 bullet points).",
    "extract_statistics": "Extract any numerical data points or statistics mentioned. If none, state that no statistics are present.",
    "find_claims": "Identify the main assertions and arguments put forward (2-4 items).",
    "find_people_orgs": "Identify key individuals, institutions, and organizations mentioned.",
    "find_contradictions": "Identify any trade-offs, tensions, or conflicting points mentioned.",
    "why_important": "Explain in 1-2 concise paragraphs why this source is significant.",
    "ask_question": "Answer this question based on the source (1-2 paragraphs): {question}",
    "compare": "Compare this source concisely with: {compare_with}.",
}

COMPARE_TEMPLATE = """Compare the provided research sources into a concise JSON object matching this schema:
{{
  "sourceIds": {source_ids_json},
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
    {{
      "topic": "Key Subtopic Theme",
      "stance": "Comparison across sources"
    }}
  ],
  "aiConclusion": "1-2 concise concluding sentences on the comparison.",
  "generatedAt": "{iso_now}"
}}

Rules:
- Max 4 similarities (1-2 sentences each).
- Max 4 differences (1-2 sentences each).
- Max 3 conflictingClaims (1-2 sentences each).
- Max 4 topicTable rows comparing the key dimensions across all included sources.
- Return ONLY the JSON object.

Sources:
{contexts}"""

BRIEF_TEMPLATE = """Topic: {topic}

Synthesize the provided sources into a structured, concise JSON research briefing matching this exact schema:
{{
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
  "generatedAt": "{iso_now}"
}}

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
{contexts}"""

ENTITIES_TEMPLATE = """Extract key entities and relationships for "{topic}" into a JSON object:
{{
  "nodes": [
    {{"id": "n1", "label": "Entity Name", "type": "topic|person|organization|source|concept", "sourceIds": ["{first_source_id}"]}}
  ],
  "edges": [
    {{"source": "n1", "target": "n2", "label": "relationship", "strength": 0.8}}
  ]
}}

Rules:
- Max 8 nodes total.
- Max 8 edges total.
- Use actual entity names mentioned in the sources.
- Return ONLY the JSON object.

Sources:
{contexts}"""

TIMELINE_TEMPLATE = """Extract all chronological milestones, historical events, policy announcements, edition rollouts, and future targets for "{topic}" into a JSON object:
{{
  "events": [
    {{
      "id": "e1",
      "date": "YYYY, YYYY-MM, or YYYY-MM-DD",
      "title": "Clear Milestone Title",
      "description": "1-2 concise sentences describing what occurred and its significance.",
      "sourceIds": ["{first_source_id}"],
      "importance": "high"
    }}
  ]
}}

Strict Rules:
- Capture ALL important milestones, dates, and developments mentioned across the sources. Do NOT artificially cap the timeline.
- Sort all events chronologically from earliest to newest.
- Keep each description concise (1-2 sentences).
- Use real dates or years mentioned in the text.
- Return ONLY the JSON object.

Sources:
{contexts}"""

REPORT_TEMPLATE = """Generate a structured research report for "{topic}" into a JSON object:
{{
  "topic": "{topic}",
  "executiveSummary": "1-2 concise paragraphs summarizing the research report.",
  "background": "1-2 concise paragraphs providing context.",
  "keyFindings": [
    "Finding 1 (1-2 sentences)",
    "Finding 2 (1-2 sentences)",
    "Finding 3 (1-2 sentences)"
  ],
  "evidence": [
    {{
      "claim": "Claim 1 (1 sentence)",
      "sources": [{{"sourceId": "{first_source_id}", "text": "Evidence excerpt"}}]
    }}
  ],
  "perspectives": [
    {{
      "viewpoint": "Perspective 1 (1-2 sentences)",
      "sources": ["{first_source_id}"]
    }}
  ],
  "contradictions": [
    "Contradiction or tension 1 (1-2 sentences)"
  ],
  "statistics": [
    "Statistic from sources, or leave array empty [] if none"
  ],
  "conclusion": "1-2 concise concluding sentences.",
  "generatedAt": "{iso_now}"
}}

Rules:
- Max 4 keyFindings (1-2 sentences each).
- Max 3 evidence items.
- Max 3 perspectives.
- Max 2 contradictions.
- If no statistics are mentioned in the sources, return an empty array [].
- Return ONLY the JSON object.

Sources:
{contexts}"""


# ── Search summary tab: one summary per file, then one over all of them ──────────────
DOC_SUMMARY_SYSTEM_PROMPT = (
    "You summarise files for a search results page. Use only the text you are given; never invent facts. "
    "Return ONLY one valid JSON object, no markdown, no code fences, no <think> tags."
)

DOC_SUMMARY_TEMPLATE = """The user searched for: "{query}"

File: {title} ({kind}, {ext})
Folder: {folder}

Return a JSON object with this shape:
{{"summary": "<what the file is and says>", "topics": ["<subject>", "<subject>"], "events": ["<event name>"]}}

Rules:
- summary: plain text, at most 90 words. Say what the file is and what it says. Write in the language of the file's text.
- topics: up to 5 short noun phrases naming the specific subjects, people, places or organisations (no generic words like "document" or "information").
- events: up to 2 specific events or occasions named in the text, or [] if there are none.

File text:
{context}"""

OVERALL_SUMMARY_SYSTEM_PROMPT = (
    "You combine per-file summaries into one clear overview for a person searching their own files. "
    "Use only the summaries you are given; never invent facts. "
    "Return ONLY one valid JSON object, no code fences, no <think> tags."
)

OVERALL_SUMMARY_TEMPLATE = """The user searched for: "{query}"

Below are summaries of the {count} most relevant items, numbered.

Return a JSON object {{"overview": "<the overall summary>"}} whose value is the overall summary written in Markdown (use \\n for line breaks), at most 220 words:
1. Two or three sentences answering what these files show about the search.
2. Three to five bullet points with the main findings, themes, people, places or events.
3. One short line starting "Differences:" only if the items disagree or cover clearly separate topics.
Cite items like [1] or [2][3]. Do not add a title.

{summaries}"""
