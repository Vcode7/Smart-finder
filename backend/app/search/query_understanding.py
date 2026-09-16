import os
import re
import json
import uuid
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from app.core.config import settings
from app.search.face_detector import detect_faces_in_image
from app.search.model_pipeline import (
    get_text_embedding,
    get_multimodal_text_embedding,
    get_image_embedding,
)

DOCUMENT_EXTENSIONS = {'pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx', 'xls', 'json', 'xml', 'html'}
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}
VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
AUDIO_EXTENSIONS = {'mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac'}

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

    return "text"

async def extract_entities_with_llm(text: str) -> List[str]:
    if not settings.GROQ_API_KEY or not text.strip():
        return []
    try:
        from app.ai.groq_client import get_async_groq_client, robust_json_loads
        client = get_async_groq_client()
        resp = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a named entity extractor. Return ONLY a JSON array of strings containing entities (people, organizations, exam names, acts, locations)."},
                {"role": "user", "content": f"Extract entities from: \"{text}\""}
            ],
            max_tokens=200,
            temperature=0.1
        )
        content = resp.choices[0].message.content or "[]"
        return robust_json_loads(content, default=[])
    except Exception as e:
        print(f"[QueryUnderstanding] Entity extraction notice: {e}")
        return []

async def transcribe_audio_with_whisper(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    if not settings.GROQ_API_KEY or not audio_bytes:
        return ""
    try:
        from app.ai.groq_client import get_groq_client
        import io
        client = get_groq_client()
        def _transcribe():
            with io.BytesIO(audio_bytes) as f:
                f.name = filename
                return client.audio.transcriptions.create(
                    file=f,
                    model="whisper-large-v3",
                    response_format="verbose_json",
                    temperature=0.0
                )
        import asyncio
        transcription = await asyncio.to_thread(_transcribe)
        return getattr(transcription, "text", "") or ""
    except Exception as e:
        print(f"[QueryUnderstanding] Whisper transcription error: {e}")
        return ""

async def understand_multimodal_query(input_data: Dict[str, Any]) -> Dict[str, Any]:
    file_name = input_data.get("fileName")
    mime_type = input_data.get("mimeType")
    category = input_data.get("fileCategory") or detect_file_category(file_name, mime_type)
    text_query = (input_data.get("textQuery") or "").strip()
    file_buffer: Optional[bytes] = input_data.get("fileBuffer")
    file_path: Optional[str] = input_data.get("filePath")
    preview_url = input_data.get("previewUrl")

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

    # 1. Text Query
    if text_query:
        signals["textEmbedding"] = get_text_embedding(text_query)
        clip_text_emb = get_multimodal_text_embedding(text_query)
        if clip_text_emb is not None:
            signals["clipTextEmbedding"] = clip_text_emb
        text_entities = await extract_entities_with_llm(text_query)
        signals["extractedEntities"].extend(text_entities)

    # 2. Image / Clipping Query
    if category in ("image", "clipping") and (file_buffer or file_path):
        img_data = file_buffer if file_buffer is not None else file_path
        face_res = await detect_faces_in_image(img_data, {"sourceId": "query"})
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

        img_emb = get_image_embedding(img_data)
        if img_emb:
            signals["visualEmbedding"] = img_emb
            signals["imageEmbedding"] = img_emb

        # Compute query perceptual hashes (pHash + dHash)
        from app.search.perceptual_hash import compute_image_hashes
        q_ph, q_dh = compute_image_hashes(img_data)
        signals["phash"] = q_ph
        signals["dhash"] = q_dh

        if not signals["derivedSearchKeywords"]:
            kw_parts = []
            if signals["extractedEntities"]:
                kw_parts.append(" ".join(signals["extractedEntities"]))
            elif signals["ocrText"]:
                kw_parts.append(signals["ocrText"][:120])
            elif signals["visualDescription"]:
                kw_parts.append(signals["visualDescription"][:120])
            signals["derivedSearchKeywords"] = " ".join(kw_parts) or "Image Visual Search"

        if signals.get("ocrText") and len(signals["ocrText"].strip()) > 15:
            try:
                signals["textEmbedding"] = get_text_embedding(signals["ocrText"][:1200])
            except Exception as e:
                print(f"[QueryUnderstanding] Image OCR embedding notice: {e}")

    # 3. Video Query
    elif category == "video" and (file_buffer or file_path):
        temp_dir = settings.resolved_upload_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_vid = str(temp_dir / f"query_vid_{uuid.uuid4()}.mp4")
        if file_buffer:
            with open(temp_vid, "wb") as f:
                f.write(file_buffer)
        else:
            temp_vid = file_path or ""

        temp_audio = str(temp_dir / f"query_aud_{uuid.uuid4()}.mp3")
        temp_frame = str(temp_dir / f"query_frame_{uuid.uuid4()}.jpg")
        try:
            # Extract 1 representative keyframe for visual search
            subprocess.run(
                ["ffmpeg", "-y", "-ss", "00:00:01", "-i", temp_vid, "-vframes", "1", "-q:v", "2", temp_frame],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
            )
            if Path(temp_frame).exists():
                try:
                    signals["imageEmbedding"] = get_image_embedding(temp_frame)
                except Exception as e:
                    print(f"[QueryUnderstanding] Video frame embedding notice: {e}")

            # Extract audio
            subprocess.run(
                ["ffmpeg", "-y", "-i", temp_vid, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", temp_audio],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
            )
            if Path(temp_audio).exists():
                aud_bytes = Path(temp_audio).read_bytes()
                signals["speechTranscript"] = await transcribe_audio_with_whisper(aud_bytes, "audio.mp3")
                if signals["speechTranscript"]:
                    entities = await extract_entities_with_llm(signals["speechTranscript"])
                    signals["extractedEntities"].extend(entities)
                    try:
                        signals["textEmbedding"] = get_text_embedding(signals["speechTranscript"][:1200])
                    except Exception as e:
                        print(f"[QueryUnderstanding] Video transcript embedding notice: {e}")
        except Exception as e:
            print(f"[QueryUnderstanding] Video processing notice: {e}")
        finally:
            for p in [temp_audio, temp_frame]:
                if Path(p).exists():
                    try: os.unlink(p)
                    except Exception: pass
            if file_buffer and Path(temp_vid).exists():
                try: os.unlink(temp_vid)
                except Exception: pass

        if not signals["derivedSearchKeywords"]:
            signals["derivedSearchKeywords"] = signals.get("speechTranscript", "")[:150] or file_name or "Video Query"

    # 4. Audio Query
    elif category == "audio" and (file_buffer or file_path):
        temp_dir = settings.resolved_upload_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_aud = str(temp_dir / f"query_aud_{uuid.uuid4()}.mp3")
        if file_buffer:
            with open(temp_aud, "wb") as f:
                f.write(file_buffer)
        else:
            temp_aud = file_path or ""

        try:
            if Path(temp_aud).exists():
                aud_bytes = Path(temp_aud).read_bytes()
                signals["speechTranscript"] = await transcribe_audio_with_whisper(aud_bytes, "audio.mp3")
                if signals["speechTranscript"]:
                    entities = await extract_entities_with_llm(signals["speechTranscript"])
                    signals["extractedEntities"].extend(entities)
                    signals["derivedSearchKeywords"] = signals["speechTranscript"][:150]
                    try:
                        signals["textEmbedding"] = get_text_embedding(signals["speechTranscript"][:1200])
                    except Exception as e:
                        print(f"[QueryUnderstanding] Audio transcript embedding notice: {e}")
        finally:
            if file_buffer and Path(temp_aud).exists():
                try: os.unlink(temp_aud)
                except Exception: pass

    # 5. Document Query
    elif category == "document" and (file_buffer or file_path):
        doc_text = ""
        ext = file_name.split(".")[-1].lower() if file_name and "." in file_name else "txt"
        try:
            if ext == "pdf":
                import pypdf, io
                stream = io.BytesIO(file_buffer) if file_buffer else open(file_path or "", "rb")
                reader = pypdf.PdfReader(stream)
                doc_text = "\n".join([page.extract_text() or "" for page in reader.pages])
            else:
                doc_text = file_buffer.decode("utf-8", errors="ignore") if file_buffer else Path(file_path or "").read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"[QueryUnderstanding] Document text extract notice: {e}")

        if doc_text:
            signals["documentText"] = doc_text
            entities = await extract_entities_with_llm(doc_text[:2500])
            signals["extractedEntities"].extend(entities)
            if not signals["derivedSearchKeywords"]:
                signals["derivedSearchKeywords"] = " ".join(entities[:4]) or doc_text[:120]
            try:
                signals["textEmbedding"] = get_text_embedding(doc_text[:1200])
                clip_doc_emb = get_multimodal_text_embedding(doc_text[:500])
                if clip_doc_emb is not None:
                    signals["clipTextEmbedding"] = clip_doc_emb
            except Exception as e:
                print(f"[QueryUnderstanding] Document embedding notice: {e}")

    return signals

async def generate_enhanced_internet_query(
    signals: Dict[str, Any],
    local_matches: List[Dict[str, Any]]
) -> Dict[str, Any]:
    top_local = local_matches[0] if local_matches else None
    discovered_entities = set(signals.get("extractedEntities", []))

    local_context_snippets = []
    for m in local_matches[:4]:
        cat = str(m.get("category", "")).upper()
        title = m.get("title", "")
        snippet = m.get("snippet", "")
        local_context_snippets.append(f"[{cat}] \"{title}\": {snippet}")
        clean_title = re.sub(r"[-_]", " ", Path(title).stem).strip()
        words = [w for w in clean_title.split() if len(w) >= 3]
        if len(words) >= 2:
            discovered_entities.add(clean_title)

    primary_query = signals.get("originalQueryText") or signals.get("derivedSearchKeywords") or "AI Research Intelligence"
    query_variants = [primary_query]
    context_summary = "Direct multimodal search execution across internet and indexed local knowledge base."

    # If local match exists, synthesize enriched query via Groq
    if top_local and settings.GROQ_API_KEY:
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
            import asyncio
            client = get_async_groq_client()
            completion = await asyncio.wait_for(
                client.chat.completions.create(
                    model=settings.GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": "You are an AI intelligence query specialist. Do NOT include <think> tags. Return ONLY a valid JSON object."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=250,
                    temperature=0.1
                ),
                timeout=10.0
            )
            raw = completion.choices[0].message.content or "{}"
            parsed = robust_json_loads(raw, default={})
            if parsed.get("primaryQuery"):
                primary_query = parsed["primaryQuery"]
            if parsed.get("queryVariants"):
                query_variants = parsed["queryVariants"]
            if parsed.get("discoveredEntities"):
                for e in parsed["discoveredEntities"]:
                    discovered_entities.add(e)
            if parsed.get("contextSummary"):
                context_summary = parsed["contextSummary"]
        except Exception as e:
            print(f"[QueryUnderstanding] LLM query enhancement notice: {e}")
            clean_title = re.sub(r"[-_]", " ", Path(top_local.get("title", "")).stem).strip()
            primary_query = clean_title

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
