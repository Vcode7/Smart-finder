import re
import json
import base64
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File, Form

from app.core.config import settings
from app.database.session import db_get, db_all
from app.api.deps import get_current_user, require_auth
from app.schemas.search import (
    SearchRequest, LocalSearchRequest, VideoSearchRequest,
    FetchMoreRequest, SynthesizeRequest
)
from app.search.providers.youtube import search_videos
from app.search.providers.academic import search_papers
from app.search.providers.news import search_news, search_articles_only, search_reports_only
from app.search.providers.web import search_web
from app.search.providers.images import search_internet_images
from app.search.keyword_search import search_document_chunks, search_transcripts
from app.search.context_expander import expand_document_chunk, expand_transcript_segment
from app.search.face_detector import detect_faces_in_image, search_face_embeddings
from app.search.query_understanding import understand_multimodal_query, generate_enhanced_internet_query, detect_file_category
from app.search.multimodal_retrieval import search_by_multimodal_signals, search_by_text

router = APIRouter(prefix="/search", tags=["search"])

@router.post("")
async def unified_search(req: SearchRequest):
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")

    source = req.source or "internet"

    internet_results: Dict[str, Any] = {
        "videos": [], "papers": [], "articles": [], "reports": [], "web": [], "providerStatuses": {}
    }

    if source in ("internet", "both"):
        import asyncio
        v_task = search_videos(topic)
        p_task = search_papers(topic)
        n_task = search_news(topic)
        w_task = search_web(topic)

        v_res, p_res, n_res, w_res = await asyncio.gather(v_task, p_task, n_task, w_task, return_exceptions=True)

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

    local_documents = []
    local_videos = []

    if source in ("local", "both"):
        text_res = await search_by_text(topic, limit=10)
        local_documents = text_res.get("documents", [])
        local_videos = text_res.get("videos", [])

    return {
        "source": source,
        **internet_results,
        "localDocuments": local_documents,
        "localVideos": local_videos,
    }

@router.post("/local")
async def local_search(req: LocalSearchRequest, user: Dict[str, Any] = Depends(require_auth)):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    limit = req.limit or 10
    res = await search_by_text(query, limit=limit)
    return {
        "query": query,
        "documents": res.get("documents", []),
        "videos": res.get("videos", []),
        "images": res.get("images", []),
        "audio": res.get("audio", []),
        "total": res.get("total", 0),
    }

