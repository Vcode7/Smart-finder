import os
import re
import uuid
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.core.config import settings
from app.search.face_detector import detect_faces_in_image
from app.search.model_pipeline import (
    get_text_query_embedding,
    get_multimodal_text_embedding,
    get_image_embedding,
    transcribe_audio,
)

from app.search.constants import DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS

_AUDIO_MIME_EXT = {
    "audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/mp4": "m4a",
    "audio/x-m4a": "m4a", "audio/aac": "aac", "audio/flac": "flac", "audio/opus": "opus",
}


def detect_file_category(file_name: Optional[str], mime_type: Optional[str] = None) -> str:
    if mime_type:
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("video/"):
            return "video"
        if mime_type.startswith("audio/"):
            return "audio"
        if any(t in mime_type for t in ["pdf", "document", "text", "csv", "sheet"]):
            return "document"

    if file_name and "." in file_name:
        ext = file_name.split(".")[-1].lower()
        if ext in IMAGE_EXTENSIONS:
            return "image"
        if ext in VIDEO_EXTENSIONS:
            return "video"
        if ext in AUDIO_EXTENSIONS:
            return "audio"
        if ext in DOCUMENT_EXTENSIONS:
            return "document"

    # 'unknown' for unrecognized types — callers must handle this explicitly.
    return "unknown"


def _file_extension(file_name: Optional[str], mime_type: Optional[str], default: str) -> str:
    if file_name and "." in file_name:
        ext = re.sub(r"[^a-z0-9]", "", file_name.rsplit(".", 1)[-1].lower())
        if ext:
            return ext
    if mime_type:
        base = mime_type.split(";")[0].strip().lower()
        if base in _AUDIO_MIME_EXT:
            return _AUDIO_MIME_EXT[base]
    return default


def _temp_path(prefix: str, ext: str) -> Path:
    temp_dir = settings.resolved_upload_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"{prefix}_{uuid.uuid4()}.{ext}"


def _remove_quietly(*paths: Optional[Path]) -> None:
    for p in paths:
        if p and Path(p).exists():
            try:
                os.unlink(p)
            except Exception:
                pass


async def extract_entities_with_llm(text: str) -> List[str]:
    if not settings.get_groq_api_keys() or not text.strip():
        return []
    try:
        from app.ai.groq_client import get_async_groq_client, robust_json_loads
        client = get_async_groq_client()
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a named entity extractor. Return ONLY a JSON array of strings containing entities (people, organizations, exam names, acts, locations)."},
                    {"role": "user", "content": f"Extract entities from: \"{text}\""}
                ],
                max_tokens=150,
                temperature=0.1,
                timeout=3.0,
            ),
            timeout=3.5
        )
        content = resp.choices[0].message.content or "[]"
        raw_list = robust_json_loads(content, default=[])
        entities = []
        if isinstance(raw_list, list):
            for item in raw_list:
                if isinstance(item, str) and item.strip():
                    entities.append(item.strip())
                elif isinstance(item, dict):
                    val = item.get("name") or item.get("entity") or item.get("text")
                    if val and str(val).strip():
                        entities.append(str(val).strip())
        return entities
    except Exception as e:
        print(f"[QueryUnderstanding] Entity extraction notice: {e}")
        return []


