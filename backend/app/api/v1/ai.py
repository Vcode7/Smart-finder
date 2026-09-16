from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.ai import (
    SummarizeRequest, InsightsRequest, CompareRequest, BriefRequest,
    EntitiesRequest, TimelineRequest, ReportRequest, ChatActionRequest, ChatRequest
)
from app.ai.groq_service import (
    summarize_source, generate_insights, chat_with_source,
    compare_sources, generate_overall_brief, extract_entities,
    generate_timeline, generate_research_report
)

router = APIRouter(tags=["ai"])

@router.post("/summarize")
async def summarize(req: SummarizeRequest):
    if not req.source:
        raise HTTPException(status_code=400, detail="Source is required")
    insights = await summarize_source(req.source)
    return {"insights": insights}

@router.post("/insights")
async def insights(req: InsightsRequest):
    if not req.source:
        raise HTTPException(status_code=400, detail="Source is required")
    result = await generate_insights(
        action=req.action,
        source=req.source,
        question=req.question,
        compare_with=req.compareWith
    )
    return {"result": result.get("result", "")}

@router.post("/chat")
async def chat(req: ChatRequest):
    if not req.source or not req.message.strip():
        raise HTTPException(status_code=400, detail="Source and message are required")

    async def stream_generator():
        async for chunk in chat_with_source(req.source, req.message, req.history or []):
            yield chunk

    return StreamingResponse(stream_generator(), media_type="text/plain; charset=utf-8")

@router.post("/compare")
async def compare(req: CompareRequest):
    sources = req.sources or req.contextItems or []
    if len(sources) < 2:
        raise HTTPException(status_code=400, detail="At least 2 sources required for comparison")
    res = await compare_sources(sources, req.selectedSourceIds)
    return res

@router.post("/brief")
async def brief(req: BriefRequest):
    if not req.topic.strip():
        raise HTTPException(status_code=400, detail="Topic is required")
    if not req.sources:
        raise HTTPException(status_code=400, detail="At least 1 source is required")
    res = await generate_overall_brief(req.topic, req.sources, req.selectedSourceIds)
    return res

@router.post("/entities")
async def entities(req: EntitiesRequest):
    sources = req.sources or req.contextItems or []
    if not sources:
        raise HTTPException(status_code=400, detail="At least 1 source is required")
    res = await extract_entities(req.topic or "Research Graph", sources, req.selectedSourceIds)
    return res

@router.post("/timeline")
async def timeline(req: TimelineRequest):
    sources = req.sources or req.contextItems or []
    if not sources:
        raise HTTPException(status_code=400, detail="At least 1 source is required")
    events = await generate_timeline(req.topic or "Timeline Analysis", sources, req.selectedSourceIds)
    return {"events": events}

@router.post("/report")
async def report(req: ReportRequest):
    sources = req.sources or req.contextItems or []
    if not sources:
        raise HTTPException(status_code=400, detail="At least 1 source is required")
    res = await generate_research_report(req.topic or "Research Report", sources, req.selectedSourceIds)
    return res

@router.post("/chat/actions")
async def chat_actions(req: ChatActionRequest):
    sources = req.sources or req.contextItems or []
    if not sources:
        raise HTTPException(status_code=400, detail="At least 1 source or context item is required")

    action = req.action.lower()
    topic = req.topic or "Research Context"

    if action in ("timeline", "events"):
        events = await generate_timeline(topic, sources)
        return {"action": action, "events": events}
    elif action in ("graph", "connections"):
        data = await extract_entities(topic, sources)
        return {"action": action, **data}
    elif action == "compare":
        data = await compare_sources(sources)
        return {"action": action, **data}
    elif action == "report":
        data = await generate_research_report(topic, sources)
        return {"action": action, **data}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown chat action: {action}")