@router.post("/extract-query")
async def extract_search_query(request: Request):
    """
    Extract a clean search query, keywords, and relevant search terms from user chat inquiry
    plus optional uploaded image or document file using LLM.
    """
    content_type = request.headers.get("content-type") or ""
    query_text = ""
    file_buffer: Optional[bytes] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_snippet: Optional[str] = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        query_text = str(form.get("query") or "")
        target_file = form.get("file") or form.get("image")
        if target_file and hasattr(target_file, "filename") and target_file.filename:
            file_name = target_file.filename
            mime_type = target_file.content_type
            file_buffer = await target_file.read()
    else:
        try:
            body = await request.json()
        except Exception:
            body = {}
        query_text = body.get("query", "")
        file_name = body.get("fileName")
        mime_type = body.get("mimeType")
        img_b64 = body.get("imageBase64")
        if img_b64:
            clean_b64 = re.sub(r"^data:image\/\w+;base64,", "", img_b64)
            try:
                file_buffer = base64.b64decode(clean_b64)
                mime_type = mime_type or "image/jpeg"
            except Exception:
                pass

    # Extract text snippet from uploaded reference file if present
    if file_buffer:
        cat = detect_file_category(file_name, mime_type)
        if cat == "document":
            ext = (file_name.split(".")[-1].lower()) if (file_name and "." in file_name) else "txt"
            if ext == "pdf":
                try:
                    import pypdf, io
                    reader = pypdf.PdfReader(io.BytesIO(file_buffer))
                    pages_text = [p.extract_text() or "" for p in reader.pages[:3]]
                    file_snippet = "\n".join(pages_text).strip()[:1500]
                except Exception as e:
                    print(f"[ExtractQuery] PDF extract notice: {e}")
            else:
                try:
                    file_snippet = file_buffer.decode("utf-8", errors="ignore").strip()[:1500]
                except Exception:
                    pass
            if not file_snippet:
                file_snippet = f"User attached document: {file_name or 'Uploaded Document'}"
        elif cat == "image":
            try:
                from app.search.face_detector import detect_faces_in_image
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

    # Fallback values if LLM unavailable
    fallback_query = query_text.strip() or (Path(file_name).stem if file_name else "Research Documents")
    words = [w for w in re.split(r"[\s,;]+", fallback_query) if len(w) >= 3]
    fallback_keywords = words[:5] if words else [fallback_query]
    fallback_terms = [fallback_query]
    fallback_intent = "Document and knowledge source retrieval"

    # Use Groq LLM to generate clean search query, keywords, and search terms
    if settings.GROQ_API_KEY:
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

            resp = await client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an elite search query formulation specialist. Your role is to convert complex user prompts and reference file contents into clean, precise search queries, keywords, and terms for document retrieval. Return ONLY a valid JSON object."
                    },
                    {
                        "role": "user",
                        "content": prompt_content
                    }
                ],
                max_tokens=300,
                temperature=0.2,
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
            print(f"[ExtractQuery] Groq extraction error: {e}")

    return {
        "searchQuery": fallback_query,
        "keywords": fallback_keywords,
        "searchTerms": fallback_terms,
        "intent": fallback_intent,
        "fileSnippet": file_snippet[:1500] if file_snippet else None,
        "originalQuery": query_text,
    }

