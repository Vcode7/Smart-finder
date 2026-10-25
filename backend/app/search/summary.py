"""
app/search/summary.py
~~~~~~~~~~~~~~~~~~~~~
The background job behind the Summary tab.

For the top results of a search (a session's files within 5% of the best score):

1. Each file gets its own summary. A summary stored by an earlier search is reused (it is
   tied to the file's fingerprint, so a changed file is summarised again). Otherwise the
   LLM reads what the index already holds for the file, a few thousand characters at most,
   and answers with a summary, topics and events, which are stored for next time.
2. The per-file summaries are combined into one overall summary. When they do not fit the
   input budget they are combined in groups first, then the group summaries are combined.

Limits and failures are handled here, not in the caller:
- Every prompt is sized to the input budget; the router caps Groq output at 850 tokens, and
  the output asked for is well under that.
- Real token usage is read from the response when it has one, otherwise estimated.
- Rate limits are retried with backoff (the key manager rotates keys but never waits).
- A file the LLM cannot summarise gets an extractive summary (its first sentences) and the
  job carries on; one failure never fails the job.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.ai.groq_client import estimate_tokens, get_async_groq_client, is_groq_rate_limit_error, robust_json_loads
from app.ai.prompts import (
    DOC_SUMMARY_SYSTEM_PROMPT, DOC_SUMMARY_TEMPLATE,
    OVERALL_SUMMARY_SYSTEM_PROMPT, OVERALL_SUMMARY_TEMPLATE,
)
from app.core.config import settings
from app.library.manager import get_library_manager
from app.search import insights
from app.search.session import SummaryJob

# The answers are short (about 150 tokens), but a local reasoning model spends its budget thinking
# first; Groq caps output at 850 tokens in the router, so ask for the most that is honoured.
DOC_MAX_TOKENS = 700
OVERALL_MAX_TOKENS = 800
CALL_TIMEOUT = 40.0
RETRIES = 2                  # extra attempts after a rate limit
MAX_WAIT = 20.0              # longest pause before a retry, seconds
CHARS_PER_TOKEN = 4          # the same rough ratio estimate_tokens() uses

_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def _strip_think(text: str) -> str:
    return _THINK.sub("", text or "").strip()


_DECODER = json.JSONDecoder()


def extract_json(raw: str, key: str) -> Dict[str, Any]:
    """
    The JSON object holding `key` in a model answer, or {}. Models sometimes think out loud, wrap
    the answer in code fences or return a list; the answer is the last object that has the key.
    """
    data = robust_json_loads(raw, default={})
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), {})
    if isinstance(data, dict) and key in data:
        return data
    found: Dict[str, Any] = {}
    text = raw or ""
    for m in re.finditer(r"\{", text):
        try:
            obj, _end = _DECODER.raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and key in obj:
            found = obj
    return found


def _retry_after(e: Exception) -> Optional[float]:
    headers = getattr(getattr(e, "response", None), "headers", None) or {}
    try:
        return float(headers.get("retry-after")) if headers.get("retry-after") else None
    except (TypeError, ValueError):
        return None


def _usage_of(completion: Any, prompt: str, answer: str) -> Tuple[int, int]:
    usage = getattr(completion, "usage", None)
    pt = getattr(usage, "prompt_tokens", None) if usage is not None else None
    ct = getattr(usage, "completion_tokens", None) if usage is not None else None
    return int(pt if pt is not None else estimate_tokens(prompt)), int(ct if ct is not None else estimate_tokens(answer))


async def _complete(job: SummaryJob, system: str, user: str, max_tokens: int) -> str:
    """One chat completion with rate-limit backoff; counts the call and its tokens on the job."""
    client = get_async_groq_client()
    delay = 2.0
    for attempt in range(RETRIES + 1):
        if job.cancelled:
            raise asyncio.CancelledError()
        try:
            completion = await client.chat.completions.create(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens, temperature=0.2, stream=False, timeout=CALL_TIMEOUT)
            answer = _strip_think(completion.choices[0].message.content or "")
            pt, ct = _usage_of(completion, system + user, answer)
            job.usage["calls"] += 1
            job.usage["promptTokens"] += pt
            job.usage["completionTokens"] += ct
            return answer
        except asyncio.CancelledError:
            raise
        except Exception as e:
            limited, _reason = is_groq_rate_limit_error(e)
            if limited and attempt < RETRIES:
                await asyncio.sleep(min(_retry_after(e) or delay, MAX_WAIT))
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def _warn(job: SummaryJob, message: str) -> None:
    if message not in job.warnings:
        job.warnings.append(message)


def _why(e: Exception) -> str:
    if isinstance(e, ValueError) and "API_KEY" in str(e):
        return "no AI service is set up (add a Groq key or choose an Ollama model in Settings)"
    if isinstance(e, ValueError):         # the model answered, but not with a summary
        return "the AI did not return a usable answer"
    limited, reason = is_groq_rate_limit_error(e)
    return "the AI service is rate limited" if limited else f"the AI service failed ({type(e).__name__})"


async def _summarise_doc(job: SummaryJob, entry: Dict[str, Any], row: Dict[str, Any], query: str,
                         gate: asyncio.Semaphore) -> None:
    async with gate:
        if job.cancelled:
            return
        lib = get_library_manager().get(row.get("libraryId") or "")
        sid = row["sourceId"]
        snippet = row.get("snippet") or ""

        cached = await asyncio.to_thread(insights.cached_llm_summary, lib, sid) if lib is not None else None
        if cached:
            entry.update(summary=cached["summary"], topics=cached["topics"], events=cached["events"],
                         source="cache", state="done")
            job.usage["cachedDocs"] += 1
            job.done += 1
            return

        max_chars = settings.SUMMARY_DOC_INPUT_TOKENS * CHARS_PER_TOKEN
        context = await asyncio.to_thread(insights.build_doc_context, lib, sid, snippet, max_chars) \
            if lib is not None else snippet[:max_chars]
        if not context.strip():
            context = f"{row.get('title', '')} ({row.get('relPath', '')})"

        try:
            prompt = DOC_SUMMARY_TEMPLATE.format(
                query=query, title=row.get("title", ""), kind=row.get("category", ""),
                ext=row.get("fileType", ""), folder=row.get("folder") or "(top level)", context=context)
            raw = await _complete(job, DOC_SUMMARY_SYSTEM_PROMPT, prompt, DOC_MAX_TOKENS)
            data = extract_json(raw, "summary")
            summary = str(data.get("summary") or "").strip()
            if len(summary) < 12 or summary.startswith("<"):      # empty, "...", or the template echoed back
                raise ValueError("the answer had no summary")
            topics = [str(t) for t in (data.get("topics") or []) if t][:5]
            events = [str(t) for t in (data.get("events") or []) if t][:2]
            if lib is not None:
                if not topics or not events:      # the model named none: keep the ones derived from the index
                    base = await asyncio.to_thread(insights.get_insights, lib, sid)
                    topics, events = topics or base["topics"], events or base["events"]
                await asyncio.to_thread(insights.save_llm_insights, lib, sid, summary, topics, events,
                                        settings.GROQ_MODEL)
            entry.update(summary=summary, topics=topics, events=events, source="llm", state="done")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _warn(job, f"Some files were summarised from their text only because {_why(e)}.")
            entry.update(summary=insights.extractive_summary(context), source="extractive", state="done",
                         error=str(e)[:160])
        finally:
            if entry.get("state") == "done":
                job.done += 1


def _numbered(docs: List[Dict[str, Any]], start: int = 1) -> str:
    lines = []
    for i, d in enumerate(docs, start):
        topics = f" (topics: {', '.join(d['topics'])})" if d.get("topics") else ""
        lines.append(f"[{i}] {d['title']}{topics}: {d['summary']}")
    return "\n".join(lines)


def _groups(docs: List[Dict[str, Any]], budget_tokens: int) -> List[List[Dict[str, Any]]]:
    """Consecutive runs of per-file summaries that each fit the input budget."""
    groups: List[List[Dict[str, Any]]] = [[]]
    used = 0
    for d in docs:
        cost = estimate_tokens(_numbered([d]))
        if groups[-1] and used + cost > budget_tokens:
            groups.append([])
            used = 0
        groups[-1].append(d)
        used += cost
    return groups


async def _write_overall(job: SummaryJob, docs: List[Dict[str, Any]], query: str, first: int = 1) -> str:
    raw = await _complete(job, OVERALL_SUMMARY_SYSTEM_PROMPT, OVERALL_SUMMARY_TEMPLATE.format(
        query=query, count=len(docs), summaries=_numbered(docs, first)), OVERALL_MAX_TOKENS)
    text = str(extract_json(raw, "overview").get("overview") or "").strip()
    if len(text) < 20 or text.startswith("<"):
        raise ValueError("the answer had no overview")
    return text


async def _overall(job: SummaryJob, docs: List[Dict[str, Any]], query: str) -> str:
    budget = settings.SUMMARY_OVERALL_INPUT_TOKENS
    groups = _groups(docs, budget)
    if len(groups) == 1:
        return await _write_overall(job, docs, query)
    # Too much for one call: summarise each group, then combine the group summaries
    partial: List[Dict[str, Any]] = []
    first = 1
    for g in groups:
        text = await _write_overall(job, g, query, first)
        partial.append({"title": f"Items {first}-{first + len(g) - 1}", "summary": text, "topics": []})
        first += len(g)
    return await _write_overall(job, partial, query)


async def run_summary_job(job: SummaryJob, rows: List[Dict[str, Any]], query: str) -> None:
    """Fills `job` in place; the Summary tab polls it. Never raises."""
    try:
        job.status = "running"
        job.total = len(rows)
        job.docs.extend({
            "id": r.get("id"), "sourceId": r["sourceId"], "libraryId": r.get("libraryId"),
            "title": r.get("title"), "category": r.get("category"), "fileType": r.get("fileType"),
            "relevanceScore": r.get("relevanceScore"), "folder": r.get("folder"), "relPath": r.get("relPath"),
            "libraryName": r.get("libraryName"), "state": "pending", "summary": None, "topics": [],
            "events": [], "source": None,
        } for r in rows)
        gate = asyncio.Semaphore(max(1, settings.SUMMARY_CONCURRENCY))
        await asyncio.gather(*(_summarise_doc(job, e, r, query, gate) for e, r in zip(job.docs, rows)))
        if job.cancelled:
            job.status = "cancelled"
            return

        done = [d for d in job.docs if d.get("summary")]
        llm_docs = [d for d in done if d["source"] in ("llm", "cache")]
        if len(done) == 1:
            job.overall, job.overall_source = done[0]["summary"], done[0]["source"]
        elif llm_docs:
            try:
                job.overall = await _overall(job, done, query)
                job.overall_source = "llm"
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _warn(job, f"The overall summary could not be written because {_why(e)}; the file summaries are shown.")
        job.status = "done"
    except asyncio.CancelledError:
        job.status = "cancelled"
    except Exception as e:      # a bug must not leave the tab spinning
        job.status = "error"
        job.error = f"{type(e).__name__}: {e}"[:300]
        print(f"[Summary] job {job.id} failed: {job.error}", flush=True)
