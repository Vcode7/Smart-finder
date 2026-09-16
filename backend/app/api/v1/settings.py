"""
backend/app/api/v1/settings.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
API Endpoints for Application Settings & Ollama Configuration.
Enables real-time model discovery, active model selection, health probing,
and connectivity testing for Ollama with Groq fallback.
"""
import time
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.ai.llm_router import get_llm_router

router = APIRouter(prefix="/settings", tags=["settings"])


class OllamaSettingsUpdate(BaseModel):
    selected_model: Optional[str] = None
    endpoint: Optional[str] = None


@router.get("/ollama")
async def get_ollama_settings():
    """
    Fetch current Ollama configuration, connectivity status,
    all installed models, and active model selection.
    """
    router_instance = get_llm_router()
    status = router_instance.get_ollama_status(force_refresh=False)
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


@router.post("/ollama")
async def update_ollama_settings(req: OllamaSettingsUpdate):
    """
    Update Ollama endpoint or selected model. Persisted into SQLite.
    """
    router_instance = get_llm_router()

    if req.endpoint is not None and req.endpoint.strip():
        router_instance.set_endpoint(req.endpoint.strip())

    if req.selected_model is not None and req.selected_model.strip():
        router_instance.set_selected_model(req.selected_model.strip())

    # Return refreshed status
    status = router_instance.get_ollama_status(force_refresh=True)
    selected_model = router_instance.get_selected_model()
    ready, active_provider, active_model = router_instance.is_ollama_ready()

    return {
        "success": True,
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


@router.post("/ollama/refresh")
async def refresh_ollama_models():
    """
    Force-refresh the list of installed models from the Ollama endpoint.
    """
    router_instance = get_llm_router()
    status = router_instance.get_ollama_status(force_refresh=True)
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


@router.post("/ollama/test")
async def test_ollama_connection():
    """
    Run a lightweight test generation using the active configuration.
    Demonstrates Ollama connectivity or transparent Groq fallback.
    """
    router_instance = get_llm_router()
    ready, active_provider, active_model = router_instance.is_ollama_ready()

    start_t = time.time()
    try:
        completion = router_instance.execute_chat_completion(
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
