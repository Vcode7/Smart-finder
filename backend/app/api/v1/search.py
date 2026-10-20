import re
import io
import json
import uuid
import base64
import asyncio
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.database.session import db_get, db_all
from app.api.deps import require_auth
from app.schemas.search import (
    SearchRequest, LocalSearchRequest, VideoSearchRequest,
    FetchMoreRequest, SynthesizeRequest
)
from app.search.providers.youtube import search_videos
from app.search.providers.academic import search_papers
from app.search.providers.news import search_news, search_articles_only, search_reports_only
from app.search.providers.web import search_web
from app.search.providers.images import search_internet_images
from app.search.keyword_search import search_transcripts, extract_query_tokens
from app.search.context_expander import expand_transcript_segment
from app.search.face_detector import detect_faces_in_image, search_face_embeddings
from app.search.query_understanding import understand_multimodal_query, generate_enhanced_internet_query, detect_file_category
from app.search.multimodal_retrieval import search_by_multimodal_signals, search_by_text
from app.search.constants import COMPOSITE_MIN_SCORE, IMAGE_EXTENSIONS
from app.search.engine import fts_terms, get_engine, plan_from_source
from app.search.plan import QueryPlan, build_plan

router = APIRouter(prefix="/search", tags=["search"])

_BUCKETS = ("documents", "videos", "images", "audio")


# ── local search: folder libraries (engine) + the legacy index until it is migrated ──
def _legacy_exists() -> bool:
    """Sources still only in the old index (rows copied into a library are in legacy_migrated)."""
    try:
        return db_get("SELECT 1 AS x FROM knowledge_sources "
                      "WHERE id NOT IN (SELECT source_id FROM legacy_migrated) LIMIT 1") is not None
    except Exception:
        return False


async def _legacy_results(query_text: str, file_buffer: Optional[bytes], file_name: Optional[str],
                          mime_type: Optional[str], limit: int) -> Dict[str, List[Dict[str, Any]]]:
    if not await run_in_threadpool(_legacy_exists):
        return {k: [] for k in _BUCKETS}
    try:
        if not file_buffer:
            return await run_in_threadpool(search_by_text, query_text, limit)
        signals = await understand_multimodal_query({
            "textQuery": query_text, "fileBuffer": file_buffer, "fileName": file_name, "mimeType": mime_type,
            "fileCategory": detect_file_category(file_name, mime_type), "previewUrl": None,
        }, use_llm=False)
        return await run_in_threadpool(search_by_multimodal_signals, signals)
    except Exception as e:
        print(f"[Search] Legacy index search notice: {e}")
        return {k: [] for k in _BUCKETS}


def _merge_buckets(primary: Dict[str, List[Dict[str, Any]]], legacy: Dict[str, List[Dict[str, Any]]],
                   limit: int) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for k in _BUCKETS:
        seen = {i.get("sourceId") for i in primary.get(k, [])}
        items = list(primary.get(k, [])) + [i for i in legacy.get(k, []) if i.get("sourceId") not in seen]
        out[k] = sorted(items, key=lambda x: x.get("relevanceScore", 0.0), reverse=True)[:limit]
    return out


async def _local_search(query_text: str, file_buffer: Optional[bytes] = None, file_name: Optional[str] = None,
                        mime_type: Optional[str] = None, limit: int = 20) -> Tuple[Dict[str, List[Dict[str, Any]]], QueryPlan, Dict[str, Any]]:
    files = [(file_buffer, file_name, mime_type)] if file_buffer else []
    plan = await run_in_threadpool(build_plan, query_text, files)
    engine_res = await run_in_threadpool(get_engine().search, plan, limit)
    legacy = await _legacy_results(query_text, file_buffer, file_name, mime_type, limit)
    return _merge_buckets(engine_res.as_dict(), legacy, limit), plan, engine_res.trace


def _compat_signals(plan: QueryPlan) -> Dict[str, Any]:
    """The shape the internet-query enhancer expects from the old query understanding."""
    anchor = plan.text or plan.rerank_query
    return {
        "queryType": plan.kind,
        "textQuery": plan.text,
        "originalQueryText": plan.text or None,
        "derivedSearchKeywords": " ".join(fts_terms(anchor)[:8]),
        "ocrText": plan.trace.get("ocr"),
        "speechTranscript": plan.trace.get("speech"),
        "documentText": plan.trace.get("document"),
        "extractedEntities": [],
        "hasFace": plan.has_faces,
        "faces": [f for img in plan.images for f in img.faces],
    }


def _decode_base64_image(data: str) -> bytes:
    clean_b64 = re.sub(r"^data:image\/[\w.+-]+;base64,", "", data or "")
    try:
        return base64.b64decode(clean_b64, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="imageBase64 is not valid base64 image data")


def _preview_data_url(file_buffer: Optional[bytes], mime_type: Optional[str]) -> Optional[str]:
    """Small JPEG preview of an uploaded query image (the full image is never echoed back)."""
    if not file_buffer or not (mime_type or "").startswith("image/"):
        return None
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(file_buffer)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((512, 512))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=80)
        return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception:
        return None


async def _read_query_request(request: Request) -> Dict[str, Any]:
    """Parse a search request sent either as multipart (with one file) or as JSON."""
    content_type = request.headers.get("content-type") or ""
    out: Dict[str, Any] = {"query": "", "file_buffer": None, "file_name": None, "mime_type": None, "fields": {}}

    if "multipart/form-data" in content_type:
        form = await request.form()
        out["fields"] = {k: v for k, v in form.items() if isinstance(v, str)}
        out["query"] = str(form.get("query") or "")
        target_file = form.get("file") or form.get("image")
        if target_file and hasattr(target_file, "filename") and target_file.filename:
            out["file_name"] = target_file.filename
            out["mime_type"] = target_file.content_type
            out["file_buffer"] = await target_file.read()
    else:
        try:
            body = await request.json()
        except Exception:
            try:
                raw_bytes = await request.body()
                body = json.loads(raw_bytes.decode("utf-8", errors="ignore")) if raw_bytes else {}
            except Exception:
                body = {}
        if not isinstance(body, dict):
            body = {}
        out["fields"] = body
        out["query"] = str(body.get("query") or "")
        out["file_name"] = body.get("fileName")
        out["mime_type"] = body.get("mimeType")
        if body.get("imageBase64"):
            out["file_buffer"] = _decode_base64_image(body["imageBase64"])
            out["mime_type"] = out["mime_type"] or "image/jpeg"
    return out