@router.post("/smart")
async def smart_search(request: Request):
    content_type = request.headers.get("content-type") or ""
    query_text = ""
    file_buffer = None
    file_name = None
    mime_type = None
    preview_url = None
    enable_internet = False
    relative_threshold = 0.20
    raw_thresh = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        query_text = str(form.get("query") or "")
        enable_internet = form.get("enableInternet") == "true" or form.get("enableInternetSources") == "true"
        raw_thresh = form.get("relativeThreshold")
        target_file = form.get("file") or form.get("image")
        if target_file and hasattr(target_file, "filename") and target_file.filename:
            file_name = target_file.filename
            mime_type = target_file.content_type
            file_buffer = await target_file.read()
            if mime_type and mime_type.startswith("image/"):
                preview_url = f"data:{mime_type};base64,{base64.b64encode(file_buffer).decode('utf-8')}"
    else:
        try:
            body = await request.json()
        except Exception:
            try:
                raw_bytes = await request.body()
                body = json.loads(raw_bytes.decode("utf-8", errors="ignore")) if raw_bytes else {}
            except Exception:
                body = {}
        query_text = body.get("query", "")
        file_name = body.get("fileName")
        mime_type = body.get("mimeType")
        enable_internet = body.get("enableInternet") is True or body.get("enableInternetSources") is True
        raw_thresh = body.get("relativeThreshold")
        img_b64 = body.get("imageBase64")
        if img_b64:
            clean_b64 = re.sub(r"^data:image\/\w+;base64,", "", img_b64)
            file_buffer = base64.b64decode(clean_b64)
            preview_url = img_b64
            mime_type = mime_type or "image/jpeg"

    if raw_thresh is not None:
        try:
            val = float(raw_thresh)
            if val > 1.0:
                val = val / 100.0
            relative_threshold = max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            relative_threshold = 0.20

    if not query_text.strip() and not file_buffer:
        raise HTTPException(status_code=400, detail="Please provide a search query or upload reference material.")

    file_category = detect_file_category(file_name, mime_type)
    signals = await understand_multimodal_query({
        "textQuery": query_text,
        "fileBuffer": file_buffer,
        "fileName": file_name,
        "mimeType": mime_type,
        "fileCategory": file_category,
        "previewUrl": preview_url,
    })

    # 1. Local Search First
    local_res = await search_by_multimodal_signals(signals)
    all_local_matches = [
        *local_res.get("videos", []),
        *local_res.get("documents", []),
        *local_res.get("images", []),
        *local_res.get("audio", []),
    ]
    all_local_matches.sort(key=lambda x: x.get("relevanceScore", 0), reverse=True)

    # 2. Extract context & generate enriched query
    enhanced = await generate_enhanced_internet_query(signals, all_local_matches)
    target_internet_query = enhanced.get("primaryQuery") or query_text or "AI Research Intelligence"

    # 3. Multi-category internet search (if enabled)
    internet_web = []
    internet_news = []
    internet_papers = []
    internet_videos = []
    internet_images = []

    if enable_internet:
        import asyncio
        w_task = search_web(target_internet_query)
        n_task = search_news(target_internet_query)
        p_task = search_papers(target_internet_query)
        v_task = search_videos(target_internet_query)
        i_task = search_internet_images(target_internet_query, 8)

        try:
            w_res, n_res, p_res, v_res, i_res = await asyncio.wait_for(
                asyncio.gather(w_task, n_task, p_task, v_task, i_task, return_exceptions=True),
                timeout=12.0
            )
        except asyncio.TimeoutError:
            print("[SmartSearch] Internet search providers timed out after 12s, proceeding with available data")
            w_res, n_res, p_res, v_res, i_res = None, None, None, None, None

        if isinstance(w_res, dict) and w_res.get("sources"):
            for it in w_res["sources"][:8]:
                try:
                    domain = urllib.parse.urlparse(it.get("url", "https://google.com")).hostname or "google.com"
                    domain = re.sub(r"^www\.", "", domain)
                    internet_web.append({
                        "id": it.get("id"), "category": "web", "title": it.get("title", ""), "url": it.get("url", ""),
                        "snippet": it.get("description", ""), "domain": domain, "publishedDate": it.get("date"),
                        "thumbnail": it.get("thumbnail"), "relevanceScore": 0.92,
                    })
                except Exception: pass

        if isinstance(n_res, dict) and n_res.get("articles"):
            for it in n_res["articles"][:6]:
                try:
                    domain = urllib.parse.urlparse(it.get("url", "https://news.google.com")).hostname or "news"
                    domain = re.sub(r"^www\.", "", domain)
                    internet_news.append({
                        "id": it.get("id"), "category": "news", "title": it.get("title", ""), "url": it.get("url", ""),
                        "snippet": it.get("description", ""), "domain": domain, "publishedDate": it.get("date"),
                        "author": it.get("author"), "relevanceScore": 0.89,
                    })
                except Exception: pass

        if isinstance(p_res, dict) and p_res.get("sources"):
            for it in p_res["sources"][:6]:
                internet_papers.append({
                    "id": it.get("id"), "category": "paper", "title": it.get("title", ""),
                    "url": it.get("url") or f"https://semanticscholar.org/search?q={urllib.parse.quote(it.get('title', ''))}",
                    "snippet": it.get("description", ""), "domain": "semanticscholar.org",
                    "publishedDate": it.get("date"), "author": it.get("author"), "relevanceScore": 0.90,
                })

        if isinstance(v_res, dict) and v_res.get("sources"):
            for it in v_res["sources"][:6]:
                vid_id = it.get("id", "").replace("yt-", "")
                internet_videos.append({
                    "id": it.get("id"), "category": "video", "title": it.get("title", ""),
                    "url": it.get("url") or f"https://youtube.com/watch?v={vid_id}",
                    "snippet": it.get("description", ""), "domain": "youtube.com",
                    "publishedDate": it.get("date"), "author": it.get("author"),
                    "thumbnail": it.get("thumbnail"), "relevanceScore": 0.90,
                })

        if isinstance(i_res, list):
            for it in i_res[:8]:
                internet_images.append({
                    "id": it["id"], "category": "image", "title": it.get("title", ""),
                    "url": it.get("sourceUrl") or it.get("url", ""), "snippet": f"Image from {it.get('domain')}",
                    "domain": it.get("domain", "web"), "thumbnail": it.get("thumbnail") or it.get("url", ""),
                    "relevanceScore": 0.88,
                })

    # 4. Relative Similarity Threshold Filtering
    all_scores = [m.get("relevanceScore", 0.0) for m in all_local_matches]
    if enable_internet:
        all_scores.extend([
            it.get("relevanceScore", 0.0)
            for it in (internet_web + internet_news + internet_papers + internet_videos + internet_images)
        ])
    top_score = max(all_scores, default=0.0)
    min_score = max(0.0, round(top_score - relative_threshold, 4))

    total_before = len(all_local_matches) + (len(internet_web) + len(internet_news) + len(internet_papers) + len(internet_videos) + len(internet_images) if enable_internet else 0)

    # Apply threshold filtering to local results
    filtered_documents = [d for d in local_res.get("documents", []) if d.get("relevanceScore", 0.0) >= min_score]
    filtered_videos = [v for v in local_res.get("videos", []) if v.get("relevanceScore", 0.0) >= min_score]
    filtered_images = [i for i in local_res.get("images", []) if i.get("relevanceScore", 0.0) >= min_score]
    filtered_audio = [a for a in local_res.get("audio", []) if a.get("relevanceScore", 0.0) >= min_score]
    all_local_matches = [m for m in all_local_matches if m.get("relevanceScore", 0.0) >= min_score]
    local_total = len(filtered_documents) + len(filtered_videos) + len(filtered_images) + len(filtered_audio)

    # Apply threshold filtering to internet results if enabled
    if enable_internet:
        internet_web = [it for it in internet_web if it.get("relevanceScore", 0.0) >= min_score]
        internet_news = [it for it in internet_news if it.get("relevanceScore", 0.0) >= min_score]
        internet_papers = [it for it in internet_papers if it.get("relevanceScore", 0.0) >= min_score]
        internet_videos = [it for it in internet_videos if it.get("relevanceScore", 0.0) >= min_score]
        internet_images = [it for it in internet_images if it.get("relevanceScore", 0.0) >= min_score]
        internet_total = len(internet_web) + len(internet_news) + len(internet_papers) + len(internet_videos) + len(internet_images)
    else:
        internet_total = 0

    total_after = local_total + internet_total

    print(f"[SmartSearch Threshold] top_score={top_score:.4f}, configured_threshold={relative_threshold:.4f}, min_score={min_score:.4f}, results_before={total_before}, results_after={total_after}")

    discovery_trace = {
        "inputType": signals.get("queryType"),
        "inputName": signals.get("fileName"),
        "inputPreview": signals.get("previewUrl"),
        "extractedSignals": {
            "hasFace": signals.get("hasFace"),
            "faceCount": len(signals.get("faces", [])),
            "ocrSnippet": signals.get("ocrText")[:160] if signals.get("ocrText") else None,
            "speechSnippet": signals.get("speechTranscript")[:160] if signals.get("speechTranscript") else None,
            "visualDescription": signals.get("visualDescription")[:160] if signals.get("visualDescription") else None,
            "extractedEntities": signals.get("extractedEntities"),
        },
        "topLocalMatch": {
            "id": all_local_matches[0]["id"],
            "sourceId": all_local_matches[0]["sourceId"],
            "title": all_local_matches[0]["title"],
            "category": all_local_matches[0]["category"],
            "relevanceScore": all_local_matches[0]["relevanceScore"],
            "timestamp": all_local_matches[0].get("startTime"),
            "isFaceMatch": all_local_matches[0].get("isFaceMatch"),
            "faceSimilarity": all_local_matches[0].get("faceSimilarity"),
            "snippet": all_local_matches[0].get("snippet"),
        } if all_local_matches else None,
        "enhancedQuery": target_internet_query,
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
            "topScore": round(top_score, 4),
            "relativeThreshold": round(relative_threshold, 4),
            "minScore": round(min_score, 4),
            "resultsBefore": total_before,
            "resultsAfter": total_after,
        },
        "internet": {
            "web": internet_web, "news": internet_news, "papers": internet_papers,
            "videos": internet_videos, "images": internet_images, "total": internet_total,
        },
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

