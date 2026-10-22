import uuid
import json
import datetime
from pathlib import PurePosixPath
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.database.session import db_get, db_all, db_run, get_db_context
from app.api.deps import require_auth
from app.core.access import can_access_library, can_access_source
from app.schemas.chat import ChatCreate, ChatUpdate, MessageCreate
from app.search.constants import tokenize

router = APIRouter(prefix="/chats", tags=["chats"])

CONTEXT_TYPES = ("document", "video", "image", "audio", "web")
HISTORY_MESSAGES = 8          # most recent turns sent to the LLM
CONTEXT_ITEM_CHARS = 1800     # expanded text per context item
CONTEXT_TOTAL_CHARS = 9000    # all context items together

def iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _chat_row(chat: Dict[str, Any]) -> Dict[str, Any]:
    """Chat row with camelCase aliases for the fields the frontend reads."""
    out = dict(chat)
    out["searchMode"] = chat.get("search_mode")
    out["createdAt"] = chat.get("created_at")
    out["updatedAt"] = chat.get("updated_at")
    return out


def _context_type(raw: Any) -> str:
    ctype = str(raw or "document")
    return ctype if ctype in CONTEXT_TYPES else "document"


def _context_fields(it: Dict[str, Any], fallback_id: str) -> tuple:
    """(type, ref_id, score, snippet, metadata_json) of a client-sent context item."""
    ctype = _context_type(it.get("type"))
    ref_id = str(it.get("refId") or it.get("sourceId") or it.get("id") or fallback_id)
    meta = it.get("metadata")
    meta = dict(meta) if isinstance(meta, dict) else {}
    if "title" not in meta and it.get("title"):
        meta["title"] = it.get("title")
    try:
        score = float(it.get("relevanceScore"))
    except (TypeError, ValueError):
        score = 0.8
    snippet = it.get("snippet")
    return ctype, ref_id, score, snippet if isinstance(snippet, str) else "", json.dumps(meta)


def _pick_passages(rows: List[Dict[str, Any]], question: str) -> str:
    """The passages sharing most words with the question, in document order on ties."""
    q_tokens = set(tokenize(question))

    def overlap(text: str) -> int:
        return len(q_tokens & set(tokenize(text))) if q_tokens else 0

    ranked = sorted(enumerate(rows), key=lambda ir: (-overlap(ir[1]["text"]), ir[0]))
    picked, used = [], 0
    for _, r in ranked[:6]:
        text = (r["text"] or "").strip()
        if used + len(text) > CONTEXT_ITEM_CHARS and picked:
            break
        page = f"(page {r['page']}) " if r.get("page") else ""
        picked.append(page + text)
        used += len(text)
    return "\n".join(picked)[:CONTEXT_ITEM_CHARS]


def _expand_library_context(source_id: str, start: Any, question: str) -> Optional[str]:
    """Context from a folder library; None when the source isn't in one."""
    from app.library.manager import get_library_manager
    found = get_library_manager().find_source(source_id)
    if not found:
        return None
    lib, src = found
    if start is not None:
        try:
            t = float(start)
            segs = lib.db.all(
                "SELECT text FROM transcript_segments WHERE source_id = ? AND ts_end >= ? AND ts_start <= ? "
                "ORDER BY ts_start", (src["id"], max(0.0, t - 30.0), t + 90.0))
            if segs:
                return " ".join(s["text"] for s in segs)[:CONTEXT_ITEM_CHARS]
        except (TypeError, ValueError):
            pass
    rows = lib.db.all(
        "SELECT text, page FROM chunks WHERE source_id = ? AND kind != 'title' ORDER BY ord LIMIT 400", (src["id"],))
    return _pick_passages(rows, question) if rows else ""