def _relative_threshold(raw: Any, default: float = 0.20) -> float:
    if raw is None:
        return default
    try:
        val = float(raw)
        if val > 1.0:
            val = val / 100.0
        return max(0.0, min(1.0, val))
    except (ValueError, TypeError):
        return default


def _cutoff(items: List[Dict[str, Any]], relative_threshold: float, fallback: float) -> float:
    top = max((i.get("relevanceScore", 0.0) for i in items), default=0.0)
    if top <= 0:
        return fallback
    return max(COMPOSITE_MIN_SCORE, round(top - relative_threshold, 4))


@router.post("")
async def unified_search(req: SearchRequest, user: Dict[str, Any] = Depends(require_auth)):
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")

    source = req.source or "internet"

    internet_results: Dict[str, Any] = {
        "videos": [], "papers": [], "articles": [], "reports": [], "web": [], "providerStatuses": {}
    }

    local_task = _local_search(topic, limit=10) if source in ("local", "both") else None

    if source in ("internet", "both"):
        v_res, p_res, n_res, w_res = await asyncio.gather(
            search_videos(topic), search_papers(topic), search_news(topic), search_web(topic),
            return_exceptions=True
        )

        v_data = v_res if isinstance(v_res, dict) else {"status": "error", "sources": [], "count": 0}
        p_data = p_res if isinstance(p_res, dict) else {"status": "error", "sources": [], "count": 0}
        n_data = n_res if isinstance(n_res, dict) else {"articles": [], "reports": [], "articleResult": {}, "reportResult": {}}
        w_data = w_res if isinstance(w_res, dict) else {"status": "error", "sources": [], "count": 0}

        internet_results = {
            "videos": v_data.get("sources", []),
            "papers": p_data.get("sources", []),
            "articles": n_data.get("articles", []),
            "reports": n_data.get("reports", []),
            "web": w_data.get("sources", []),
            "providerStatuses": {
                "video": {"provider": v_data.get("provider", "YouTube"), "category": "video", "status": v_data.get("status", "success"), "count": v_data.get("count", 0)},
                "paper": {"provider": p_data.get("provider", "Academic"), "category": "paper", "status": p_data.get("status", "success"), "count": p_data.get("count", 0)},
                "article": n_data.get("articleResult", {}),
                "reports": n_data.get("reportResult", {}),
                "web": {"provider": w_data.get("provider", "Web"), "category": "web", "status": w_data.get("status", "success"), "count": w_data.get("count", 0)},
            }
        }

    text_res = (await local_task)[0] if local_task is not None else {}
    return {
        "source": source,
        **internet_results,
        "localDocuments": text_res.get("documents", []),
        "localVideos": text_res.get("videos", []),
        "localImages": text_res.get("images", []),
        "localAudio": text_res.get("audio", []),
    }


@router.post("/local")
async def local_search(req: LocalSearchRequest, user: Dict[str, Any] = Depends(require_auth)):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    limit = req.limit or 10
    res, _plan, _trace = await _local_search(query, limit=limit)
    documents = res.get("documents", [])[:limit]
    videos = res.get("videos", [])[:limit]
    images = res.get("images", [])[:limit]
    audio = res.get("audio", [])[:limit]
    return {
        "query": query,
        "documents": documents,
        "videos": videos,
        "images": images,
        "audio": audio,
        "total": len(documents) + len(videos) + len(images) + len(audio),
    }


def _document_snippet(file_buffer: bytes, file_name: Optional[str]) -> Optional[str]:
    ext = (file_name.split(".")[-1].lower()) if (file_name and "." in file_name) else "txt"
    if ext == "pdf":
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_buffer))
        return "\n".join(p.extract_text() or "" for p in reader.pages[:3]).strip()[:1500]
    if ext == "docx":
        import docx
        doc = docx.Document(io.BytesIO(file_buffer))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()[:1500]
    return file_buffer.decode("utf-8", errors="ignore").strip()[:1500]


