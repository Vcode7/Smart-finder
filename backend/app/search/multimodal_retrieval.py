import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

# Number of FAISS candidates to retrieve for scoring.
# Decoupled from output limit so results ranked 10-50 are not silently dropped.
_FAISS_RECALL_K = 50
from app.database.session import db_all, db_get
from app.search.model_pipeline import (
    get_text_embedding,
    get_multimodal_text_embedding,
    get_image_embedding,
    detect_and_embed_faces,
)
from app.search.faiss_index import get_faiss_manager
from app.search.keyword_search import search_document_chunks, search_transcripts
from app.search.perceptual_hash import search_image_hashes
from app.search.constants import (
    DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
    STOPWORDS, COMPOSITE_MIN_SCORE, TEXT_MIN_SCORE, IMAGE_MIN_SCORE,
    FACE_MIN_SCORE, FACE_MATCH_THRESHOLD,
)

def extract_query_tokens(text: str) -> List[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return [w for w in cleaned.split() if len(w) >= 2 and w not in STOPWORDS]

def compute_title_score(query: str, filename: str) -> float:
    """
    Computes a continuous similarity score between query text/filename and a repository file.
    Never returns hardcoded or arbitrary flat constants.
    """
    clean_q = query.lower().strip()
    clean_fn = Path(filename.lower()).stem
    if not clean_q or not clean_fn:
        return 0.0

    # Exact or substring match on clean stem
    if clean_q == clean_fn or clean_q in clean_fn:
        return 0.95
    if clean_fn in clean_q and len(clean_fn) >= 4:
        return 0.90

    # Token overlap analysis
    q_tokens = set(extract_query_tokens(clean_q))
    fn_tokens = set(extract_query_tokens(clean_fn))
    if not q_tokens or not fn_tokens:
        return 0.0

    intersection = q_tokens.intersection(fn_tokens)
    if not intersection:
        return 0.0

    jaccard = len(intersection) / len(q_tokens.union(fn_tokens))
    coverage = len(intersection) / len(q_tokens)

    if len(intersection) == len(q_tokens):
        return round(0.70 + 0.25 * jaccard, 4)

    return round((coverage * 0.45) + (jaccard * 0.35), 4)

def resolve_parent_files(source_signals: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    CRITICAL REQUIREMENT: Return Complete Files.
    Resolves matched retrieval signals (embeddings, chunks, frames, faces)
    back to their canonical parent file in knowledge_sources, deduplicates by file ID,
    and formats complete file records with metadata and supporting timestamps.
    """
    documents: List[Dict[str, Any]] = []
    videos: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    audio: List[Dict[str, Any]] = []

    # Batch fetch all needed sources in ONE query (was N separate queries — audit #18)
    source_ids = list(source_signals.keys())
    if not source_ids:
        return {"documents": [], "videos": [], "images": [], "audio": []}
    placeholders = ",".join("?" * len(source_ids))
    rows = db_all(
        f"SELECT * FROM knowledge_sources WHERE id IN ({placeholders})",
        tuple(source_ids)
    )
    sources_by_id = {r["id"]: r for r in rows}

    for source_id, sig in source_signals.items():
        src = sources_by_id.get(source_id)
        if not src:
            continue

        ext = (src.get("file_type") or "").lower()
        if ext in DOCUMENT_EXTENSIONS:
            category = "document"
        elif ext in VIDEO_EXTENSIONS:
            category = "video"
        elif ext in IMAGE_EXTENSIONS:
            category = "image"
        elif ext in AUDIO_EXTENSIONS:
            category = "audio"
        else:
            category = "document"

        # Calculate composite score from all retrieval signals
        text_vec_scores = sig.get("text_vec_scores", [])
        image_vec_scores = sig.get("image_vec_scores", [])
        face_vec_scores = sig.get("face_vec_scores", [])
        phash_scores = sig.get("phash_scores", [])
        fts_scores = sig.get("fts_scores", [])
        title_score = sig.get("title_score", 0.0)

        max_text_vec = max(text_vec_scores, default=0.0)
        max_img_vec = max(image_vec_scores, default=0.0)
        max_face_vec = max(face_vec_scores, default=0.0)
        max_phash = max(phash_scores, default=0.0)

        # Per-source FTS score: best chunk score + small soft-max boost
        # when multiple strong chunks match (rewards broad textual coverage).
        if fts_scores:
            raw_max_fts = max(fts_scores)
            if len(fts_scores) > 1:
                # Soft boost: up to +0.05 proportional to how many extra chunks matched
                extra = min(len(fts_scores) - 1, 5)  # cap at 5 extra chunks
                boost = 0.01 * extra * (1.0 - raw_max_fts)  # shrinks as score approaches 1
                max_fts = min(0.99, raw_max_fts + boost)
            else:
                max_fts = raw_max_fts
        else:
            max_fts = 0.0

        # Baseline vector / semantic score
        # Only fold face score into vector_score when the query actually carries a face signal (#9)
        max_face_for_vec = max_face_vec if sig.get("is_face_query") else 0.0
        vector_score = max(max_text_vec, max_img_vec, max_face_for_vec)
        lexical_score = max(max_fts, title_score)

        if sig.get("is_exact_image_match") or max_phash >= 0.95:
            composite_score = max_phash if max_phash > 0.0 else 0.98
        elif sig.get("is_face_match") and max_face_vec > 0.0:
            composite_score = max_face_vec
        elif vector_score > 0.0 and lexical_score > 0.0:
            # Max-fusion with small synergy bonus.
            # A weighted average (0.70*vec + 0.30*lex) penalises documents that have
            # both strong signals — e.g. FAISS=0.50, FTS=0.71 only scored 0.563, worse
            # than a competitor with FTS=0.666 alone. Instead:
            #   base = max(vector, lexical)       — never punish a strong signal
            #   bonus = 0.10 * min(vec, lex) * gap_to_1  — small reward for agreement
            base = max(vector_score, lexical_score)
            bonus = 0.10 * min(vector_score, lexical_score) * (1.0 - base)
            composite_score = min(0.99, base + bonus)
        elif vector_score > 0.0:
            composite_score = vector_score
        elif lexical_score > 0.0:
            # No penalty — FTS is a real signal calibrated to [0, 1) by log-scale formula.
            composite_score = lexical_score
        elif max_phash > 0.0:
            composite_score = max_phash
        else:
            composite_score = 0.0

        # Filter results below composite minimum (constant, not inline magic number — audit #8)
        if composite_score < COMPOSITE_MIN_SCORE:
            continue

        # Clean snippet (never raw internal chunk representations)
        snippets = [s.strip() for s in sig.get("snippets", []) if s and len(s.strip()) > 10]
        primary_snippet = snippets[0] if snippets else f"Relevant file matching query criteria in {src['original_name']}."
        if sig.get("is_exact_image_match"):
            page_info = f"on Page {sig['exact_image_page']}" if sig.get("exact_image_page") else "in media content"
            primary_snippet = f"🎯 Exact visual image match {page_info}. " + primary_snippet
        elif max_phash >= 0.85:
            primary_snippet = "Visual match detected in document media. " + primary_snippet
        if len(primary_snippet) > 350:
            primary_snippet = primary_snippet[:350].rstrip() + "..."

        # Round timestamps to fixed precision before dedup to prevent float equality issues (#29)
        raw_ts = [round(t, 1) for t in sig.get("timestamps", [])]
        timestamps = sorted(list(set(raw_ts)))
        first_ts = timestamps[0] if timestamps else 0.0

        matching_frames = []
        for f in sig.get("frames", []):
            matching_frames.append({
                "id": f.get("id", f"frame-{f.get('timestamp', 0)}"),
                "frameNumber": f.get("frameNumber", 1),
                "sceneId": 1,
                "timestamp": f.get("timestamp", 0.0),
                "framePath": f.get("framePath", ""),
                "similarity": round(f.get("similarity", composite_score), 2),
                "isFaceMatch": f.get("isFaceMatch", False),
                "faceSimilarity": f.get("faceSimilarity"),
            })

        # Thumbnail path
        thumbnail_url = f"/api/knowledge/{src['id']}/file"
        if category == "document":
            thumbnail_url = f"/api/knowledge/{src['id']}/thumbnail"
        elif category == "video" and matching_frames and matching_frames[0].get("framePath"):
            thumbnail_url = f"/api/knowledge/{src['id']}/thumbnail"

        complete_file_item = {
            "id": f"src-{src['id']}",
            "sourceId": src["id"],
            "category": category,
            "title": src.get("original_name", ""),
            "originalName": src.get("original_name", ""),
            "fileType": src.get("file_type", ""),
            "fileSize": src.get("file_size", 0),
            "uploadDate": src.get("upload_date", ""),
            "relevanceScore": round(composite_score, 4),
            "snippet": primary_snippet,
            "pageCount": src.get("page_count"),
            "duration": src.get("duration_seconds"),
            "startTime": first_ts if category in ("video", "audio") else None,
            "endTime": (first_ts + 15.0) if category in ("video", "audio") else None,
            "matchingFrames": matching_frames if category == "video" and matching_frames else None,
            "primaryFrame": matching_frames[0] if category == "video" and matching_frames else None,
            "isFaceMatch": sig.get("is_face_match", False),
            "faceSimilarity": sig.get("face_similarity"),
            "thumbnail": thumbnail_url,
        }

        if category == "document":
            documents.append(complete_file_item)
        elif category == "video":
            videos.append(complete_file_item)
        elif category == "image":
            images.append(complete_file_item)
        elif category == "audio":
            audio.append(complete_file_item)

    documents.sort(key=lambda x: x["relevanceScore"], reverse=True)
    videos.sort(key=lambda x: x["relevanceScore"], reverse=True)
    images.sort(key=lambda x: x["relevanceScore"], reverse=True)
    audio.sort(key=lambda x: x["relevanceScore"], reverse=True)

    return {
        "documents": documents,
        "videos": videos,
        "images": images,
        "audio": audio,
    }

async def search_by_text(query_text: str, limit: int = 30) -> Dict[str, Any]:
    """
    Hybrid Multimodal Retrieval for Text Queries:
    1. SQLite FTS5 exact/keyword search across document chunks & transcripts
    2. FAISS text index vector search (Qwen3-Embedding-0.6B)
    3. FAISS image index vector search (Jina CLIP v2 multimodal text embedding)
    4. Exact title matching on knowledge_sources
    5. Canonical Parent File Resolution (returns complete files deduplicated by file ID)
    """
    clean_query = query_text.strip() if query_text else ""
    if not clean_query:
        return {"query": "", "queryType": "text", "documents": [], "videos": [], "images": [], "audio": [], "total": 0}

    source_signals: Dict[str, Dict[str, Any]] = {}

    def get_signal(source_id: str) -> Dict[str, Any]:
        if source_id not in source_signals:
            source_signals[source_id] = {
                "text_vec_scores": [],
                "image_vec_scores": [],
                "face_vec_scores": [],
                "fts_scores": [],
                "title_score": 0.0,
                "snippets": [],
                "timestamps": [],
                "frames": [],
                "is_face_match": False,
            }
        return source_signals[source_id]

    # 1. Filename Exact / Token Match — pre-filter with SQL LIKE before Python scoring
    # Avoids full table scan of knowledge_sources for title matching (audit #19)
    title_tokens = [w for w in re.sub(r"[^a-z0-9\s]", " ", clean_query.lower()).split() if len(w) >= 3]
    if title_tokens:
        like_clauses = " OR ".join(["original_name LIKE ?" for _ in title_tokens])
        candidates = db_all(
            f"SELECT id, original_name FROM knowledge_sources WHERE {like_clauses}",
            tuple(f"%{t}%" for t in title_tokens)
        )
    else:
        candidates = db_all("SELECT id, original_name FROM knowledge_sources")
    for s in candidates:
        t_score = compute_title_score(clean_query, s["original_name"])
        if t_score > 0.0:
            get_signal(s["id"])["title_score"] = t_score

    # 2. SQLite FTS5 Keyword Search (Preserves exact/keyword search!)
    fts_doc_matches = search_document_chunks(clean_query, limit=max(30, limit))
    for m in fts_doc_matches:
        sid = m["sourceId"]
        sig = get_signal(sid)
        sig["fts_scores"].append(float(m["score"]))
        if m.get("text"):
            sig["snippets"].append(m["text"])

    fts_tr_matches = search_transcripts(clean_query, limit=max(30, limit))
    for m in fts_tr_matches:
        sid = m["sourceId"]
        sig = get_signal(sid)
        sig["fts_scores"].append(float(m["score"]))
        if m.get("text"):
            sig["snippets"].append(m["text"])
        if m.get("startTime") is not None:
            sig["timestamps"].append(float(m["startTime"]))

    # 3. FAISS Vector Search: Text Space (Qwen3-Embedding-0.6B)
    # _FAISS_RECALL_K is decoupled from output limit — always retrieve 50 candidates
    # so documents ranked 11-50 in FAISS are not silently dropped before scoring.
    faiss_mgr = get_faiss_manager()
    query_text_vec = get_text_embedding(clean_query)
    if query_text_vec is not None:  # None-safe: skip FAISS if model unavailable (audit #1)
        text_matches = faiss_mgr.search_text(query_text_vec, top_k=_FAISS_RECALL_K, min_score=TEXT_MIN_SCORE)
        for m in text_matches:
            sid = m["source_id"]
            sig = get_signal(sid)
            sig["text_vec_scores"].append(m["score"])
            meta = m.get("metadata", {})
            if meta.get("preview"):
                sig["snippets"].append(meta["preview"])
            if meta.get("start") is not None:
                sig["timestamps"].append(float(meta["start"]))
            if meta.get("timestamp") is not None:
                sig["timestamps"].append(float(meta["timestamp"]))

    # 4. FAISS Vector Search: Image Space (Jina CLIP v2 Text Encoder)
    clip_text_vec = get_multimodal_text_embedding(clean_query)
    if clip_text_vec:  # None-safe (audit #1)
        image_matches = faiss_mgr.search_image(clip_text_vec, top_k=_FAISS_RECALL_K, min_score=IMAGE_MIN_SCORE)
        for m in image_matches:
            sid = m["source_id"]
            sig = get_signal(sid)
            sig["image_vec_scores"].append(m["score"])
            meta = m.get("metadata", {})
            ts = meta.get("timestamp")
            if ts is not None:
                sig["timestamps"].append(float(ts))
                sig["frames"].append({
                    "id": m["entity_id"],
                    "timestamp": float(ts),
                    "framePath": meta.get("frame_path", ""),
                    "similarity": m["score"],
                })

    # 5. Canonical Parent File Resolution & Deduplication
    categorized = resolve_parent_files(source_signals)
    total = sum(len(v) for v in categorized.values())

    return {
        "query": clean_query,
        "queryType": "text",
        "documents": categorized["documents"],
        "videos": categorized["videos"],
        "audio": categorized["audio"],
        "images": categorized["images"],
        "total": total,
    }

async def search_by_multimodal_signals(signals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Multimodal Retrieval given extracted signals (text query, uploaded image, face embeddings, OCR):
    Searches across FTS5, FAISS text index, FAISS image index, and FAISS face index,
    then resolves all matches back to parent files in knowledge_sources.
    """
    source_signals: Dict[str, Dict[str, Any]] = {}

    def get_signal(source_id: str) -> Dict[str, Any]:
        if source_id not in source_signals:
            source_signals[source_id] = {
                "text_vec_scores": [],
                "image_vec_scores": [],
                "face_vec_scores": [],
                "phash_scores": [],
                "fts_scores": [],
                "title_score": 0.0,
                "snippets": [],
                "timestamps": [],
                "frames": [],
                "is_face_match": False,
                "face_similarity": None,
                "is_exact_image_match": False,
                "exact_image_page": None,
                "exact_image_path": None,
            }
        return source_signals[source_id]

    faiss_mgr = get_faiss_manager()

    # 1. Perceptual Image Matching (pHash + dHash exact & near-duplicate matching)
    q_phash = signals.get("phash")
    q_dhash = signals.get("dhash")
    if q_phash or q_dhash:
        ph_matches = search_image_hashes(q_phash or "", q_dhash or "", max_hamming_distance=8)
        for pm in ph_matches:
            sid = pm["source_id"]
            sig = get_signal(sid)
            sig["phash_scores"].append(pm["similarity"])
            if pm.get("is_exact_match"):
                sig["is_exact_image_match"] = True
            if pm.get("page_num"):
                sig["exact_image_page"] = pm["page_num"]
            if pm.get("image_path"):
                sig["exact_image_path"] = pm["image_path"]

    # 2. Face-Based Retrieval — is_face_query flag set here for composite scoring (#9/#22)
    face_embeddings = signals.get("faceEmbeddings", [])
    is_face_query = signals.get("hasFace", False) and bool(face_embeddings)
    if is_face_query:
        for face_vec in face_embeddings:
            face_matches = faiss_mgr.search_face(face_vec, top_k=25, min_score=FACE_MIN_SCORE)
            for m in face_matches:
                sid = m["source_id"]
                sig = get_signal(sid)
                sig["face_vec_scores"].append(m["score"])
                sig["is_face_query"] = True  # signals face_score should be included in composite
                # Only set is_face_match if this specific match exceeds threshold (audit #22)
                if m["score"] >= FACE_MATCH_THRESHOLD:
                    sig["is_face_match"] = True
                    if sig["face_similarity"] is None or m["score"] > sig["face_similarity"]:
                        sig["face_similarity"] = round(m["score"], 3)

                meta = m.get("metadata", {})
                ts = meta.get("timestamp")
                if ts is not None:
                    sig["timestamps"].append(float(ts))
                    sig["frames"].append({
                        "id": m["entity_id"],
                        "timestamp": float(ts),
                        "framePath": meta.get("frame_path", ""),
                        "similarity": m["score"],
                        "isFaceMatch": True,
                        "faceSimilarity": m["score"],
                    })

    # 3. Image Vector Search (Jina CLIP v2 - 1024-dim visual space)
    clip_vec = signals.get("imageEmbedding")
    if clip_vec:
        img_matches = faiss_mgr.search_image(clip_vec, top_k=30, min_score=IMAGE_MIN_SCORE)
        for m in img_matches:
            sid = m["source_id"]
            sig = get_signal(sid)
            sig["image_vec_scores"].append(m["score"])
            meta = m.get("metadata", {})
            ts = meta.get("timestamp")
            if ts is not None:
                sig["timestamps"].append(float(ts))
                sig["frames"].append({
                    "id": m["entity_id"],
                    "timestamp": float(ts),
                    "framePath": meta.get("frame_path", ""),
                    "similarity": m["score"],
                })

    # C. Text Search (Query Text, OCR Text, Visual Description, Document Text)
    text_queries = []
    if signals.get("textQuery"):
        text_queries.append(str(signals["textQuery"]))
    elif signals.get("originalQueryText"):
        text_queries.append(str(signals["originalQueryText"]))
    elif signals.get("derivedSearchKeywords"):
        text_queries.append(str(signals["derivedSearchKeywords"]))

    if signals.get("documentText") and len(str(signals["documentText"]).strip()) > 10:
        text_queries.append(str(signals["documentText"]).strip()[:2000])
    if signals.get("ocrText") and len(str(signals["ocrText"]).strip()) > 4:
        text_queries.append(str(signals["ocrText"]).strip())
    if signals.get("speechTranscript") and len(str(signals["speechTranscript"]).strip()) > 4:
        text_queries.append(str(signals["speechTranscript"]).strip())

    combined_text = " ".join(text_queries).strip()

    # Filename title matching based on explicit user query or file title
    title_target = signals.get("textQuery") or signals.get("originalQueryText") or signals.get("fileName") or ""
    if title_target:
        all_sources = db_all("SELECT id, original_name FROM knowledge_sources")
        for s in all_sources:
            t_score = compute_title_score(title_target, s["original_name"])
            if t_score > 0.0:
                get_signal(s["id"])["title_score"] = t_score

    if combined_text:
        # FTS5 matches
        doc_matches = search_document_chunks(combined_text[:1000], limit=25)
        for m in doc_matches:
            sid = m["sourceId"]
            sig = get_signal(sid)
            sig["fts_scores"].append(float(m["score"]))
            if m.get("text"):
                sig["snippets"].append(m["text"])

        tr_matches = search_transcripts(combined_text[:1000], limit=25)
        for m in tr_matches:
            sid = m["sourceId"]
            sig = get_signal(sid)
            sig["fts_scores"].append(float(m["score"]))
            if m.get("text"):
                sig["snippets"].append(m["text"])
            if m.get("startTime") is not None:
                sig["timestamps"].append(float(m["startTime"]))

        # FAISS Text Vector search (Qwen3): Use precomputed embedding if available
        t_vec = signals.get("textEmbedding")
        if not t_vec:
            t_vec = get_text_embedding(combined_text)
        if t_vec is not None:  # None-safe (audit #1)
            txt_matches = faiss_mgr.search_text(t_vec, top_k=30, min_score=TEXT_MIN_SCORE)
            for m in txt_matches:
                sid = m["source_id"]
                sig = get_signal(sid)
                sig["text_vec_scores"].append(m["score"])
                meta = m.get("metadata", {})
                if meta.get("preview"):
                    sig["snippets"].append(meta["preview"])
                if meta.get("start") is not None:
                    sig["timestamps"].append(float(meta["start"]))

        # Jina CLIP text query to image index
        if not clip_vec:
            clip_t_vec = get_multimodal_text_embedding(combined_text)
            if clip_t_vec is not None:  # None-safe (audit #1)
                img_matches = faiss_mgr.search_image(clip_t_vec, top_k=25, min_score=IMAGE_MIN_SCORE)
                for m in img_matches:
                    sid = m["source_id"]
                    sig = get_signal(sid)
                    sig["image_vec_scores"].append(m["score"])
                    meta = m.get("metadata", {})
                    ts = meta.get("timestamp")
                    if ts is not None:
                        sig["timestamps"].append(float(ts))

    # D. Canonical Parent File Resolution & Deduplication
    categorized = resolve_parent_files(source_signals)
    total = sum(len(v) for v in categorized.values())

    return {
        "query": combined_text,
        "queryType": signals.get("queryType", "multimodal"),
        "documents": categorized["documents"],
        "videos": categorized["videos"],
        "audio": categorized["audio"],
        "images": categorized["images"],
        "total": total,
    }

async def search_by_image(
    image_input: Any,
    query_preview_url: Optional[str] = None
) -> Dict[str, Any]:
    """Helper for direct image search."""
    from app.search.query_understanding import understand_multimodal_query
    signals = await understand_multimodal_query({
        "fileBuffer": image_input if isinstance(image_input, bytes) else None,
        "filePath": image_input if isinstance(image_input, str) else None,
        "fileCategory": "image",
        "previewUrl": query_preview_url,
    })
    return await search_by_multimodal_signals(signals)