@router.post("/similar")
async def find_similar_sources(request: Request):
    content_type = request.headers.get("content-type") or ""
    source_id = None
    relative_threshold = 0.20
    raw_thresh = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        source_id = str(form.get("sourceId") or form.get("source_id") or "").strip()
        raw_thresh = form.get("relativeThreshold")
    else:
        try:
            body = await request.json()
        except Exception:
            try:
                raw_bytes = await request.body()
                body = json.loads(raw_bytes.decode("utf-8", errors="ignore")) if raw_bytes else {}
            except Exception:
                body = {}
        source_id = str(body.get("sourceId") or body.get("source_id") or "").strip()
        raw_thresh = body.get("relativeThreshold")

    if raw_thresh is not None:
        try:
            val = float(raw_thresh)
            if val > 1.0:
                val = val / 100.0
            relative_threshold = max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            relative_threshold = 0.20

    if not source_id:
        raise HTTPException(status_code=400, detail="sourceId is required to find similar sources")

    source = db_get(
        "SELECT id, original_name, file_type, file_path, file_size, upload_date, tags_json, metadata_json FROM knowledge_sources WHERE id = ?",
        (source_id,)
    )
    if not source:
        raise HTTPException(status_code=404, detail=f"Source with id '{source_id}' not found")

    title = source["original_name"]
    file_type = (source.get("file_type") or "").lower()

    # Retrieve document sections & chunks
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

    # Retrieve video transcripts
    transcripts = db_all(
        "SELECT text, start_time FROM video_transcripts WHERE source_id = ? ORDER BY start_time ASC LIMIT 12",
        (source_id,)
    )
    transcript_texts = [t["text"] for t in transcripts if t.get("text")]
    video_summary = " ".join(transcript_texts)[:1000] if transcript_texts else ""

    # Retrieve tags / keywords
    keywords = []
    if source.get("tags_json"):
        try:
            kws = json.loads(source["tags_json"])
            if isinstance(kws, list):
                keywords.extend(kws)
        except Exception:
            pass
    if section_titles:
        keywords.extend(section_titles)

    # Retrieve visual signals (pHash, dHash, image embeddings)
    img_row = db_get(
        "SELECT image_path, phash, dhash FROM image_perceptual_hashes WHERE source_id = ? LIMIT 1",
        (source_id,)
    )
    phash = img_row.get("phash") if img_row else None
    dhash = img_row.get("dhash") if img_row else None
    img_path = img_row.get("image_path") if img_row else (
        source["file_path"] if file_type in ("jpg", "png", "webp", "jpeg", "bmp") else None
    )

    img_emb = None
    if img_path and Path(img_path).exists():
        try:
            from app.search.model_pipeline import get_image_embedding
            img_emb = get_image_embedding(img_path)
        except Exception as e:
            print(f"[Find Similar Sources] Notice loading image embedding: {e}")

    text_content = doc_summary or video_summary
    from app.search.keyword_search import extract_query_tokens
    tokens = extract_query_tokens(f"{title} {text_content}")
    from collections import Counter
    top_tokens = [w for w, _ in Counter(tokens).most_common(8)]
    combined_keywords = list(dict.fromkeys(keywords + top_tokens))

    query_preview = f"{title} {' '.join(combined_keywords[:6])}".strip()

    text_emb = None
    if text_content:
        try:
            from app.search.model_pipeline import get_text_embedding
            text_emb = get_text_embedding(f"{title} {text_content}"[:1200])
        except Exception as e:
            print(f"[Find Similar Sources] Notice loading text embedding: {e}")

    signals = {
        "queryType": "similar_source",
        "textQuery": query_preview,
        "originalQueryText": title,
        "textEmbedding": text_emb,
        "documentText": doc_summary if doc_summary else None,
        "derivedSearchKeywords": " ".join(combined_keywords[:8]),
        "ocrText": doc_summary[:500] if doc_summary else None,
        "speechTranscript": video_summary[:500] if video_summary else None,
        "fileName": title,
        "phash": phash,
        "dhash": dhash,
        "imageEmbedding": img_emb,
    }

    # Execute search across existing vector & text indexes
    raw_res = await search_by_multimodal_signals(signals)

    # Exclude the query source itself so it does not dominate
    filtered_documents = [
        d for d in raw_res.get("documents", [])
        if d.get("sourceId") != source_id and d.get("id") != f"src-{source_id}"
    ]
    filtered_videos = [
        v for v in raw_res.get("videos", [])
        if v.get("sourceId") != source_id and v.get("id") != f"src-{source_id}"
    ]
    filtered_images = [
        i for i in raw_res.get("images", [])
        if i.get("sourceId") != source_id and i.get("id") != f"src-{source_id}"
    ]
    filtered_audio = [
        a for a in raw_res.get("audio", [])
        if a.get("sourceId") != source_id and a.get("id") != f"src-{source_id}"
    ]

    all_matches = [*filtered_videos, *filtered_documents, *filtered_images, *filtered_audio]
    all_matches.sort(key=lambda x: x.get("relevanceScore", 0.0), reverse=True)

    # Apply relative threshold filtering
    top_score = max([m.get("relevanceScore", 0.0) for m in all_matches], default=0.0)
    min_score = max(0.0, round(top_score - relative_threshold, 4))
    total_before = len(all_matches)

    final_docs = [d for d in filtered_documents if d.get("relevanceScore", 0.0) >= min_score]
    final_vids = [v for v in filtered_videos if v.get("relevanceScore", 0.0) >= min_score]
    final_imgs = [i for i in filtered_images if i.get("relevanceScore", 0.0) >= min_score]
    final_auds = [a for a in filtered_audio if a.get("relevanceScore", 0.0) >= min_score]
    final_matches = [m for m in all_matches if m.get("relevanceScore", 0.0) >= min_score]
    total_related = len(final_matches)

    # Structured logs as requested
    print(f"[Find Similar Sources] Selected source: '{title}' (id: {source_id})")
    print(f"[Find Similar Sources] Keywords/Summary used: '{query_preview}'")
    print(f"[Find Similar Sources] Number of related sources returned: {total_related}")
    print(f"[Find Similar Sources Threshold] top_score={top_score:.4f}, configured_threshold={relative_threshold:.4f}, min_score={min_score:.4f}, results_before={total_before}, results_after={total_related}")

    discovery_trace = {
        "inputType": "similar_source",
        "inputName": title,
        "extractedSignals": {
            "sourceTitle": title,
            "sourceType": file_type,
            "keywords": combined_keywords[:8],
            "hasVisualSignal": bool(phash or img_emb is not None),
            "summarySnippet": (text_content[:200] + "...") if text_content else None,
        },
        "topLocalMatch": final_matches[0] if final_matches else None,
        "enhancedQuery": query_preview,
    }

    return {
        "query": f"Similar to: {title}",
        "sourceId": source_id,
        "sourceTitle": title,
        "discoveryTrace": discovery_trace,
        "thresholdInfo": {
            "topScore": round(top_score, 4),
            "relativeThreshold": round(relative_threshold, 4),
            "minScore": round(min_score, 4),
            "resultsBefore": total_before,
            "resultsAfter": total_related,
        },
        "local": {
            "documents": final_docs,
            "videos": final_vids,
            "audio": final_auds,
            "images": final_imgs,
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
async def multimodal_search(request: Request):
    content_type = request.headers.get("content-type") or ""
    query_text = ""
    file_buffer = None
    file_name = None
    mime_type = None
    preview_url = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        query_text = str(form.get("query") or "")
        target_file = form.get("file") or form.get("image")
        if target_file and hasattr(target_file, "filename") and target_file.filename:
            file_name = target_file.filename
            mime_type = target_file.content_type
            file_buffer = await target_file.read()
            if mime_type and mime_type.startswith("image/"):
                preview_url = f"data:{mime_type};base64,{base64.b64encode(file_buffer).decode('utf-8')}"
    else:
        try:
            body = await request.json()
        except Exception:
            try:
                raw_bytes = await request.body()
                body = json.loads(raw_bytes.decode("utf-8", errors="ignore")) if raw_bytes else {}
            except Exception:
                body = {}
        query_text = body.get("query", "")
        file_name = body.get("fileName")
        mime_type = body.get("mimeType")
        img_b64 = body.get("imageBase64")
        if img_b64:
            clean_b64 = re.sub(r"^data:image\/\w+;base64,", "", img_b64)
            file_buffer = base64.b64decode(clean_b64)
            preview_url = img_b64
            mime_type = mime_type or "image/jpeg"

    if not query_text.strip() and not file_buffer:
        raise HTTPException(status_code=400, detail="Please provide a text query or upload reference material.")

    file_category = detect_file_category(file_name, mime_type)
    signals = await understand_multimodal_query({
        "textQuery": query_text,
        "fileBuffer": file_buffer,
        "fileName": file_name,
        "mimeType": mime_type,
        "fileCategory": file_category,
        "previewUrl": preview_url,
    })

    results = await search_by_multimodal_signals(signals)
    return results

@router.post("/face")
async def face_search(request: Request, user: Dict[str, Any] = Depends(require_auth)):
    content_type = request.headers.get("content-type") or ""
    matches = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        target_file = form.get("file") or form.get("image")
        if target_file and hasattr(target_file, "filename") and target_file.filename:
            buf = await target_file.read()
            face_res = await detect_faces_in_image(buf, {"sourceId": "query"})
            for f in face_res.get("faces", []):
                if f.get("embedding"):
                    res = search_face_embeddings(f["embedding"], min_similarity=0.50, limit=10)
                    matches.extend(res)
    else:
        body = await request.json()
        if body.get("embedding") and isinstance(body["embedding"], list):
            matches = search_face_embeddings(body["embedding"], min_similarity=0.50, limit=10)
        elif body.get("imageBase64"):
            clean_b64 = re.sub(r"^data:image\/\w+;base64,", "", body["imageBase64"])
            buf = base64.b64decode(clean_b64)
            face_res = await detect_faces_in_image(buf, {"sourceId": "query"})
            for f in face_res.get("faces", []):
                if f.get("embedding"):
                    res = search_face_embeddings(f["embedding"], min_similarity=0.50, limit=10)
                    matches.extend(res)

    # Deduplicate matches
    seen = set()
    unique_matches = []
    for m in matches:
        key = f"{m.get('sourceId')}-{m.get('videoId')}-{m.get('timestamp')}"
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)
    unique_matches.sort(key=lambda x: x.get("similarity", 0), reverse=True)

    return {"matches": unique_matches[:10], "total": len(unique_matches)}

@router.post("/video")
async def video_search(req: VideoSearchRequest, user: Dict[str, Any] = Depends(require_auth)):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    limit = req.limit or 10
    raw_results = search_transcripts(query, limit * 2)
    video_results = []
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
async def fetch_more(req: FetchMoreRequest):
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
async def synthesize(req: SynthesizeRequest):
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
        completion = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are an advanced AI research analyst specialized in cross-source data synthesis and knowledge extraction."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=850
        )
        summary = completion.choices[0].message.content or "Unable to generate synthesis."
    except Exception as e:
        print(f"[Synthesize] Error with {settings.GROQ_MODEL} across Groq keys: {e}")
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