def _source_location(ref_id: str, meta: Dict[str, Any], user: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """'<library> › <folder>' of a local item (folder names often say the event or place)."""
    from app.library.manager import get_library_manager
    source_id = str(meta.get("sourceId") or ref_id or "").removeprefix("src-")
    found = get_library_manager().find_source(source_id) if source_id else None
    if found and user is not None and not can_access_library(user, found[0].id):
        return None
    if found:
        lib, src = found
        library, rel = lib.name, src["rel_path"]
    elif meta.get("relPath"):
        library, rel = meta.get("libraryName") or "", str(meta["relPath"])
    else:
        return None
    folder = str(PurePosixPath(rel.replace("\\", "/")).parent)
    folder = "" if folder == "." else folder
    if not folder:
        return f"{library} (top level)" if library else None
    return f"{library} › {folder}" if library else folder


def _expand_local_context(ref_id: str, meta: Dict[str, Any], question: str,
                          user: Optional[Dict[str, Any]] = None) -> str:
    """
    Fuller text for a local knowledge-base item: the source's passages that best match
    the question (documents/images) or the transcript window around the matched time
    (audio/video). Returns "" for internet items, unknown sources, or sources that
    are not shared with `user`.
    """
    source_id = str(meta.get("sourceId") or ref_id or "").removeprefix("src-")
    if not source_id:
        return ""
    if user is not None and not can_access_source(user, source_id):
        return ""
    start = meta.get("startTime", meta.get("timestamp"))
    library_text = _expand_library_context(source_id, start, question)
    if library_text is not None:
        return library_text
    if not db_get("SELECT 1 FROM knowledge_sources WHERE id = ?", (source_id,)):
        return ""

    transcripts = []
    if start is not None:
        try:
            start_f = float(start)
            transcripts = db_all(
                """SELECT text FROM video_transcripts
                   WHERE source_id = ? AND end_time >= ? AND start_time <= ?
                   ORDER BY start_time ASC""",
                (source_id, max(0.0, start_f - 30.0), start_f + 90.0)
            )
        except (TypeError, ValueError):
            transcripts = []
    if transcripts:
        return " ".join(t["text"] for t in transcripts)[:CONTEXT_ITEM_CHARS]

    q_tokens = set(tokenize(question))
    rows = db_all(
        "SELECT chunk_text, page_num FROM document_chunks WHERE source_id = ? ORDER BY chunk_order ASC LIMIT 400",
        (source_id,)
    )
    if not rows:
        rows = [{"chunk_text": r["text"], "page_num": None} for r in db_all(
            "SELECT text FROM video_transcripts WHERE source_id = ? ORDER BY start_time ASC LIMIT 400", (source_id,)
        )]
    if not rows:
        return ""

    def overlap(text: str) -> int:
        return len(q_tokens & set(tokenize(text))) if q_tokens else 0

    ranked = sorted(enumerate(rows), key=lambda ir: (-overlap(ir[1]["chunk_text"]), ir[0]))
    picked, used = [], 0
    for _, r in ranked[:6]:
        text = r["chunk_text"].strip()
        if used + len(text) > CONTEXT_ITEM_CHARS and picked:
            break
        page = f"(page {r['page_num']}) " if r.get("page_num") else ""
        picked.append(page + text)
        used += len(text)
    return "\n".join(picked)[:CONTEXT_ITEM_CHARS]

@router.get("")
async def list_chats(user: Dict[str, Any] = Depends(require_auth)):
    chats = db_all(
        "SELECT id, title, search_mode, created_at, updated_at FROM chats WHERE user_id = ? ORDER BY updated_at DESC",
        (user["id"],)
    )
    return {"chats": [_chat_row(c) for c in chats]}

@router.post("")
async def create_chat(req: ChatCreate, user: Dict[str, Any] = Depends(require_auth)):
    chat_id = str(uuid.uuid4())
    now = iso_now()
    db_run(
        "INSERT INTO chats (id, user_id, title, search_mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, user["id"], req.title or "New Chat", req.searchMode or "internet", now, now)
    )
    return {
        "chat": _chat_row({
            "id": chat_id,
            "user_id": user["id"],
            "title": req.title or "New Chat",
            "search_mode": req.searchMode or "internet",
            "created_at": now,
            "updated_at": now,
        })
    }

@router.get("/{chat_id}")
async def get_chat(chat_id: str, user: Dict[str, Any] = Depends(require_auth)):
    chat = db_get("SELECT * FROM chats WHERE id = ? AND user_id = ?", (chat_id, user["id"]))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = db_all(
        "SELECT id, role, content, citations_json, created_at FROM chat_messages WHERE chat_id = ? ORDER BY created_at ASC",
        (chat_id,)
    )

    context_rows = db_all(
        "SELECT id, context_type, context_ref_id, relevance_score, snippet, metadata_json, added_at FROM chat_context WHERE chat_id = ?",
        (chat_id,)
    )
    context_items = []
    for cr in context_rows:
        try:
            meta = json.loads(cr.get("metadata_json") or "{}")
        except Exception:
            meta = {}
        context_items.append({
            "id": cr["id"],
            "type": cr["context_type"],
            "refId": cr["context_ref_id"],
            "title": meta.get("title") or meta.get("sourceName") or "Source Document",
            "snippet": cr["snippet"],
            "relevanceScore": cr["relevance_score"],
            "metadata": meta,
        })

    for m in messages:
        try:
            m["citations"] = json.loads(m.get("citations_json") or "[]")
        except Exception:
            m["citations"] = []
        m["createdAt"] = m.get("created_at")

    return {
        "chat": _chat_row(chat),
        "messages": messages,
        "contextItems": context_items,
    }

@router.put("/{chat_id}/context")
async def update_chat_context(chat_id: str, req: Dict[str, Any], user: Dict[str, Any] = Depends(require_auth)):
    chat = db_get("SELECT id FROM chats WHERE id = ? AND user_id = ?", (chat_id, user["id"]))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    items = req.get("contextItems") or []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="contextItems must be a list")
    now = iso_now()
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_context WHERE chat_id = ?", (chat_id,))
        for it in items:
            if not isinstance(it, dict):
                continue
            ctx_id = str(uuid.uuid4())
            ctype, ref_id, score, snippet, meta_json = _context_fields(it, ctx_id)
            cursor.execute(
                "INSERT INTO chat_context (id, chat_id, context_type, context_ref_id, relevance_score, snippet, metadata_json, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ctx_id, chat_id, ctype, ref_id, score, snippet, meta_json, now)
            )
        cursor.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
        conn.commit()

    return {"success": True, "count": len(items)}