@router.post("/extract-query")
async def extract_search_query(request: Request, user: Dict[str, Any] = Depends(require_auth)):
    """
    Extract a clean search query, keywords, and relevant search terms from user chat inquiry
    plus optional uploaded image, audio or document file using LLM.
    """
    parsed_req = await _read_query_request(request)
    query_text = parsed_req["query"]
    file_buffer: Optional[bytes] = parsed_req["file_buffer"]
    file_name: Optional[str] = parsed_req["file_name"]
    mime_type: Optional[str] = parsed_req["mime_type"]
    file_snippet: Optional[str] = None

    if file_buffer:
        cat = detect_file_category(file_name, mime_type)
        if cat == "document":
            try:
                file_snippet = await run_in_threadpool(_document_snippet, file_buffer, file_name)
            except Exception as e:
                print(f"[ExtractQuery] Document extract notice: {e}")
            if not file_snippet:
                file_snippet = f"User attached document: {file_name or 'Uploaded Document'}"
        elif cat == "image":
            try:
                face_res = await detect_faces_in_image(file_buffer, {"sourceId": "query"})
                ocr_text = face_res.get("ocrText") or ""
                visual_desc = face_res.get("visualDescription") or ""
                names = ", ".join(face_res.get("identifiedNames", []))
                faces = face_res.get("faces", [])
                parts = []
                if names: parts.append(f"Identified entities: {names}")
                if visual_desc: parts.append(f"Visual description: {visual_desc[:300]}")
                if ocr_text: parts.append(f"OCR text: {ocr_text[:300]}")
                if faces: parts.append(f"Detected {len(faces)} face(s)")
                if not parts:
                    parts.append(f"User attached image: {file_name or 'Uploaded Image'}")
                file_snippet = " | ".join(parts)
            except Exception as e:
                print(f"[ExtractQuery] Image extract notice: {e}")
                file_snippet = f"User attached image: {file_name or 'Uploaded Image'}"
        elif cat in ("audio", "video"):
            try:
                signals = await understand_multimodal_query({
                    "fileBuffer": file_buffer, "fileName": file_name,
                    "mimeType": mime_type, "fileCategory": cat,
                }, use_llm=False)
                transcript = (signals.get("speechTranscript") or "").strip()
                file_snippet = f"Speech transcript: {transcript[:1200]}" if transcript else f"User attached {cat}: {file_name or 'recording'}"
            except Exception as e:
                print(f"[ExtractQuery] Audio extract notice: {e}")

    # Fallback values if LLM unavailable
    fallback_query = query_text.strip() or (Path(file_name).stem if file_name else "Research Documents")
    words = [w for w in re.split(r"[\s,;]+", fallback_query) if len(w) >= 3]
    fallback_keywords = words[:5] if words else [fallback_query]
    fallback_terms = [fallback_query]
    fallback_intent = "Document and knowledge source retrieval"

    if settings.get_groq_api_keys():
        try:
            from app.ai.groq_client import get_async_groq_client, robust_json_loads
            client = get_async_groq_client()

            prompt_content = f"User Inquiry: \"{query_text}\""
            if file_name:
                prompt_content += f"\nReference File Name: {file_name}"
            if file_snippet:
                prompt_content += f"\nExtracted Content Snippet:\n\"\"\"{file_snippet[:1200]}\"\"\""

            prompt_content += (
                "\n\nGenerate a JSON response with:\n"
                "1. \"searchQuery\": A clean, concise, high-precision search query (1 to 8 words) optimized for semantic document and knowledge retrieval.\n"
                "2. \"keywords\": A list of 3 to 6 core domain keywords and entity names.\n"
                "3. \"searchTerms\": A list of 3 to 5 relevant search terms, synonyms, or alternative phrases.\n"
                "4. \"intent\": A single sentence summarizing what information the user is searching for.\n\n"
                "Return ONLY valid JSON matching this schema."
            )

            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an elite search query formulation specialist. Your role is to convert complex user prompts and reference file contents into clean, precise search queries, keywords, and terms for document retrieval. Return ONLY a valid JSON object."
                        },
                        {"role": "user", "content": prompt_content}
                    ],
                    max_tokens=300,
                    temperature=0.2,
                    timeout=3.5,
                ),
                timeout=4.0
            )

            content = resp.choices[0].message.content or "{}"
            parsed = robust_json_loads(content, default={})

            extracted_query = str(parsed.get("searchQuery") or "").strip() or fallback_query
            extracted_keywords = parsed.get("keywords") if isinstance(parsed.get("keywords"), list) else fallback_keywords
            extracted_terms = parsed.get("searchTerms") if isinstance(parsed.get("searchTerms"), list) else fallback_terms
            extracted_intent = str(parsed.get("intent") or "").strip() or fallback_intent

            return {
                "searchQuery": extracted_query,
                "keywords": [str(k) for k in extracted_keywords if str(k).strip()][:6],
                "searchTerms": [str(t) for t in extracted_terms if str(t).strip()][:6],
                "intent": extracted_intent,
                "fileSnippet": file_snippet[:1500] if file_snippet else None,
                "originalQuery": query_text,
            }
        except Exception as e:
            print(f"[ExtractQuery] LLM extraction error: {e}")

    return {
        "searchQuery": fallback_query,
        "keywords": fallback_keywords,
        "searchTerms": fallback_terms,
        "intent": fallback_intent,
        "fileSnippet": file_snippet[:1500] if file_snippet else None,
        "originalQuery": query_text,
    }


def _web_domain(url: str, default: str) -> str:
    try:
        domain = urllib.parse.urlparse(url or "").hostname or default
    except Exception:
        domain = default
    return re.sub(r"^www\.", "", domain)


async def _internet_sources(query: str) -> Dict[str, List[Dict[str, Any]]]:
    try:
        w_res, n_res, p_res, v_res, i_res = await asyncio.wait_for(
            asyncio.gather(
                search_web(query), search_news(query), search_papers(query),
                search_videos(query), search_internet_images(query, 8),
                return_exceptions=True
            ),
            timeout=12.0
        )
    except asyncio.TimeoutError:
        print("[SmartSearch] Internet search providers timed out after 12s, proceeding with available data")
        w_res = n_res = p_res = v_res = i_res = None

    web, news, papers, videos, images = [], [], [], [], []
    if isinstance(w_res, dict):
        for it in w_res.get("sources", [])[:8]:
            web.append({
                "id": it.get("id") or f"web-{uuid.uuid4()}", "category": "web", "title": it.get("title", ""), "url": it.get("url", ""),
                "snippet": it.get("description", ""), "domain": _web_domain(it.get("url", ""), "web"), "publishedDate": it.get("date"),
                "thumbnail": it.get("thumbnail"), "relevanceScore": 0.92,
            })
    if isinstance(n_res, dict):
        for it in n_res.get("articles", [])[:6]:
            news.append({
                "id": it.get("id") or f"news-{uuid.uuid4()}", "category": "news", "title": it.get("title", ""), "url": it.get("url", ""),
                "snippet": it.get("description", ""), "domain": _web_domain(it.get("url", ""), "news"), "publishedDate": it.get("date"),
                "author": it.get("author"), "relevanceScore": 0.89,
            })
    if isinstance(p_res, dict):
        for it in p_res.get("sources", [])[:6]:
            papers.append({
                "id": it.get("id") or f"paper-{uuid.uuid4()}", "category": "paper", "title": it.get("title", ""),
                "url": it.get("url") or f"https://semanticscholar.org/search?q={urllib.parse.quote(it.get('title', ''))}",
                "snippet": it.get("description", ""), "domain": "semanticscholar.org",
                "publishedDate": it.get("date"), "author": it.get("author"), "relevanceScore": 0.90,
            })
    if isinstance(v_res, dict):
        for it in v_res.get("sources", [])[:6]:
            vid_id = (it.get("id") or "").replace("yt-", "")
            videos.append({
                "id": it.get("id") or f"yt-{uuid.uuid4()}", "category": "video", "title": it.get("title", ""),
                "url": it.get("url") or f"https://youtube.com/watch?v={vid_id}",
                "snippet": it.get("description", ""), "domain": "youtube.com",
                "publishedDate": it.get("date"), "author": it.get("author"),
                "thumbnail": it.get("thumbnail"), "relevanceScore": 0.90,
            })
    if isinstance(i_res, list):
        for it in i_res[:8]:
            if not isinstance(it, dict):
                continue
            images.append({
                "id": it.get("id") or f"img-{uuid.uuid4()}", "category": "image", "title": it.get("title", ""),
                "url": it.get("sourceUrl") or it.get("url", ""), "snippet": f"Image from {it.get('domain', 'web')}",
                "domain": it.get("domain", "web"), "thumbnail": it.get("thumbnail") or it.get("url", ""),
                "relevanceScore": 0.88,
            })
    return {"web": web, "news": news, "papers": papers, "videos": videos, "images": images}


