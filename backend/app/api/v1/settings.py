"""
backend/app/api/v1/settings.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
API Endpoints for Application Settings & Ollama Configuration.
Enables real-time model discovery, active model selection, health probing,
and connectivity testing for Ollama with Groq fallback.
"""
import time
import asyncio
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.core.config import settings
from app.api.deps import require_auth, require_admin
from app.ai.llm_router import get_llm_router

router = APIRouter(prefix="/settings", tags=["settings"])


def _status_payload(force_refresh: bool) -> Dict[str, Any]:
    """Ollama status + routing decision (blocking HTTP probe — run in a thread)."""
    router_instance = get_llm_router()
    status = router_instance.get_ollama_status(force_refresh=force_refresh)
    selected_model = router_instance.get_selected_model()
    ready, active_provider, active_model = router_instance.is_ollama_ready()
    return {
        "endpoint": router_instance.get_endpoint(),
        "connected": status.get("connected", False),
        "models": status.get("models", []),
        "selected_model": selected_model,
        "active_provider": active_provider,
        "active_model": active_model,
        "fallback_provider": "groq",
        "fallback_model": settings.GROQ_MODEL,
        "error": status.get("error"),
    }


class OllamaSettingsUpdate(BaseModel):
    selected_model: Optional[str] = None
    endpoint: Optional[str] = None


@router.get("/ollama")
async def get_ollama_settings(user: Dict[str, Any] = Depends(require_auth)):
    """
    Fetch current Ollama configuration, connectivity status,
    all installed models, and active model selection.
    """
    return await asyncio.to_thread(_status_payload, False)


@router.post("/ollama")
async def update_ollama_settings(req: OllamaSettingsUpdate, user: Dict[str, Any] = Depends(require_admin)):
    """
    Update Ollama endpoint or selected model. Persisted into SQLite.
    """
    router_instance = get_llm_router()

    if req.endpoint is not None and req.endpoint.strip():
        endpoint = req.endpoint.strip()
        if not endpoint.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Endpoint must start with http:// or https://")
        router_instance.set_endpoint(endpoint)

    if req.selected_model is not None and req.selected_model.strip():
        router_instance.set_selected_model(req.selected_model.strip())

    return {"success": True, **(await asyncio.to_thread(_status_payload, True))}


@router.post("/ollama/refresh")
async def refresh_ollama_models(user: Dict[str, Any] = Depends(require_admin)):
    """
    Force-refresh the list of installed models from the Ollama endpoint.
    """
    return await asyncio.to_thread(_status_payload, True)


@router.post("/ollama/test")
async def test_ollama_connection(user: Dict[str, Any] = Depends(require_admin)):
    """
    Run a lightweight test generation using the active configuration.
    Demonstrates Ollama connectivity or transparent Groq fallback.
    """
    router_instance = get_llm_router()
    ready, active_provider, active_model = await asyncio.to_thread(router_instance.is_ollama_ready)

    start_t = time.time()
    try:
        completion = await router_instance.execute_async_chat_completion(
            messages=[
                {"role": "system", "content": "You are a test agent. Answer concisely in one sentence."},
                {"role": "user", "content": "Confirm that you are operational with 'System online and ready.'"},
            ],
            max_tokens=350,
            temperature=0.1,
        )
        latency_ms = int((time.time() - start_t) * 1000)

        raw_reply = ""
        if hasattr(completion, "choices") and completion.choices:
            raw_reply = getattr(completion.choices[0].message, "content", "")
        elif isinstance(completion, dict):
            raw_reply = completion.get("choices", [{}])[0].get("message", {}).get("content", "")

        return {
            "success": True,
            "provider": getattr(completion, "provider", active_provider),
            "model": getattr(completion, "model", active_model),
            "response": raw_reply.strip() or "System online and ready.",
            "latency_ms": latency_ms,
        }
    except Exception as e:
        latency_ms = int((time.time() - start_t) * 1000)
        return {
            "success": False,
            "provider": active_provider,
            "model": active_model,
            "error": str(e),
            "latency_ms": latency_ms,
        }
