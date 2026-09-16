import uuid
import json
import datetime
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends

from app.core.config import settings
from app.database.session import db_get, db_all, db_run, get_db_context
from app.api.deps import require_auth
from app.schemas.chat import ChatCreate, ChatUpdate, MessageCreate

router = APIRouter(prefix="/chats", tags=["chats"])

def iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

@router.get("")
async def list_chats(user: Dict[str, Any] = Depends(require_auth)):
    chats = db_all(
        "SELECT id, title, search_mode, created_at, updated_at FROM chats WHERE user_id = ? ORDER BY updated_at DESC",
        (user["id"],)
    )
    return {"chats": chats}

@router.post("")
async def create_chat(req: ChatCreate, user: Dict[str, Any] = Depends(require_auth)):
    chat_id = str(uuid.uuid4())
    now = iso_now()
    db_run(
        "INSERT INTO chats (id, user_id, title, search_mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, user["id"], req.title or "New Chat", req.searchMode or "internet", now, now)
    )
    return {
        "chat": {
            "id": chat_id,
            "user_id": user["id"],
            "title": req.title or "New Chat",
            "search_mode": req.searchMode or "internet",
            "created_at": now,
            "updated_at": now,
        }
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

    return {
        "chat": chat,
        "messages": messages,
        "contextItems": context_items,
    }

@router.put("/{chat_id}/context")
async def update_chat_context(chat_id: str, req: Dict[str, Any], user: Dict[str, Any] = Depends(require_auth)):
    chat = db_get("SELECT id FROM chats WHERE id = ? AND user_id = ?", (chat_id, user["id"]))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    items = req.get("contextItems", [])
    now = iso_now()
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_context WHERE chat_id = ?", (chat_id,))
        for it in items:
            ctx_id = str(uuid.uuid4())
            ctype = it.get("type", "document")
            if ctype not in ("document", "video", "image", "web"):
                ctype = "document"
            ref_id = str(it.get("refId") or it.get("sourceId") or it.get("id") or ctx_id)
            snippet = it.get("snippet", "")
            meta = it.get("metadata") or {}
            if "title" not in meta and it.get("title"):
                meta["title"] = it.get("title")
            meta_json = json.dumps(meta)
            score = float(it.get("relevanceScore", 0.8))
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

    now = iso_now()
    db_run(
        "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
        (req.title.strip(), now, chat_id)
    )
    return {"success": True, "title": req.title.strip()}

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
            ctype = it.get("type", "document")
            if ctype not in ("document", "video", "image", "web"):
                ctype = "document"
            ref_id = str(it.get("refId") or it.get("sourceId") or it.get("id") or ctx_id)
            snippet = it.get("snippet", "")
            meta = it.get("metadata") or {}
            if "title" not in meta and it.get("title"):
                meta["title"] = it.get("title")
            meta_json = json.dumps(meta)
            score = float(it.get("relevanceScore", 0.8))

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

    # Build conversation context & call Groq
    recent_messages = db_all(
        "SELECT role, content FROM chat_messages WHERE chat_id = ? ORDER BY created_at ASC LIMIT 10",
        (chat_id,)
    )
    context_rows = db_all(
        "SELECT context_type, snippet, metadata_json, relevance_score FROM chat_context WHERE chat_id = ? ORDER BY relevance_score DESC, added_at DESC",
        (chat_id,)
    )

    context_snippets = []
    citations = []
    has_attached_file = False
    for idx, cr in enumerate(context_rows):
        try:
            m = json.loads(cr.get("metadata_json") or "{}")
        except Exception:
            m = {}
        title = m.get("title") or m.get("sourceName") or f"Source {idx + 1}"
        url = m.get("url")
        is_user_att = bool(m.get("isUserAttachment") or "[Attached" in title)
        if is_user_att:
            has_attached_file = True

        raw_snip = (cr.get("snippet") or "").strip()
        if not raw_snip and m.get("extractedSnippet"):
            raw_snip = str(m.get("extractedSnippet")).strip()

        # Generous snippet allowance for attached document/image (up to 1500 chars), other sources up to 500 chars
        limit = 1500 if is_user_att else 500
        trunc_snip = (raw_snip[:limit] + "...") if len(raw_snip) > limit else raw_snip

        prefix = "USER ATTACHED FILE" if is_user_att else cr['context_type'].upper()
        snippet_entry = f"[{prefix}] {title}:\n{trunc_snip}"
        # Put user attached files at the very top of context
        if is_user_att:
            context_snippets.insert(0, snippet_entry)
        else:
            context_snippets.append(snippet_entry)
        citations.append({"title": title, "url": url, "type": cr["context_type"]})

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

    if context_snippets:
        # Take up to 10 sources, cap total joined context to 3500 chars
        joined_context = "\n\n".join(context_snippets[:10])[:3500]
        system_prompt += f"\n\n### RESEARCH CONTEXT:\n{joined_context}"

    messages_payload = [{"role": "system", "content": system_prompt}]
    # Keep last 4 recent messages, truncating long individual messages
    for m in recent_messages[-4:]:
        content = (m.get("content") or "").strip()
        if len(content) > 500:
            content = content[:500] + "..."
        messages_payload.append({"role": m["role"], "content": content})

    assistant_content = ""
    candidate_models = [settings.GROQ_MODEL, "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
    seen = set()
    models_to_try = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

    try:
        from app.ai.groq_client import get_groq_client
        client = get_groq_client()

        for model_name in models_to_try:
            try:
                is_qwen = "qwen" in model_name.lower()
                tokens_limit = 800 if is_qwen else 2048
                call_kwargs = {
                    "model": model_name,
                    "messages": messages_payload,
                    "max_tokens": tokens_limit,
                    "temperature": 0.3,
                }
                if is_qwen:
                    call_kwargs["extra_body"] = {"reasoning_format": "hidden"}

                completion = client.chat.completions.create(**call_kwargs)
                choice = completion.choices[0]
                raw_text = (choice.message.content or "").strip()

                if "<think>" in raw_text:
                    import re
                    raw_text = re.sub(r"<think>[\s\S]*?(?:</think>|$)", "", raw_text).strip()

                if raw_text:
                    assistant_content = raw_text
                    print(f"[ChatAPI] Generated response using {model_name}")
                    break
                else:
                    print(f"[ChatAPI] Model {model_name} returned empty content, trying fallback model...")
            except Exception as e:
                print(f"[ChatAPI] Model {model_name} failed: {e}, trying fallback model...")
    except Exception as outer_e:
        print(f"[ChatAPI] Groq client initialization error: {outer_e}")

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
    if chat.get("title") in ("New Chat", "", None):
        auto_title = " ".join(msg_text.split()[:6])
        db_run("UPDATE chats SET title = ?, updated_at = ? WHERE id = ?", (auto_title, assistant_now, chat_id))
    else:
        db_run("UPDATE chats SET updated_at = ? WHERE id = ?", (assistant_now, chat_id))

    return {
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