async def transcribe_audio_with_whisper(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """Groq cloud Whisper (fallback when the local model is unavailable). filename must keep the real extension."""
    if not settings.get_groq_api_keys() or not audio_bytes:
        return ""
    try:
        from app.ai.groq_client import get_groq_client
        client = get_groq_client()

        def _transcribe():
            return client.audio.transcriptions.create(
                file=(filename, audio_bytes),
                model="whisper-large-v3",
                response_format="verbose_json",
                temperature=0.0
            )
        transcription = await asyncio.to_thread(_transcribe)
        return getattr(transcription, "text", "") or ""
    except Exception as e:
        print(f"[QueryUnderstanding] Groq Whisper transcription error: {e}")
        return ""


async def _transcribe_query_audio(path: Path) -> str:
    """Local faster-whisper first (same model as ingestion), Groq Whisper as fallback."""
    segments = await asyncio.to_thread(transcribe_audio, str(path))
    text = " ".join(s["text"] for s in segments).strip()
    if text:
        return text
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except Exception:
        return ""
    return await transcribe_audio_with_whisper(data, path.name)


async def understand_multimodal_query(input_data: Dict[str, Any], use_llm: bool = True) -> Dict[str, Any]:
    """
    Turn a query (text and/or one file) into retrieval signals.

    Each input keeps its own embedding key so retrieval can search them separately:
      textEmbedding (typed text), ocrEmbedding, transcriptEmbedding, documentEmbedding.
    use_llm=False skips the LLM calls (entity extraction, vision description) that only
    feed internet-query enhancement; local retrieval does not need them.
    """
    file_name = input_data.get("fileName")
    mime_type = input_data.get("mimeType")
    category = input_data.get("fileCategory") or detect_file_category(file_name, mime_type)
    text_query = (input_data.get("textQuery") or "").strip()
    file_buffer: Optional[bytes] = input_data.get("fileBuffer")
    file_path: Optional[str] = input_data.get("filePath")
    preview_url = input_data.get("previewUrl")

    if not file_name and not file_buffer and not file_path:
        category = "text"

    signals: Dict[str, Any] = {
        "queryType": category,
        "textQuery": text_query or None,
        "originalQueryText": text_query or None,
        "fileName": file_name,
        "previewUrl": preview_url,
        "hasFace": False,
        "faces": [],
        "faceEmbeddings": [],
        "extractedEntities": [],
        "derivedSearchKeywords": text_query,
    }

    # 1. Typed text
    if text_query:
        signals["textEmbedding"] = await asyncio.to_thread(get_text_query_embedding, text_query)
        clip_text_emb = await asyncio.to_thread(get_multimodal_text_embedding, text_query)
        if clip_text_emb is not None:
            signals["clipTextEmbedding"] = clip_text_emb
        if use_llm:
            signals["extractedEntities"].extend(await extract_entities_with_llm(text_query))

    # 2. Image / clipping
    if category in ("image", "clipping") and (file_buffer or file_path):
        img_data = file_buffer if file_buffer is not None else file_path
        face_res = await detect_faces_in_image(img_data, {"sourceId": "query", "useVision": use_llm})
        signals["hasFace"] = face_res["hasFace"]
        signals["faces"] = face_res["faces"]
        signals["primaryFace"] = face_res["primaryFace"]
        signals["ocrText"] = face_res["ocrText"]
        signals["visualDescription"] = face_res["visualDescription"]
        if face_res["identifiedNames"]:
            signals["extractedEntities"].extend(face_res["identifiedNames"])
        for f in face_res["faces"]:
            if f.get("embedding"):
                signals["faceEmbeddings"].append(f["embedding"])

        img_emb = await asyncio.to_thread(get_image_embedding, img_data)
        if img_emb:
            signals["visualEmbedding"] = img_emb
            signals["imageEmbedding"] = img_emb

        from app.search.perceptual_hash import compute_image_hashes
        q_ph, q_dh = await asyncio.to_thread(compute_image_hashes, img_data)
        signals["phash"] = q_ph
        signals["dhash"] = q_dh

        if not signals["derivedSearchKeywords"]:
            kw_parts = []
            if signals["extractedEntities"]:
                kw_parts.append(" ".join(signals["extractedEntities"]))
            elif signals.get("ocrText") and len(signals["ocrText"].strip()) > 15:
                kw_parts.append(signals["ocrText"][:120])
            signals["derivedSearchKeywords"] = " ".join(kw_parts).strip()

        if signals.get("ocrText") and len(signals["ocrText"].strip()) > 15:
            signals["ocrEmbedding"] = await asyncio.to_thread(get_text_query_embedding, signals["ocrText"][:1200])

    # 3. Video: one representative keyframe + the soundtrack transcript
    elif category == "video" and (file_buffer or file_path):
        owns_video = file_buffer is not None
        temp_vid = _temp_path("query_vid", _file_extension(file_name, mime_type, "mp4")) if owns_video else Path(file_path or "")
        temp_audio = _temp_path("query_aud", "wav")
        temp_frame = _temp_path("query_frame", "jpg")
        try:
            if owns_video:
                await asyncio.to_thread(temp_vid.write_bytes, file_buffer)

            await asyncio.to_thread(
                subprocess.run,
                ["ffmpeg", "-y", "-ss", "00:00:01", "-i", str(temp_vid), "-vframes", "1", "-q:v", "2", str(temp_frame)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=120,
            )
            if temp_frame.exists():
                signals["imageEmbedding"] = await asyncio.to_thread(get_image_embedding, str(temp_frame))

            await asyncio.to_thread(
                subprocess.run,
                ["ffmpeg", "-y", "-i", str(temp_vid), "-vn", "-ar", "16000", "-ac", "1", str(temp_audio)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=600,
            )
            if temp_audio.exists():
                signals["speechTranscript"] = await _transcribe_query_audio(temp_audio)
                if signals["speechTranscript"]:
                    if use_llm:
                        signals["extractedEntities"].extend(await extract_entities_with_llm(signals["speechTranscript"]))
                    signals["transcriptEmbedding"] = await asyncio.to_thread(
                        get_text_query_embedding, signals["speechTranscript"][:1200]
                    )
        except Exception as e:
            print(f"[QueryUnderstanding] Video processing notice: {e}")
        finally:
            _remove_quietly(temp_audio, temp_frame, temp_vid if owns_video else None)

        if not signals["derivedSearchKeywords"]:
            signals["derivedSearchKeywords"] = (signals.get("speechTranscript") or "")[:150] or file_name or "Video Query"

    # 4. Audio (voice notes, recordings): transcript with the real container format
    elif category == "audio" and (file_buffer or file_path):
        owns_audio = file_buffer is not None
        temp_aud = _temp_path("query_aud", _file_extension(file_name, mime_type, "webm")) if owns_audio else Path(file_path or "")
        try:
            if owns_audio:
                await asyncio.to_thread(temp_aud.write_bytes, file_buffer)
            if temp_aud.exists():
                signals["speechTranscript"] = await _transcribe_query_audio(temp_aud)
                if signals["speechTranscript"]:
                    if use_llm:
                        signals["extractedEntities"].extend(await extract_entities_with_llm(signals["speechTranscript"]))
                    signals["derivedSearchKeywords"] = signals["derivedSearchKeywords"] or signals["speechTranscript"][:150]
                    signals["transcriptEmbedding"] = await asyncio.to_thread(
                        get_text_query_embedding, signals["speechTranscript"][:1200]
                    )
        finally:
            if owns_audio:
                _remove_quietly(temp_aud)

    # 5. Document
    elif category == "document" and (file_buffer or file_path):
        doc_text = ""
        ext = file_name.split(".")[-1].lower() if file_name and "." in file_name else "txt"

        def _extract() -> str:
            import io
            if ext == "pdf":
                import pypdf
                stream = io.BytesIO(file_buffer) if file_buffer else open(file_path or "", "rb")
                with stream:
                    reader = pypdf.PdfReader(stream)
                    return "\n".join([page.extract_text() or "" for page in reader.pages[:10]])
            if ext in ("docx",):
                import docx
                stream = io.BytesIO(file_buffer) if file_buffer else open(file_path or "", "rb")
                with stream:
                    d = docx.Document(stream)
                    return "\n".join([p.text for p in d.paragraphs[:50] if p.text.strip()])
            data = file_buffer if file_buffer else Path(file_path or "").read_bytes()
            return data.decode("utf-8", errors="ignore")

        try:
            doc_text = await asyncio.to_thread(_extract)
        except Exception as e:
            print(f"[QueryUnderstanding] Document text extract notice: {e}")

        if doc_text:
            signals["documentText"] = doc_text
            entities = await extract_entities_with_llm(doc_text[:2500]) if use_llm else []
            signals["extractedEntities"].extend(entities)
            if not signals["derivedSearchKeywords"]:
                signals["derivedSearchKeywords"] = " ".join(entities[:4]) or doc_text[:120]
            signals["documentEmbedding"] = await asyncio.to_thread(get_text_query_embedding, doc_text[:1200])

    # 6. Unknown file type — log visibly so it can be added to a supported category
    elif category == "unknown" and file_name:
        print(
            f"[QueryUnderstanding] WARNING: Unrecognized file type for '{file_name}'. "
            f"Only text-query signals will be used."
        )
        if not signals["derivedSearchKeywords"] and file_name:
            signals["derivedSearchKeywords"] = Path(file_name).stem

    return signals


async def generate_enhanced_internet_query(
    signals: Dict[str, Any],
    local_matches: List[Dict[str, Any]]
) -> Dict[str, Any]:
    top_local = local_matches[0] if local_matches else None
    discovered_entities: set = set()
    for e in signals.get("extractedEntities", []):
        if isinstance(e, str) and e.strip():
            discovered_entities.add(e.strip())
        elif isinstance(e, dict):
            val = e.get("name") or e.get("entity") or e.get("text")
            if val and str(val).strip():
                discovered_entities.add(str(val).strip())

    local_context_snippets = []
    for m in local_matches[:4]:
        cat = str(m.get("category") or "").upper()
        title = m.get("title") or m.get("originalName") or ""
        snippet = m.get("snippet") or ""
        local_context_snippets.append(f"[{cat}] \"{title}\": {snippet}")
        if title:
            try:
                clean_title = re.sub(r"[-_]", " ", Path(str(title)).stem).strip()
                words = [w for w in clean_title.split() if len(w) >= 3]
                if len(words) >= 2:
                    discovered_entities.add(clean_title)
            except Exception:
                pass

    primary_query = signals.get("originalQueryText") or signals.get("derivedSearchKeywords") or "AI Research Intelligence"
    query_variants = [primary_query]
    context_summary = "Direct multimodal search execution across internet and indexed local knowledge base."

    # If local match exists, synthesize enriched query via the LLM
    if top_local and settings.get_groq_api_keys():
        try:
            ocr_info = f"Extracted OCR text: \"{signals.get('ocrText', '')[:200]}\"\n" if signals.get("ocrText") else ""
            speech_info = f"Speech transcript: \"{signals.get('speechTranscript', '')[:200]}\"\n" if signals.get("speechTranscript") else ""
            face_info = "A face was detected.\n" if signals.get("hasFace") else ""
            local_snippets_text = "\n".join(local_context_snippets)

            prompt = (
                f"You are an AI intelligence query specialist.\n"
                f"A user uploaded an input of type: {signals.get('queryType')} {signals.get('fileName', '')}.\n"
                f"{face_info}{ocr_info}{speech_info}\n"
                f"The local knowledge search found these high-relevance matches:\n"
                f"{local_snippets_text}\n\n"
                f"Top Local Match: \"{top_local.get('title')}\" ({top_local.get('category')})\n\n"
                f"Based on the discovered local context:\n"
                f"1. Extract authoritative entity names and designations (e.g. 'SSC Chairman Gopal Krishna').\n"
                f"2. Generate an ENHANCED INTERNET SEARCH QUERY to find current news, web pages, and research.\n"
                f"3. Generate 3 search query variants.\n"
                f"4. Write a 1-2 sentence context summary explaining how the local match enriched the internet query.\n\n"
                f"Return ONLY valid JSON:\n"
                f"{{\n"
                f'  "primaryQuery": "string",\n'
                f'  "queryVariants": ["query 1", "query 2", "query 3"],\n'
                f'  "discoveredEntities": ["Entity 1", "Entity 2"],\n'
                f'  "contextSummary": "string explanation"\n'
                f"}}"
            )

            from app.ai.groq_client import get_async_groq_client, robust_json_loads
            client = get_async_groq_client()
            completion = await asyncio.wait_for(
                client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "You are an AI intelligence query specialist. Do NOT include <think> tags. Return ONLY a valid JSON object."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=250,
                    temperature=0.1,
                    timeout=3.0,
                ),
                timeout=3.5
            )
            raw = completion.choices[0].message.content or "{}"
            parsed = robust_json_loads(raw, default={})
            if parsed.get("primaryQuery"):
                primary_query = parsed["primaryQuery"]
            if parsed.get("queryVariants"):
                query_variants = parsed["queryVariants"]
            if parsed.get("discoveredEntities"):
                for e in parsed["discoveredEntities"]:
                    if isinstance(e, str) and e.strip():
                        discovered_entities.add(e.strip())
                    elif isinstance(e, dict):
                        val = e.get("name") or e.get("entity") or e.get("text")
                        if val and str(val).strip():
                            discovered_entities.add(str(val).strip())
            if parsed.get("contextSummary"):
                context_summary = parsed["contextSummary"]
        except Exception as e:
            print(f"[QueryUnderstanding] LLM query enhancement notice: {e}")
            top_title = top_local.get("title") or top_local.get("originalName") or ""
            if top_title:
                try:
                    clean_title = re.sub(r"[-_]", " ", Path(str(top_title)).stem).strip()
                    primary_query = clean_title or primary_query
                except Exception:
                    pass

    lineage = [
        {"step": 1, "title": "Uploaded Reference Media", "description": f"Analyzed {signals.get('queryType')} input {signals.get('fileName', '')}", "type": "upload"},
    ]
    if signals.get("hasFace"):
        lineage.append({"step": 2, "title": "Face Detection & Embedding", "description": f"Detected {len(signals.get('faces', []))} face(s) in reference image", "type": "vision_face"})
    if top_local:
        lineage.append({"step": 3, "title": "Local Knowledge Base Match", "description": f"Discovered relevant local asset \"{top_local.get('title')}\"", "type": "local_match"})
        lineage.append({"step": 4, "title": "Context & Entity Extraction", "description": f"Enriched query using discovered entities {list(discovered_entities)[:3]}", "type": "context_extraction"})
    lineage.append({"step": len(lineage) + 1, "title": "Internet Query Execution", "description": f"Executed live search with query: \"{primary_query}\"", "type": "internet_query"})

    return {
        "primaryQuery": primary_query,
        "queryVariants": query_variants,
        "discoveredEntities": list(discovered_entities),
        "contextSummary": context_summary,
        "lineage": lineage,
    }