@router.post("/smart")
async def smart_search(request: Request, user: Dict[str, Any] = Depends(require_auth)):
    req = await _read_query_request(request)
    fields = req["fields"]
    query_text = req["query"]
    file_buffer = req["file_buffer"]
    file_name = req["file_name"]
    mime_type = req["mime_type"]
    enable_internet = str(fields.get("enableInternet") or fields.get("enableInternetSources") or "").lower() == "true" \
        or fields.get("enableInternet") is True or fields.get("enableInternetSources") is True
    relative_threshold = _relative_threshold(fields.get("relativeThreshold"))

    if not query_text.strip() and not file_buffer:
        raise HTTPException(status_code=400, detail="Please provide a search query or upload reference material.")

    preview_url = _preview_data_url(file_buffer, mime_type)

    # 1. Local search: every folder library (plus the legacy index until it is migrated)
    local_res, plan, engine_trace = await _local_search(query_text, file_buffer, file_name, mime_type, limit=20)
    signals = _compat_signals(plan)
    all_local_matches = sorted(
        [*local_res.get("videos", []), *local_res.get("documents", []),
         *local_res.get("images", []), *local_res.get("audio", [])],
        key=lambda x: x.get("relevanceScore", 0), reverse=True
    )

    # 2. Internet search (optional). The typed text stays the anchor; LLM enrichment from
    #    local context is only used for image/document uploads without text.
    enhanced: Dict[str, Any] = {}
    target_internet_query = query_text.strip()
    internet = {"web": [], "news": [], "papers": [], "videos": [], "images": []}
    if enable_internet:
        enhanced = await generate_enhanced_internet_query(signals, all_local_matches)
        if not target_internet_query:
            target_internet_query = enhanced.get("primaryQuery") or "AI Research Intelligence"
        internet = await _internet_sources(target_internet_query)

    # 3. Per-modality relative thresholds, so strong document scores can't wipe out
    #    visual or audio matches (and vice versa).
    top_local_score = max((m.get("relevanceScore", 0.0) for m in all_local_matches), default=0.0)
    min_score = max(COMPOSITE_MIN_SCORE, round(top_local_score - relative_threshold, 4))
    is_visual_search = bool(plan.images) and not plan.text
    has_user_text = bool(plan.text)

    doc_min = _cutoff(local_res.get("documents", []), relative_threshold, min_score)
    video_min = _cutoff(local_res.get("videos", []), relative_threshold, min_score)
    image_min = _cutoff(local_res.get("images", []), relative_threshold, min_score)
    audio_min = _cutoff(local_res.get("audio", []), relative_threshold, min_score)
    if is_visual_search and not has_user_text:
        # Pure visual search: documents must be genuinely relevant to show up
        doc_min = max(0.50, doc_min)

    filtered_documents = [d for d in local_res.get("documents", []) if d.get("relevanceScore", 0.0) >= doc_min]
    filtered_videos = [v for v in local_res.get("videos", []) if v.get("relevanceScore", 0.0) >= video_min]
    filtered_images = [i for i in local_res.get("images", []) if i.get("relevanceScore", 0.0) >= image_min]
    filtered_audio = [a for a in local_res.get("audio", []) if a.get("relevanceScore", 0.0) >= audio_min]
    all_local_matches = sorted(
        [*filtered_videos, *filtered_documents, *filtered_images, *filtered_audio],
        key=lambda x: x.get("relevanceScore", 0.0), reverse=True
    )
    local_total = len(all_local_matches)
    internet_total = sum(len(v) for v in internet.values())
    total_before = len(local_res.get("documents", [])) + len(local_res.get("videos", [])) + \
        len(local_res.get("images", [])) + len(local_res.get("audio", [])) + internet_total

    print(f"[SmartSearch Threshold] top_local_score={top_local_score:.4f}, configured_threshold={relative_threshold:.4f}, "
          f"min_score={min_score:.4f}, results_before={total_before}, results_after={local_total + internet_total}")

    top = all_local_matches[0] if all_local_matches else None
    discovery_trace = {
        "inputType": plan.kind,
        "inputName": file_name,
        "inputPreview": preview_url,
        "extractedSignals": {
            "hasFace": plan.has_faces,
            "faceCount": len(signals.get("faces", [])),
            "ocrSnippet": signals.get("ocrText")[:160] if signals.get("ocrText") else None,
            "speechSnippet": signals.get("speechTranscript")[:160] if signals.get("speechTranscript") else None,
            "visualDescription": None,
            "extractedEntities": [],
            "filters": plan.filters.describe(),
        },
        "engine": {k: engine_trace.get(k) for k in ("libraries", "candidates", "reranked", "faceFilter", "returned",
                                                   "folders", "folderQuery")},
        "topLocalMatch": {
            "id": top.get("id"),
            "sourceId": top.get("sourceId"),
            "title": top.get("title") or top.get("originalName") or "Untitled Document",
            "category": top.get("category", "document"),
            "relevanceScore": top.get("relevanceScore", 0.0),
            "timestamp": top.get("startTime"),
            "isFaceMatch": top.get("isFaceMatch"),
            "faceSimilarity": top.get("faceSimilarity"),
            "snippet": top.get("snippet"),
        } if top else None,
        "enhancedQuery": target_internet_query or query_text,
        "queryVariants": enhanced.get("queryVariants"),
        "discoveredEntities": enhanced.get("discoveredEntities"),
        "contextSummary": enhanced.get("contextSummary"),
        "lineage": enhanced.get("lineage"),
    }

    return {
        "query": query_text or target_internet_query,
        "queryImagePreview": preview_url,
        "discoveryTrace": discovery_trace,
        "thresholdInfo": {
            "topScore": round(top_local_score, 4),
            "relativeThreshold": round(relative_threshold, 4),
            "minScore": round(min_score, 4),
            "resultsBefore": total_before,
            "resultsAfter": local_total + internet_total,
        },
        "internet": {**internet, "total": internet_total},
        "local": {
            "documents": filtered_documents,
            "videos": filtered_videos,
            "audio": filtered_audio,
            "images": filtered_images,
            "total": local_total,
        },
        "stats": {
            "internetCount": internet_total,
            "localCount": local_total,
            "total": internet_total + local_total,
        },
    }


