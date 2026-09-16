import datetime
import json
from typing import Any, Dict, List, Optional, AsyncGenerator
from app.core.config import settings
from app.ai.groq_client import get_groq_client, execute_groq_request
from app.ai.prompts import (
    STRICT_JSON_SYSTEM_PROMPT,
    SUMMARY_TEMPLATE,
    INSIGHTS_ACTION_PROMPTS,
    COMPARE_TEMPLATE,
    BRIEF_TEMPLATE,
    ENTITIES_TEMPLATE,
    TIMELINE_TEMPLATE,
    REPORT_TEMPLATE,
)

def iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def build_source_context(source: Dict[str, Any], max_chars: int = 3500) -> str:
    if not source:
        return ""
    parts = []
    stype = str(source.get("type", "source")).upper()
    title = str(source.get("title", "Untitled Source"))
    provider = f" | {source['provider']}" if source.get("provider") else ""
    date = f" | {str(source['date'])[:10]}" if source.get("date") else ""
    parts.append(f"[{stype}] \"{title}\"{provider}{date}")

    if source.get("author"):
        parts.append(f"Author(s): {source['author']}")

    source_type = str(source.get("type", "")).lower()
    if source_type == "video":
        if source.get("duration"):
            parts.append(f"Duration: {source['duration']}")
        if source.get("transcript"):
            parts.append(f"Transcript:\n{str(source['transcript'])[:max_chars]}")
        elif source.get("description"):
            parts.append(f"Key Video Notes:\n{str(source['description'])[:max_chars]}")
    elif source_type == "paper":
        if source.get("journal"):
            parts.append(f"Publication/Venue: {source['journal']}")
        if source.get("citationCount") is not None:
            parts.append(f"Citations: {source['citationCount']}")
        if source.get("abstract"):
            parts.append(f"Abstract:\n{str(source['abstract'])[:max_chars]}")
        elif source.get("description"):
            parts.append(f"Summary:\n{str(source['description'])[:max_chars]}")
    elif source_type == "report":
        if source.get("description"):
            parts.append(f"Report Executive Summary & Directives:\n{str(source['description'])[:max_chars]}")
    else:
        if source.get("description"):
            parts.append(f"Content Excerpt:\n{str(source['description'])[:max_chars]}")

    full_text = "\n".join(parts)
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "... [content truncated]"
    return full_text

def build_multi_source_context(sources: List[Dict[str, Any]], max_total_chars: int = 32000) -> str:
    if not sources:
        return ""
    per_source_limit = max(1000, max_total_chars // max(1, len(sources)))
    rendered = []
    for idx, s in enumerate(sources):
        ctxt = build_source_context(s, per_source_limit)
        rendered.append(f"--- SOURCE {idx + 1} (ID: {s.get('id', idx)}) ---\n{ctxt}")
    return "\n\n".join(rendered)

async def summarize_source(source: Dict[str, Any]) -> Dict[str, Any]:
    context = build_source_context(source, 2500)
    prompt = SUMMARY_TEMPLATE.format(
        source_id=source.get("id", "source-1"),
        iso_now=iso_now(),
        context=context
    )
    return execute_groq_request(
        system_prompt=STRICT_JSON_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=1000,
        operation="summary"
    )

async def generate_insights(
    action: str,
    source: Dict[str, Any],
    question: Optional[str] = None,
    compare_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    context = build_source_context(source, 2000)
    compare_str = build_source_context(compare_with, 1000) if compare_with else "other sources"
    action_prompt_tmpl = INSIGHTS_ACTION_PROMPTS.get(action, "Analyze this source.")
    action_prompt = action_prompt_tmpl.format(question=question or "", compare_with=compare_str)

    user_prompt = f"""{action_prompt}

Return ONLY a JSON object in this format:
{{"result": "Your concise response here (1-3 paragraphs maximum)."}}

Source:
{context}"""

    return execute_groq_request(
        system_prompt=STRICT_JSON_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=800,
        operation="insights"
    )

async def chat_with_source(
    source: Dict[str, Any],
    message: str,
    history: List[Dict[str, Any]]
) -> AsyncGenerator[str, None]:
    context = build_source_context(source, 2500)
    client = get_groq_client()

    messages = [
        {
            "role": "system",
            "content": f"You are an AI research assistant powered by Qwen on Groq. Answer questions directly and concisely about this source: \"{source.get('title', '')}\" ({source.get('provider', '')}). Ground answers in the provided context. No <think> tags.\n\nContext:\n{context}"
        }
    ]

    for m in history[-6:]:
        messages.append({
            "role": m.get("role", "user"),
            "content": m.get("content", "")
        })

    messages.append({"role": "user", "content": message})

    stream = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=messages,
        stream=True,
        max_tokens=1000,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            yield delta

async def compare_sources(
    sources: List[Dict[str, Any]],
    selected_source_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    active = sources[:6] if len(sources) > 6 else sources
    contexts = build_multi_source_context(active, 16000)
    source_ids = [s.get("id", f"s{i}") for i, s in enumerate(active)]
    prompt = COMPARE_TEMPLATE.format(
        source_ids_json=json.dumps(source_ids),
        iso_now=iso_now(),
        contexts=contexts
    )
    res = execute_groq_request(
        system_prompt=STRICT_JSON_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=2500,
        operation="compare"
    )
    if "sourceIds" not in res:
        res["sourceIds"] = source_ids
    return res

async def generate_overall_brief(
    topic: str,
    sources: List[Dict[str, Any]],
    selected_source_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    active = sources[:5] if len(sources) > 5 else sources
    contexts = build_multi_source_context(active, 10000)
    prompt = BRIEF_TEMPLATE.format(
        topic=topic,
        iso_now=iso_now(),
        contexts=contexts
    )
    return execute_groq_request(
        system_prompt=STRICT_JSON_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=2200,
        operation="brief"
    )

async def extract_entities(
    topic: str,
    sources: List[Dict[str, Any]],
    selected_source_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    active = sources[:4] if len(sources) > 4 else sources
    contexts = build_multi_source_context(active, 6000)
    first_id = active[0].get("id", "s1") if active else "s1"
    prompt = ENTITIES_TEMPLATE.format(
        topic=topic,
        first_source_id=first_id,
        contexts=contexts
    )
    res = execute_groq_request(
        system_prompt=STRICT_JSON_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=1200,
        operation="entities"
    )
    if "nodes" not in res:
        res["nodes"] = []
    if "edges" not in res:
        res["edges"] = []
    return res

async def generate_timeline(
    topic: str,
    sources: List[Dict[str, Any]],
    selected_source_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    active = sources[:6] if len(sources) > 6 else sources
    contexts = build_multi_source_context(active, 12000)
    first_id = active[0].get("id", "s1") if active else "s1"
    prompt = TIMELINE_TEMPLATE.format(
        topic=topic,
        first_source_id=first_id,
        contexts=contexts
    )
    res = execute_groq_request(
        system_prompt=STRICT_JSON_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=3000,
        operation="timeline"
    )
    return res.get("events", [])

async def generate_research_report(
    topic: str,
    sources: List[Dict[str, Any]],
    selected_source_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    active = sources[:5] if len(sources) > 5 else sources
    contexts = build_multi_source_context(active, 10000)
    first_id = active[0].get("id", "s1") if active else "s1"
    prompt = REPORT_TEMPLATE.format(
        topic=topic,
        first_source_id=first_id,
        iso_now=iso_now(),
        contexts=contexts
    )
    res = execute_groq_request(
        system_prompt=STRICT_JSON_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=3000,
        operation="report"
    )
    res["sources"] = active
    return res