@router.delete("/{chat_id}/context/{context_id}")
async def delete_chat_context_item(chat_id: str, context_id: str, user: Dict[str, Any] = Depends(require_auth)):
    chat = db_get("SELECT id FROM chats WHERE id = ? AND user_id = ?", (chat_id, user["id"]))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    db_run("DELETE FROM chat_context WHERE chat_id = ? AND (id = ? OR context_ref_id = ?)", (chat_id, context_id, context_id))
    return {"success": True, "deleted": context_id}

@router.patch("/{chat_id}")
async def update_chat(chat_id: str, req: ChatUpdate, user: Dict[str, Any] = Depends(require_auth)):
    chat = db_get("SELECT id FROM chats WHERE id = ? AND user_id = ?", (chat_id, user["id"]))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    now = iso_now()
    db_run(
        "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
        (title, now, chat_id)
    )
    return {"success": True, "title": title}

@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, user: Dict[str, Any] = Depends(require_auth)):
    chat = db_get("SELECT id FROM chats WHERE id = ? AND user_id = ?", (chat_id, user["id"]))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
        cursor.execute("DELETE FROM chat_context WHERE chat_id = ?", (chat_id,))
        cursor.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        conn.commit()

    return {"success": True, "deleted": chat_id}

@router.post("/{chat_id}/messages")
async def send_message(chat_id: str, req: MessageCreate, user: Dict[str, Any] = Depends(require_auth)):
    chat = db_get("SELECT * FROM chats WHERE id = ? AND user_id = ?", (chat_id, user["id"]))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    msg_text = (req.message or "").strip()
    if not msg_text:
        if req.contextItems:
            msg_text = "Synthesize the provided research context and summarize key findings."
        else:
            raise HTTPException(status_code=400, detail="Message cannot be empty")

    now = iso_now()
    user_msg_id = str(uuid.uuid4())
    db_run(
        "INSERT INTO chat_messages (id, chat_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
        (user_msg_id, chat_id, msg_text, now)
    )

    # Store any new context items attached to chat
    if req.contextItems:
        for it in req.contextItems:
            ctx_id = str(uuid.uuid4())
            ctype, ref_id, score, snippet, meta_json = _context_fields(it, ctx_id)

            # avoid duplicate insertions if ref_id already exists in this chat's context
            existing = db_get(
                "SELECT id FROM chat_context WHERE chat_id = ? AND context_ref_id = ?",
                (chat_id, ref_id)
            )
            if not existing:
                try:
                    db_run(
                        "INSERT INTO chat_context (id, chat_id, context_type, context_ref_id, relevance_score, snippet, metadata_json, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (ctx_id, chat_id, ctype, ref_id, score, snippet, meta_json, now)
                    )
                except Exception:
                    pass

    # Build conversation context: the most recent turns, newest last
    recent_messages = list(reversed(db_all(
        "SELECT role, content FROM chat_messages WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
        (chat_id, HISTORY_MESSAGES)
    )))
    context_rows = db_all(
        "SELECT context_type, context_ref_id, snippet, metadata_json, relevance_score FROM chat_context WHERE chat_id = ? ORDER BY relevance_score DESC, added_at DESC",
        (chat_id,)
    )

    def _build_context():
        snippets = []
        cites = []
        attached = False
        has_local = False
        for idx, cr in enumerate(context_rows[:12]):
            try:
                m = json.loads(cr.get("metadata_json") or "{}")
            except Exception:
                m = {}
            title = m.get("title") or m.get("sourceName") or f"Source {idx + 1}"
            url = m.get("url")
            is_user_att = bool(m.get("isUserAttachment") or "[Attached" in title)
            attached = attached or is_user_att

            raw_snip = (cr.get("snippet") or "").strip()
            if not raw_snip and m.get("extractedSnippet"):
                raw_snip = str(m.get("extractedSnippet")).strip()
            expanded = "" if is_user_att else _expand_local_context(cr.get("context_ref_id") or "", m, msg_text, user)
            body = expanded or raw_snip
            limit = 1500 if is_user_att else CONTEXT_ITEM_CHARS
            body = (body[:limit] + "...") if len(body) > limit else body
            location = None if is_user_att or url else _source_location(cr.get("context_ref_id") or "", m, user)
            has_local = has_local or location is not None

            prefix = "USER ATTACHED FILE" if is_user_att else cr["context_type"].upper()
            where = f" — folder: {location}" if location else ""
            entry = f"[{prefix}] {title}{where}:\n{body}"
            if is_user_att:
                snippets.insert(0, entry)
            else:
                snippets.append(entry)
            cite = {"title": title, "url": url, "type": cr["context_type"],
                    "sourceId": m.get("sourceId") or cr.get("context_ref_id")}
            if location:
                cite["folder"] = location
            cites.append(cite)
        return snippets, cites, attached, has_local

    context_snippets, citations, has_attached_file, has_local_files = await run_in_threadpool(_build_context)

    system_prompt = (
        "You are an elite research AI assistant. "
        "Answer the user's inquiry thoroughly, objectively, and accurately using provided research context. "
        "Cite specific facts, entities, dates, and details from the sources when available. Do not include <think> tags."
    )
    if has_attached_file:
        system_prompt += (
            "\n\nCRITICAL INSTRUCTION: The user has attached a reference document or image (marked as [USER ATTACHED FILE]). "
            "You MUST carefully analyze, interpret, and ground your response in the attached document/image's contents and visual details, "
            "synthesizing it with any relevant external knowledge sources."
        )
    if has_local_files:
        system_prompt += (
            "\n\nThe user's own files show the folder they are stored in (\"folder: <library> › <path>\"). "
            "Folder names often name the event, trip, date or people a file belongs to: treat them as facts "
            "about the file, and mention the folder when it helps the user find it."
        )

    if context_snippets:
        joined_context = "\n\n".join(context_snippets)[:CONTEXT_TOTAL_CHARS]
        system_prompt += f"\n\n### RESEARCH CONTEXT:\n{joined_context}"

    messages_payload = [{"role": "system", "content": system_prompt}]
    for m in recent_messages:
        content = (m.get("content") or "").strip()
        if len(content) > 1500:
            content = content[:1500] + "..."
        messages_payload.append({"role": m["role"], "content": content})

    assistant_content = ""
    try:
        from app.ai.groq_client import get_async_groq_client
        # The LLM router picks the model: the selected Ollama model, else the Groq model.
        completion = await get_async_groq_client().chat.completions.create(
            messages=messages_payload,
            max_tokens=2048,
            temperature=0.3,
            timeout=60.0,
        )
        raw_text = (completion.choices[0].message.content or "").strip()
        if "<think>" in raw_text:
            import re
            raw_text = re.sub(r"<think>[\s\S]*?(?:</think>|$)", "", raw_text).strip()
        assistant_content = raw_text
    except Exception as e:
        print(f"[ChatAPI] LLM generation failed: {e}")

    if not assistant_content:
        assistant_content = "I was unable to generate a response at this time. Please check your query or API quota."

    assistant_msg_id = str(uuid.uuid4())
    assistant_now = iso_now()
    citations_json = json.dumps(citations)
    db_run(
        "INSERT INTO chat_messages (id, chat_id, role, content, citations_json, created_at) VALUES (?, ?, 'assistant', ?, ?, ?)",
        (assistant_msg_id, chat_id, assistant_content, citations_json, assistant_now)
    )

    # Auto-generate title if chat was "New Chat"
    title = chat.get("title")
    if title in ("New Chat", "", None):
        title = " ".join(msg_text.split()[:6])
        db_run("UPDATE chats SET title = ?, updated_at = ? WHERE id = ?", (title, assistant_now, chat_id))
    else:
        db_run("UPDATE chats SET updated_at = ? WHERE id = ?", (assistant_now, chat_id))

    return {
        "chat": {"id": chat_id, "title": title, "updatedAt": assistant_now},
        "userMessage": {
            "id": user_msg_id,
            "role": "user",
            "content": msg_text,
            "created_at": now,
        },
        "assistantMessage": {
            "id": assistant_msg_id,
            "role": "assistant",
            "content": assistant_content,
            "citations": citations,
            "created_at": assistant_now,
        }
    }