def _similar_signals(source: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build retrieval signals describing an indexed source (blocking)."""
    from collections import Counter
    from app.search.model_pipeline import get_image_embedding, get_text_query_embedding

    source_id = source["id"]
    title = source["original_name"]
    file_type = (source.get("file_type") or "").lower()

    chunks = db_all(
        """SELECT c.chunk_text, s.section_title, c.page_num
           FROM document_chunks c
           LEFT JOIN document_sections s ON c.section_id = s.id
           WHERE c.source_id = ?
           ORDER BY c.chunk_order ASC LIMIT 10""",
        (source_id,)
    )
    chunk_texts = [c["chunk_text"] for c in chunks if c.get("chunk_text")]
    section_titles = list({
        c["section_title"] for c in chunks
        if c.get("section_title") and not c["section_title"].startswith("Page ")
    })
    if not section_titles:
        secs = db_all("SELECT section_title FROM document_sections WHERE source_id = ? LIMIT 10", (source_id,))
        section_titles = list({s["section_title"] for s in secs if s.get("section_title") and not s["section_title"].startswith("Page ")})
    doc_summary = " ".join(chunk_texts)[:1000] if chunk_texts else ""

    transcripts = db_all(
        "SELECT text, start_time FROM video_transcripts WHERE source_id = ? ORDER BY start_time ASC LIMIT 12",
        (source_id,)
    )
    video_summary = " ".join(t["text"] for t in transcripts if t.get("text"))[:1000]

    keywords: List[str] = []
    if source.get("tags_json"):
        try:
            kws = json.loads(source["tags_json"])
            if isinstance(kws, list):
                keywords.extend(kws)
        except Exception:
            pass
    keywords.extend(section_titles)

    img_row = db_get(
        "SELECT image_path, phash, dhash FROM image_perceptual_hashes WHERE source_id = ? LIMIT 1",
        (source_id,)
    )
    phash = img_row.get("phash") if img_row else None
    dhash = img_row.get("dhash") if img_row else None
    img_path = img_row.get("image_path") if img_row else (
        source["file_path"] if file_type in IMAGE_EXTENSIONS else None
    )
    img_emb = get_image_embedding(img_path) if img_path and Path(img_path).exists() else None

    text_content = doc_summary or video_summary
    tokens = extract_query_tokens(f"{title} {text_content}")
    top_tokens = [w for w, _ in Counter(tokens).most_common(8)]
    combined_keywords = list(dict.fromkeys(keywords + top_tokens))
    query_preview = f"{title} {' '.join(combined_keywords[:6])}".strip()
    text_emb = get_text_query_embedding(f"{title} {text_content}"[:1200]) if text_content else None

    signals = {
        "queryType": "similar_source",
        "textQuery": query_preview,
        "originalQueryText": title,
        "textEmbedding": text_emb,
        "documentText": doc_summary or None,
        "derivedSearchKeywords": " ".join(combined_keywords[:8]),
        "speechTranscript": video_summary[:500] if video_summary else None,
        "fileName": title,
        "phash": phash,
        "dhash": dhash,
        "imageEmbedding": img_emb,
    }
    info = {
        "title": title,
        "file_type": file_type,
        "keywords": combined_keywords[:8],
        "query_preview": query_preview,
        "text_content": text_content,
        "has_visual": bool(phash or img_emb is not None),
    }
    return signals, info


async def _similar_in_libraries(lib, src: Dict[str, Any], relative_threshold: float) -> Dict[str, Any]:
    plan = await run_in_threadpool(plan_from_source, lib, src["id"])
    res = await run_in_threadpool(get_engine().search, plan, 20)
    buckets = res.as_dict()
    all_matches = res.all()
    top_score = max((m["relevanceScore"] for m in all_matches), default=0.0)
    min_score = max(0.0, round(top_score - relative_threshold, 4))
    final = {k: [i for i in v if i["relevanceScore"] >= min_score] for k, v in buckets.items()}
    final_matches = [m for m in all_matches if m["relevanceScore"] >= min_score]
    total = len(final_matches)
    title = src["name"]
    return {
        "query": f"Similar to: {title}",
        "sourceId": src["id"],
        "sourceTitle": title,
        "discoveryTrace": {
            "inputType": "similar_source",
            "inputName": title,
            "extractedSignals": {
                "sourceTitle": title,
                "sourceType": src["ext"],
                "keywords": fts_terms(plan.rerank_query)[:8],
                "hasVisualSignal": bool(plan.images),
                "summarySnippet": (plan.rerank_query[:200] + "...") if plan.rerank_query else None,
            },
            "topLocalMatch": final_matches[0] if final_matches else None,
            "enhancedQuery": title,
        },
        "thresholdInfo": {
            "topScore": round(top_score, 4),
            "relativeThreshold": round(relative_threshold, 4),
            "minScore": round(min_score, 4),
            "resultsBefore": len(all_matches),
            "resultsAfter": total,
        },
        "local": {**final, "total": total},
        "internet": {"web": [], "news": [], "papers": [], "videos": [], "images": [], "total": 0},
        "stats": {"internetCount": 0, "localCount": total, "total": total},
    }


@router.post("/similar")
async def find_similar_sources(request: Request, user: Dict[str, Any] = Depends(require_auth)):
    req = await _read_query_request(request)
    fields = req["fields"]
    raw_id = str(fields.get("sourceId") or fields.get("source_id") or "").strip()
    relative_threshold = _relative_threshold(fields.get("relativeThreshold"))
    if not raw_id:
        raise HTTPException(status_code=400, detail="sourceId is required to find similar sources")

    source_id = raw_id.removeprefix("src-")
    from app.library.manager import get_library_manager
    found = await run_in_threadpool(get_library_manager().find_source, source_id)
    if found:
        return await _similar_in_libraries(found[0], found[1], relative_threshold)
    source = db_get(
        "SELECT id, original_name, file_type, file_path, file_size, upload_date, tags_json, metadata_json FROM knowledge_sources WHERE id = ?",
        (source_id,)
    )
    if not source:
        raise HTTPException(status_code=404, detail=f"Source with id '{raw_id}' not found")

    signals, info = await run_in_threadpool(_similar_signals, source)
    raw_res = await run_in_threadpool(search_by_multimodal_signals, signals)

    def not_self(item: Dict[str, Any]) -> bool:
        return item.get("sourceId") != source_id

    filtered = {k: [i for i in raw_res.get(k, []) if not_self(i)] for k in ("documents", "videos", "images", "audio")}
    all_matches = sorted(
        [*filtered["videos"], *filtered["documents"], *filtered["images"], *filtered["audio"]],
        key=lambda x: x.get("relevanceScore", 0.0), reverse=True
    )

    top_score = max((m.get("relevanceScore", 0.0) for m in all_matches), default=0.0)
    min_score = max(0.0, round(top_score - relative_threshold, 4))
    final = {k: [i for i in v if i.get("relevanceScore", 0.0) >= min_score] for k, v in filtered.items()}
    final_matches = [m for m in all_matches if m.get("relevanceScore", 0.0) >= min_score]
    total_related = len(final_matches)

    print(f"[Find Similar Sources] '{info['title']}' (id: {source_id}) -> {total_related} related "
          f"(top_score={top_score:.4f}, min_score={min_score:.4f})")

    return {
        "query": f"Similar to: {info['title']}",
        "sourceId": source_id,
        "sourceTitle": info["title"],
        "discoveryTrace": {
            "inputType": "similar_source",
            "inputName": info["title"],
            "extractedSignals": {
                "sourceTitle": info["title"],
                "sourceType": info["file_type"],
                "keywords": info["keywords"],
                "hasVisualSignal": info["has_visual"],
                "summarySnippet": (info["text_content"][:200] + "...") if info["text_content"] else None,
            },
            "topLocalMatch": final_matches[0] if final_matches else None,
            "enhancedQuery": info["query_preview"],
        },
        "thresholdInfo": {
            "topScore": round(top_score, 4),
            "relativeThreshold": round(relative_threshold, 4),
            "minScore": round(min_score, 4),
            "resultsBefore": len(all_matches),
            "resultsAfter": total_related,
        },
        "local": {
            "documents": final["documents"],
            "videos": final["videos"],
            "audio": final["audio"],
            "images": final["images"],
            "total": total_related,
        },
        "internet": {
            "web": [], "news": [], "papers": [], "videos": [], "images": [], "total": 0,
        },
        "stats": {
            "internetCount": 0,
            "localCount": total_related,
            "total": total_related,
        },
    }


@router.post("/multimodal")
async def multimodal_search(request: Request, user: Dict[str, Any] = Depends(require_auth)):
    req = await _read_query_request(request)
    query_text = req["query"]
    file_buffer = req["file_buffer"]
    if not query_text.strip() and not file_buffer:
        raise HTTPException(status_code=400, detail="Please provide a text query or upload reference material.")

    res, _plan, _trace = await _local_search(query_text, file_buffer, req["file_name"], req["mime_type"], limit=20)
    return res


@router.post("/face")
async def face_search(request: Request, user: Dict[str, Any] = Depends(require_auth)):
    content_type = request.headers.get("content-type") or ""
    query_embeddings: List[List[float]] = []
    buf: Optional[bytes] = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        target_file = form.get("file") or form.get("image")
        if target_file and hasattr(target_file, "filename") and target_file.filename:
            buf = await target_file.read()
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Expected an image upload or a JSON body")
        if body.get("embedding") and isinstance(body["embedding"], list):
            query_embeddings = [body["embedding"]]
        elif body.get("imageBase64"):
            buf = _decode_base64_image(body["imageBase64"])

    matches: List[Dict[str, Any]] = []
    if buf:
        # Folder libraries: identity vectors from buffalo_l
        def _face_only() -> List[Dict[str, Any]]:
            from app.search.plan import _image_signal, finish_plan
            sig = _image_signal(buf, "face query")
            if sig is None or not sig.faces:
                return []
            sig.clip_vec, sig.phash, sig.ocr_text = None, None, ""
            plan = QueryPlan(images=[sig])
            finish_plan(plan)
            out = []
            for item in get_engine().search(plan, 20).all():
                frame = item.get("primaryFrame") or (item.get("matchingFrames") or [None])[0]
                out.append({
                    "sourceId": item["sourceId"], "title": item["title"], "category": item["category"],
                    "similarity": item.get("faceSimilarity") or 0.0, "isMatch": item.get("isFaceMatch"),
                    "timestamp": item.get("startTime"), "frameId": frame.get("id") if frame else None,
                    "framePath": frame.get("framePath") if frame else None,
                    "libraryName": item.get("libraryName"), "relevanceScore": item["relevanceScore"],
                })
            return out
        matches.extend(await run_in_threadpool(_face_only))
        # Legacy index (buffalo_s vectors) until it is migrated
        if await run_in_threadpool(_legacy_exists):
            face_res = await detect_faces_in_image(buf, {"sourceId": "query", "useVision": False})
            query_embeddings = [f["embedding"] for f in face_res.get("faces", []) if f.get("embedding")]

    for emb in query_embeddings:
        matches.extend(await run_in_threadpool(search_face_embeddings, emb, 0.50, 10))

    seen = set()
    unique_matches = []
    for m in sorted(matches, key=lambda x: x.get("similarity", 0), reverse=True):
        key = f"{m.get('sourceId')}-{m.get('videoId')}-{m.get('timestamp')}"
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)

    return {"matches": unique_matches[:10], "total": len(unique_matches)}


@router.post("/video")
async def video_search(req: VideoSearchRequest, user: Dict[str, Any] = Depends(require_auth)):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")
    limit = req.limit or 10

    def _search() -> List[Dict[str, Any]]:
        video_results = []
        # Folder libraries: transcripts and frames through the search engine
        plan = build_plan(query + " kind:video")
        for item in get_engine().search(plan, limit).videos:
            video_results.append({
                "id": item["id"], "videoId": item["sourceId"], "sourceId": item["sourceId"],
                "videoTitle": item["title"], "startTime": item.get("startTime") or 0,
                "endTime": item.get("endTime") or 0, "duration": item.get("duration"),
                "transcript": item["snippet"], "snippet": item["snippet"],
                "relevanceScore": item["relevanceScore"], "uploadDate": item.get("uploadDate"),
                "matchingFrames": item.get("matchingFrames") or [], "libraryName": item.get("libraryName"),
            })
        if not _legacy_exists() or len(video_results) >= limit:
            return video_results[:limit]
        raw_results = search_transcripts(query, limit * 2)
        seen_videos = set()
        for tr in raw_results:
            expanded = expand_transcript_segment(tr["id"], tr["score"])
            if not expanded:
                continue
            video_key = f"{expanded['videoId']}-{int((expanded.get('startTime') or 0) // 30)}"
            if video_key in seen_videos:
                continue
            seen_videos.add(video_key)

            source = db_get(
                "SELECT id, original_name, file_type, upload_date, duration_seconds FROM knowledge_sources WHERE id = ?",
                (expanded["sourceId"],)
            )
            frames = db_all(
                """SELECT id, frame_number, scene_id, timestamp, frame_path FROM video_frames
                   WHERE video_id = ? AND timestamp BETWEEN ? AND ?
                   ORDER BY timestamp ASC LIMIT 3""",
                (expanded["videoId"], max(0.0, (expanded.get("startTime") or 0) - 15), (expanded.get("endTime") or 0) + 15)
            )
            video_results.append({
                "id": tr["id"],
                "videoId": expanded["videoId"],
                "sourceId": expanded["sourceId"],
                "videoTitle": source.get("original_name") if source else "Video",
                "startTime": expanded.get("startTime") or 0,
                "endTime": expanded.get("endTime") or 0,
                "duration": source.get("duration_seconds") if source else None,
                "transcript": expanded.get("transcriptText") or tr["text"],
                "snippet": tr["text"],
                "relevanceScore": tr["score"],
                "uploadDate": source.get("upload_date") if source else None,
                "matchingFrames": [
                    {
                        "id": f["id"],
                        "frameNumber": f["frame_number"],
                        "sceneId": f["scene_id"],
                        "timestamp": f["timestamp"],
                        "framePath": f["frame_path"],
                    }
                    for f in frames
                ],
            })
            if len(video_results) >= limit:
                break
        return video_results

    video_results = await run_in_threadpool(_search)
    return {"query": query, "results": video_results, "total": len(video_results)}

def normalize_url(url: Optional[str]) -> str:
    if not url:
        return ""
    clean = url.strip().lower()
    clean = re.sub(r"^https?:\/\/", "", clean)
    clean = re.sub(r"^www\.", "", clean)
    yt = re.search(r"(?:youtube\.com\/(?:watch\?v=|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})", clean)
    if yt:
        return f"yt:{yt.group(1)}"
    clean = clean.split("?")[0].split("#")[0]
    return clean.rstrip("/")

def normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    return re.sub(r"[^a-z0-9]", "", title.lower()).strip()

@router.post("/fetch-more")
async def fetch_more(req: FetchMoreRequest, user: Dict[str, Any] = Depends(require_auth)):
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")

    stype = req.type
    current_count = req.currentCount or 8
    effective_limit = req.targetLimit if req.targetLimit and req.targetLimit > 0 else max(12, current_count + 4)

    existing_urls = {normalize_url(u) for u in (req.existingUrls or []) if normalize_url(u)}
    existing_titles = {normalize_title(t) for t in (req.existingTitles or []) if normalize_title(t)}

    fetched_sources = []
    provider_status = None
    next_page_token = None
    next_offset = None
    next_page = None

    if stype == "video":
        res = await search_videos(topic, {
            "pageToken": req.pageToken,
            "offset": req.offset,
            "maxResults": min(50, effective_limit)
        })
        fetched_sources = res.get("sources", [])
        provider_status = {
            "provider": res.get("provider", "YouTube"),
            "category": "video",
            "status": res.get("status", "success"),
            "count": res.get("count", 0),
            "error": res.get("error"),
        }
        next_page_token = res.get("nextPageToken")
    elif stype == "paper":
        res = await search_papers(topic, {
            "offset": req.offset or 0,
            "limit": min(50, effective_limit)
        })
        fetched_sources = res.get("sources", [])
        provider_status = {
            "provider": res.get("provider", "Academic"),
            "category": "paper",
            "status": res.get("status", "success"),
            "count": res.get("count", 0),
            "error": res.get("error"),
        }
        next_offset = res.get("offset")
    elif stype == "article":
        res = await search_articles_only(topic, {
            "page": req.page or 1,
            "limit": min(100, effective_limit)
        })
        fetched_sources = res.get("sources", [])
        provider_status = res.get("providerResult")
        next_page = res.get("page")
    elif stype == "report":
        res = await search_reports_only(topic, {
            "page": req.page or 1,
            "limit": min(100, effective_limit)
        })
        fetched_sources = res.get("sources", [])
        provider_status = res.get("providerResult")
        next_page = res.get("page")
    elif stype == "web":
        res = await search_web(topic, {
            "page": req.page or 1,
            "offset": req.offset or 0,
            "limit": min(50, effective_limit)
        })
        fetched_sources = res.get("sources", [])
        provider_status = {
            "provider": res.get("provider", "Web"),
            "category": "web",
            "status": res.get("status", "success"),
            "count": res.get("count", 0),
            "error": res.get("error"),
        }
        next_offset = res.get("offset")
        next_page = res.get("page")
    else:
        raise HTTPException(status_code=400, detail=f"Invalid source type: {stype}")

    unique_sources = []
    seen_in_batch = set()

    for s in fetched_sources:
        n_url = normalize_url(s.get("url"))
        n_title = normalize_title(s.get("title"))

        if not n_url and not n_title:
            continue
        if n_url and (n_url in existing_urls or n_url in seen_in_batch):
            continue
        if n_title and len(n_title) > 8 and (n_title in existing_titles or n_title in seen_in_batch):
            continue

        if n_url: seen_in_batch.add(n_url)
        if n_title: seen_in_batch.add(n_title)
        unique_sources.append(s)

    return {
        "sources": unique_sources,
        "providerStatus": provider_status,
        "rawCount": len(fetched_sources),
        "newCount": len(unique_sources),
        "targetLimit": effective_limit,
        "nextPageToken": next_page_token,
        "offset": next_offset,
        "page": next_page,
    }

@router.post("/synthesize")
async def synthesize(req: SynthesizeRequest, user: Dict[str, Any] = Depends(require_auth)):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    selected_local = req.selectedLocalDocs or []
    selected_internet = req.selectedInternetSources or []

    if not selected_local and not selected_internet:
        raise HTTPException(status_code=400, detail="At least one source must be selected")

    local_parts = []
    for idx, item in enumerate(selected_local):
        sec = f"Section: {item['sectionTitle']}\n" if item.get("sectionTitle") else ""
        pg = f"Page: {item['pageNum']}\n" if item.get("pageNum") else ""
        ts = f"Timestamp: {item['startTime']}s - {item['endTime']}s\n" if item.get("startTime") is not None else ""
        content = item.get("fullContext") or item.get("snippet") or ""
        local_parts.append(
            f"[Local File {idx + 1}] Title: {item.get('title')} ({item.get('category', '').upper()} - {item.get('fileType', '').upper()})\n"
            f"Original Name: {item.get('originalName')}\n{sec}{pg}{ts}Excerpt Content:\n{content}\n"
        )
    local_section = "\n---\n".join(local_parts) if local_parts else "No local files selected."

    internet_parts = []
    for idx, src in enumerate(selected_internet):
        internet_parts.append(
            f"[Internet Source {idx + 1}] Title: {src.get('title')}\n"
            f"Category: {src.get('category', '').upper()}\n"
            f"Domain/Source: {src.get('domain')}\n"
            f"URL: {src.get('url')}\n"
            f"Summary Content:\n{src.get('snippet')}\n"
        )
    internet_section = "\n---\n".join(internet_parts) if internet_parts else "No internet sources selected."

    prompt = f"""You are an elite research intelligence analyst.
A user asked: "{query}"

Synthesize the following categorized sources into a comprehensive, multi-dimensional executive research report.

### CONTEXT FROM INTERNAL LOCAL FILES ({len(selected_local)} selected):
{local_section}

### CONTEXT FROM EXTERNAL INTERNET SOURCES ({len(selected_internet)} selected):
{internet_section}

---

### INSTRUCTIONS:
Structure your response in rich Markdown with the following clear sections:

1. **Executive Summary**
   - Provide a direct, high-level answer to the user's inquiry based on the evidence.

2. **Internal Knowledge Base Findings**
   - Highlight key evidence, data points, methodologies, and conclusions found in the local files.
   - Reference specific files and pages/timestamps.

3. **External Internet & Market Intelligence**
   - Highlight real-time facts, industry standards, recent news, or academic insights.
   - Reference web sources with domain names and links.

4. **Cross-Source Synthesis & Comparative Analysis**
   - Synthesize how the local files align with, contradict, or extend external internet data.
   - Point out unique internal knowledge vs. public internet consensus.

5. **Strategic Takeaways & Actionable Recommendations**
   - Provide 3-5 concrete, actionable conclusions.

6. **Cited Sources Reference**
   - Provide a clean list of all cited local files and web URLs.

Tone: Objective, thorough, analytical, and professional."""

    from app.ai.groq_client import get_async_groq_client
    client = get_async_groq_client()
    try:
        completion = await asyncio.wait_for(
            client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are an advanced AI research analyst specialized in cross-source data synthesis and knowledge extraction."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=850,
                timeout=12.0,
            ),
            timeout=14.0
        )
        summary = completion.choices[0].message.content or "Unable to generate synthesis."
    except Exception as e:
        print(f"[Synthesize] LLM error: {e}")
        summary = f"Error generating synthesis: {e}"

    import datetime
    return {
        "query": query,
        "summary": summary,
        "sourcesCount": {
            "local": len(selected_local),
            "internet": len(selected_internet),
            "total": len(selected_local) + len(selected_internet),
        },
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
