from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

# Number of FAISS candidates to retrieve for scoring.
# Decoupled from output limit so results ranked 10-50 are not silently dropped.
_FAISS_RECALL_K = 50
from app.database.session import db_all
from app.search.model_pipeline import (
    get_text_query_embedding,
    get_multimodal_text_embedding,
)
from app.search.faiss_index import get_faiss_manager
from app.search.keyword_search import search_document_chunks, search_transcripts
from app.search.perceptual_hash import search_image_hashes
from app.search.constants import (
    DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
    COMPOSITE_MIN_SCORE, TEXT_MIN_SCORE, IMAGE_MIN_SCORE,
    FACE_MIN_SCORE, FACE_MATCH_THRESHOLD, tokenize,
)

# Scored evidence: (score, value). Plain values are accepted for backward compatibility.
Scored = Union[Tuple[float, Any], Any]


def extract_query_tokens(text: str) -> List[str]:
    return tokenize(text)


def _calibrate_face(score: float) -> float:
    """ArcFace cosine at/above the match threshold maps smoothly to [0.75, 0.98]."""
    if score < FACE_MATCH_THRESHOLD:
        return score
    return min(0.98, max(score, 0.75 + ((score - FACE_MATCH_THRESHOLD) / max(0.01, 0.90 - FACE_MATCH_THRESHOLD)) * 0.23))


def _calibrate_clip(score: float) -> float:
    """CLIP similarities in [0.35, 0.85] map to [0.65, 0.96] for visual media."""
    if score < 0.35:
        return score
    return min(0.96, max(score, 0.65 + ((score - 0.35) / 0.50) * 0.31))


def compute_title_score(query: str, filename: str) -> float:
    """
    Similarity between a query and a file name, on whole words only — a query
    like "ai" must not match "chairman". Returns 0.0 when nothing matches.
    """
    q_tokens = tokenize(query)
    fn_tokens = tokenize(Path(filename).stem)
    if not q_tokens or not fn_tokens:
        return 0.0

    q_set, fn_set = set(q_tokens), set(fn_tokens)
    intersection = q_set & fn_set
    if not intersection:
        return 0.0

    jaccard = len(intersection) / len(q_set | fn_set)
    coverage = len(intersection) / len(q_set)

    if q_set == fn_set:
        return 0.95
    if intersection == q_set:
        # Every query word appears in the name
        return round(0.70 + 0.25 * jaccard, 4)
    if intersection == fn_set and len(fn_set) >= 2:
        # The whole (multi-word) file name appears inside a longer query
        return 0.85
    return round((coverage * 0.45) + (jaccard * 0.35), 4)


def _title_candidates(query: str) -> List[Dict[str, Any]]:
    """Sources whose name contains at least one query word (SQL pre-filter, no full scan)."""
    tokens = [t for t in tokenize(query) if len(t) >= 3] or tokenize(query)
    if not tokens:
        return []
    tokens = tokens[:12]
    like_clauses = " OR ".join(["original_name LIKE ?" for _ in tokens])
    return db_all(
        f"SELECT id, original_name FROM knowledge_sources WHERE {like_clauses}",
        tuple(f"%{t}%" for t in tokens)
    )


def _best(entries: List[Scored]) -> Optional[Any]:
    """Value with the highest score from a list of (score, value) pairs or plain values."""
    best_val, best_score = None, float("-inf")
    for e in entries:
        if isinstance(e, tuple) and len(e) == 2:
            score, val = e
        else:
            score, val = 0.0, e
        if val is None:
            continue
        if score > best_score:
            best_score, best_val = score, val
    return best_val


def _values(entries: List[Scored]) -> List[Any]:
    return [e[1] if isinstance(e, tuple) and len(e) == 2 else e for e in entries]


def resolve_parent_files(source_signals: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Resolves matched retrieval signals (embeddings, chunks, frames, faces) back to their
    canonical parent file in knowledge_sources, deduplicates by file ID, and formats
    complete file records with metadata and supporting timestamps.
    """
    documents: List[Dict[str, Any]] = []
    videos: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    audio: List[Dict[str, Any]] = []

    source_ids = list(source_signals.keys())
    if not source_ids:
        return {"documents": [], "videos": [], "images": [], "audio": []}
    clean_ids = [str(sid).removeprefix("src-") for sid in source_ids]
    all_query_ids = list(set([str(sid) for sid in source_ids] + clean_ids))
    placeholders = ",".join("?" * len(all_query_ids))
    rows = db_all(
        f"SELECT * FROM knowledge_sources WHERE id IN ({placeholders})",
        tuple(all_query_ids)
    )
    sources_by_id = {}
    for r in rows:
        rid = str(r["id"])
        sources_by_id[rid] = r
        sources_by_id[f"src-{rid}"] = r

    for source_id, sig in source_signals.items():
        src = sources_by_id.get(str(source_id)) or sources_by_id.get(str(source_id).removeprefix("src-"))
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

        text_vec_scores = sig.get("text_vec_scores", [])
        image_vec_scores = sig.get("image_vec_scores", [])
        face_vec_scores = sig.get("face_vec_scores", [])
        phash_scores = sig.get("phash_scores", [])
        fts_scores = sig.get("fts_scores", [])
        title_score = sig.get("title_score", 0.0)
        is_face_query = bool(sig.get("is_face_query"))

        max_text_vec = max(text_vec_scores, default=0.0)
        max_img_vec = max(image_vec_scores, default=0.0)
        max_face_vec = max(face_vec_scores, default=0.0)
        max_phash = max(phash_scores, default=0.0)

        # Per-source FTS score: best chunk score + small boost when several chunks match
        if fts_scores:
            raw_max_fts = max(fts_scores)
            if len(fts_scores) > 1:
                extra = min(len(fts_scores) - 1, 5)
                boost = 0.01 * extra * (1.0 - raw_max_fts)
                max_fts = min(0.99, raw_max_fts + boost)
            else:
                max_fts = raw_max_fts
        else:
            max_fts = 0.0

        # Face similarity only counts when the query itself carries a face
        max_face_for_vec = max_face_vec if is_face_query else 0.0
        vector_score = max(max_text_vec, max_img_vec, max_face_for_vec)
        lexical_score = max(max_fts, title_score)

        is_face_match = is_face_query and bool(sig.get("is_face_match")) and max_face_vec >= FACE_MATCH_THRESHOLD
        calibrated_face = _calibrate_face(max_face_vec) if is_face_query else 0.0
        calibrated_img = _calibrate_clip(max_img_vec)

        if sig.get("is_exact_image_match") or max_phash >= 0.95:
            composite_score = max_phash if max_phash > 0.0 else 0.98
        elif is_face_match:
            composite_score = calibrated_face
        elif category in ("video", "image") and (calibrated_img >= 0.60 or calibrated_face >= 0.60):
            best_visual = max(calibrated_img, calibrated_face)
            if lexical_score > 0.0:
                composite_score = min(0.99, best_visual + 0.05 * lexical_score * (1.0 - best_visual))
            else:
                composite_score = best_visual
        elif vector_score > 0.0 and lexical_score > 0.0:
            # Max-fusion with a small agreement bonus; a weighted average would punish
            # sources that are strong on both signals.
            base = max(vector_score, lexical_score)
            bonus = 0.10 * min(vector_score, lexical_score) * (1.0 - base)
            composite_score = min(0.99, base + bonus)
        elif vector_score > 0.0:
            composite_score = vector_score
        elif lexical_score > 0.0:
            composite_score = lexical_score
        elif max_phash > 0.0:
            composite_score = max_phash
        else:
            composite_score = 0.0

        if composite_score < COMPOSITE_MIN_SCORE:
            continue

        # Snippet from the strongest matching passage
        snippet_entries = [
            e for e in sig.get("snippets", [])
            if (e[1] if isinstance(e, tuple) else e) and len(str(e[1] if isinstance(e, tuple) else e).strip()) > 10
        ]
        best_snippet = _best(snippet_entries)
        primary_snippet = str(best_snippet).strip() if best_snippet else f"Relevant file matching query criteria in {src['original_name']}."
        if sig.get("is_exact_image_match"):
            page_info = f"on Page {sig['exact_image_page']}" if sig.get("exact_image_page") else "in media content"
            primary_snippet = f"🎯 Exact visual image match {page_info}. " + primary_snippet
        elif max_phash >= 0.85:
            primary_snippet = "Visual match detected in document media. " + primary_snippet
        if len(primary_snippet) > 350:
            primary_snippet = primary_snippet[:350].rstrip() + "..."

        # Jump target: the timestamp of the strongest timed match (not the earliest)
        ts_entries = sig.get("timestamps", [])
        best_ts = _best(ts_entries)
        if best_ts is None:
            all_ts = sorted(round(float(t), 1) for t in _values(ts_entries) if t is not None)
            best_ts = all_ts[0] if all_ts else 0.0
        best_ts = round(float(best_ts), 1)

        matching_frames = []
        for f in sig.get("frames", []):
            f_sim = f.get("similarity", composite_score)
            if f.get("isFaceMatch"):
                f_sim = _calibrate_face(f_sim)
            else:
                f_sim = _calibrate_clip(f_sim)
            matching_frames.append({
                "id": f.get("id", f"frame-{f.get('timestamp', 0)}"),
                "frameNumber": f.get("frameNumber", 1),
                "sceneId": 1,
                "timestamp": f.get("timestamp", 0.0),
                "framePath": f.get("framePath", ""),
                "similarity": round(f_sim, 2),
                "isFaceMatch": f.get("isFaceMatch", False),
                "faceSimilarity": f.get("faceSimilarity"),
            })
        matching_frames.sort(key=lambda x: x["similarity"], reverse=True)

        thumbnail_url = f"/api/knowledge/{src['id']}/file"
        if category in ("document", "video", "audio"):
            thumbnail_url = f"/api/knowledge/{src['id']}/thumbnail"

        complete_file_item = {
            "id": f"src-{src['id']}",
            "sourceId": str(src["id"]),
            "category": category,
            "title": src.get("original_name") or "Untitled Document",
            "originalName": src.get("original_name") or "Untitled Document",
            "fileType": src.get("file_type", ""),
            "fileSize": src.get("file_size", 0),
            "uploadDate": src.get("upload_date", ""),
            "relevanceScore": round(composite_score, 4),
            "snippet": primary_snippet,
            "pageCount": src.get("page_count"),
            "duration": src.get("duration_seconds"),
            "startTime": best_ts if category in ("video", "audio") else None,
            "endTime": (best_ts + 15.0) if category in ("video", "audio") else None,
            "matchingFrames": matching_frames if category == "video" and matching_frames else None,
            "primaryFrame": matching_frames[0] if category == "video" and matching_frames else None,
            "isFaceMatch": is_face_match,
            "faceSimilarity": sig.get("face_similarity") if is_face_match else None,
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

    for bucket in (documents, videos, images, audio):
        bucket.sort(key=lambda x: x["relevanceScore"], reverse=True)

    return {
        "documents": documents,
        "videos": videos,
        "images": images,
        "audio": audio,
    }


def _new_signal() -> Dict[str, Any]:
    return {
        "text_vec_scores": [],
        "image_vec_scores": [],
        "face_vec_scores": [],
        "phash_scores": [],
        "fts_scores": [],
        "title_score": 0.0,
        "snippets": [],
        "timestamps": [],
        "frames": [],
        "is_face_query": False,
        "is_face_match": False,
        "face_similarity": None,
        "is_exact_image_match": False,
        "exact_image_page": None,
        "exact_image_path": None,
    }


def _add_text_signals(
    get_signal,
    query: str,
    query_vec: Optional[List[float]],
    fts_limit: int,
    vec_k: int,
) -> None:
    """Keyword (FTS5) + semantic (Qwen3) matches for one textual query signal."""
    faiss_mgr = get_faiss_manager()
    fts_query = query[:1000]
    for m in search_document_chunks(fts_query, limit=fts_limit):
        sig = get_signal(m["sourceId"])
        score = float(m["score"])
        sig["fts_scores"].append(score)
        if m.get("text"):
            sig["snippets"].append((score, m["text"]))

    for m in search_transcripts(fts_query, limit=fts_limit):
        sig = get_signal(m["sourceId"])
        score = float(m["score"])
        sig["fts_scores"].append(score)
        if m.get("text"):
            sig["snippets"].append((score, m["text"]))
        if m.get("startTime") is not None:
            sig["timestamps"].append((score, float(m["startTime"])))

    if query_vec is None:
        query_vec = get_text_query_embedding(query)
    if query_vec is None:  # model unavailable — skip semantic search
        return
    for m in faiss_mgr.search_text(query_vec, top_k=vec_k, min_score=TEXT_MIN_SCORE):
        sig = get_signal(m["source_id"])
        score = float(m["score"])
        sig["text_vec_scores"].append(score)
        meta = m.get("metadata", {})
        if meta.get("preview"):
            sig["snippets"].append((score, meta["preview"]))
        for key in ("start", "timestamp"):
            if meta.get(key) is not None:
                sig["timestamps"].append((score, float(meta[key])))


def _add_clip_image_signals(get_signal, clip_vec: Optional[List[float]], top_k: int) -> None:
    if not clip_vec:
        return
    for m in get_faiss_manager().search_image(clip_vec, top_k=top_k, min_score=IMAGE_MIN_SCORE):
        sig = get_signal(m["source_id"])
        score = float(m["score"])
        sig["image_vec_scores"].append(score)
        meta = m.get("metadata", {})
        ts = meta.get("timestamp")
        if ts is not None:
            sig["timestamps"].append((score, float(ts)))
            sig["frames"].append({
                "id": m["entity_id"],
                "timestamp": float(ts),
                "framePath": meta.get("frame_path", ""),
                "similarity": score,
            })


def _apply_title_scores(get_signal, query: str) -> None:
    for s in _title_candidates(query):
        t_score = compute_title_score(query, s["original_name"])
        if t_score > 0.0:
            sig = get_signal(s["id"])
            sig["title_score"] = max(sig["title_score"], t_score)


def search_by_text(query_text: str, limit: int = 30) -> Dict[str, Any]:
    """
    Hybrid retrieval for a text query (blocking — call from a threadpool):
    1. SQLite FTS5 keyword search across document chunks & transcripts
    2. FAISS text index (Qwen3-Embedding-0.6B, query instruction prompt)
    3. FAISS image index (Qwen3-VL-Embedding text query, retrieval instruction)
    4. Whole-word title matching
    5. Parent-file resolution (complete files, deduplicated by file ID)
    """
    clean_query = query_text.strip() if query_text else ""
    if not clean_query:
        return {"query": "", "queryType": "text", "documents": [], "videos": [], "images": [], "audio": [], "total": 0}

    source_signals: Dict[str, Dict[str, Any]] = {}

    def get_signal(source_id: str) -> Dict[str, Any]:
        if source_id not in source_signals:
            source_signals[source_id] = _new_signal()
        return source_signals[source_id]

    _apply_title_scores(get_signal, clean_query)
    _add_text_signals(get_signal, clean_query, None, fts_limit=max(30, limit), vec_k=_FAISS_RECALL_K)
    _add_clip_image_signals(get_signal, get_multimodal_text_embedding(clean_query), top_k=_FAISS_RECALL_K)

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


def search_by_multimodal_signals(signals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieval from extracted query signals (blocking — call from a threadpool).

    Every input is searched on its own and contributes evidence to the same
    per-file signals: the typed text, OCR text, speech transcript and document
    text each get their own keyword + semantic search (concatenating them, or
    letting one overwrite the other's embedding, loses the user's intent).
    """
    source_signals: Dict[str, Dict[str, Any]] = {}

    def get_signal(source_id: str) -> Dict[str, Any]:
        if source_id not in source_signals:
            source_signals[source_id] = _new_signal()
        return source_signals[source_id]

    faiss_mgr = get_faiss_manager()

    # 1. Perceptual image matching (pHash + dHash exact & near-duplicate)
    q_phash = signals.get("phash")
    q_dhash = signals.get("dhash")
    if q_phash or q_dhash:
        for pm in search_image_hashes(q_phash or "", q_dhash or "", max_hamming_distance=8):
            sig = get_signal(pm["source_id"])
            sig["phash_scores"].append(pm["similarity"])
            if pm.get("is_exact_match"):
                sig["is_exact_image_match"] = True
            if pm.get("page_num"):
                sig["exact_image_page"] = pm["page_num"]
            if pm.get("image_path"):
                sig["exact_image_path"] = pm["image_path"]

    # 2. Face-based retrieval
    face_embeddings = signals.get("faceEmbeddings", [])
    is_face_query = bool(signals.get("hasFace", False) and face_embeddings)
    if is_face_query:
        for face_vec in face_embeddings:
            for m in faiss_mgr.search_face(face_vec, top_k=25, min_score=FACE_MIN_SCORE):
                sig = get_signal(m["source_id"])
                score = float(m["score"])
                sig["face_vec_scores"].append(score)
                sig["is_face_query"] = True
                if score >= FACE_MATCH_THRESHOLD:
                    sig["is_face_match"] = True
                    cal = round(_calibrate_face(score), 3)
                    if sig["face_similarity"] is None or cal > sig["face_similarity"]:
                        sig["face_similarity"] = cal

                meta = m.get("metadata", {})
                ts = meta.get("timestamp")
                # Only video faces carry a real timestamp (document faces store a page number)
                if ts is not None and meta.get("type") == "video_face":
                    sig["timestamps"].append((score, float(ts)))
                    sig["frames"].append({
                        "id": m["entity_id"],
                        "timestamp": float(ts),
                        "framePath": meta.get("frame_path", ""),
                        "similarity": score,
                        "isFaceMatch": score >= FACE_MATCH_THRESHOLD,
                        "faceSimilarity": score,
                    })

    # 3. Image → image (Qwen3-VL-Embedding space)
    clip_vec = signals.get("imageEmbedding")
    _add_clip_image_signals(get_signal, clip_vec, top_k=30)

    # 4. Textual signals, each searched separately
    is_visual_query = signals.get("queryType") in ("image", "clipping")
    user_text = str(signals.get("textQuery") or signals.get("originalQueryText") or "").strip()

    text_signals: List[Tuple[str, Optional[List[float]]]] = []
    if user_text:
        text_signals.append((user_text, signals.get("textEmbedding")))
    elif not is_visual_query and signals.get("derivedSearchKeywords"):
        kw = str(signals["derivedSearchKeywords"]).strip()
        if kw and kw not in ("Image Visual Search", "Video Query", "Audio Query"):
            text_signals.append((kw, None))
    if signals.get("documentText") and len(str(signals["documentText"]).strip()) > 10:
        text_signals.append((str(signals["documentText"]).strip()[:2000], signals.get("documentEmbedding")))
    if signals.get("ocrText") and len(str(signals["ocrText"]).strip()) > 15:
        text_signals.append((str(signals["ocrText"]).strip(), signals.get("ocrEmbedding")))
    if signals.get("speechTranscript") and len(str(signals["speechTranscript"]).strip()) > 4:
        text_signals.append((str(signals["speechTranscript"]).strip(), signals.get("transcriptEmbedding")))

    for query, vec in text_signals:
        _add_text_signals(get_signal, query, vec, fts_limit=25, vec_k=30)

    # 5. Text → image in CLIP space for the typed text — also when an image is attached
    #    ("photos like this at the beach" needs both the image and the words)
    clip_text_source = user_text or (text_signals[0][0] if text_signals and not clip_vec else "")
    if clip_text_source:
        clip_t_vec = signals.get("clipTextEmbedding") if user_text else None
        if clip_t_vec is None:
            clip_t_vec = get_multimodal_text_embedding(clip_text_source[:500])
        _add_clip_image_signals(get_signal, clip_t_vec, top_k=25)

    # 6. File-name matching on the typed text (or the uploaded file's name)
    title_target = user_text
    if not title_target and not is_visual_query:
        title_target = signals.get("fileName") or ""
    if title_target:
        _apply_title_scores(get_signal, title_target)

    categorized = resolve_parent_files(source_signals)
    total = sum(len(v) for v in categorized.values())
    combined_query = " ".join(q for q, _ in text_signals).strip()
    return {
        "query": combined_query,
        "queryType": signals.get("queryType", "multimodal"),
        "documents": categorized["documents"],
        "videos": categorized["videos"],
        "audio": categorized["audio"],
        "images": categorized["images"],
        "total": total,
    }
