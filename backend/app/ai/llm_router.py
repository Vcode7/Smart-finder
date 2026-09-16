"""
backend/app/ai/llm_router.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unified LLM Endpoint Routing & Provider Manager.

Implements the single source of truth for all LLM calls:
  Priority:
    Ollama (selected local model)
        ↓  (if unavailable, offline, missing model, or on error)
    Groq API (configured Groq model + multi-key rotation)

Handles:
  1. Ollama health probing and model discovery (/api/tags).
  2. Persistent model selection via SQLite app_settings.
  3. Seamless sync & async completions (OpenAI/Groq compatible).
  4. Automatic transparent fallback to Groq with zero prompt modifications.
"""
from __future__ import annotations

import json
import re
import time
import threading
from typing import Any, Dict, List, Optional, Tuple, Generator, AsyncGenerator
import httpx

from app.core.config import settings
from app.database.session import get_app_setting, set_app_setting


# ─── Response Wrappers (OpenAI/Groq API Compatible) ──────────────────────────

class MessageWrapper:
    def __init__(self, content: str, role: str = "assistant"):
        self.content = content
        self.role = role

    def __getitem__(self, item):
        return getattr(self, item)


class ChoiceWrapper:
    def __init__(self, message: MessageWrapper, finish_reason: str = "stop"):
        self.message = message
        self.finish_reason = finish_reason

    def __getitem__(self, item):
        return getattr(self, item)


class ChatCompletionWrapper:
    def __init__(self, content: str, model: str, provider: str = "ollama"):
        self.id = f"chatcmpl-{int(time.time() * 1000)}"
        self.choices = [ChoiceWrapper(MessageWrapper(content))]
        self.model = model
        self.provider = provider

    def __getitem__(self, item):
        return getattr(self, item)


class DeltaWrapper:
    def __init__(self, content: str):
        self.content = content

    def __getitem__(self, item):
        return getattr(self, item)


class StreamChoiceWrapper:
    def __init__(self, delta: DeltaWrapper):
        self.delta = delta

    def __getitem__(self, item):
        return getattr(self, item)


class ChatCompletionChunkWrapper:
    def __init__(self, content: str, model: str):
        self.choices = [StreamChoiceWrapper(DeltaWrapper(content))]
        self.model = model

    def __getitem__(self, item):
        return getattr(self, item)


# ─── LLMRouter Implementation ────────────────────────────────────────────────

class LLMRouter:
    _instance: Optional[LLMRouter] = None
    _lock = threading.RLock()

    def __init__(self):
        self._cache_lock = threading.Lock()
        self._status_cache: Optional[Dict[str, Any]] = None
        self._cache_timestamp: float = 0.0
        self._cache_ttl: float = 8.0  # seconds to cache health probe

    @classmethod
    def get_instance(cls) -> LLMRouter:
        with cls._lock:
            if cls._instance is None:
                cls._instance = LLMRouter()
            return cls._instance

    # ─── Endpoint & Model Configuration ──────────────────────────────────────

    def get_endpoint(self) -> str:
        """Get configured Ollama endpoint (SQLite > settings > default)."""
        ep = get_app_setting("ollama_endpoint")
        if ep and ep.strip():
            return ep.strip()
        return settings.OLLAMA_ENDPOINT.strip() or "http://localhost:11434"

    def set_endpoint(self, endpoint: str) -> None:
        """Persist new Ollama endpoint."""
        clean = endpoint.strip().rstrip("/")
        set_app_setting("ollama_endpoint", clean)
        settings.OLLAMA_ENDPOINT = clean
        self.clear_cache()

    def get_selected_model(self) -> str:
        """Get user-selected Ollama model name (SQLite > settings > auto-detect)."""
        m = get_app_setting("ollama_model")
        if m and m.strip():
            return m.strip()
        if settings.OLLAMA_MODEL and settings.OLLAMA_MODEL.strip():
            return settings.OLLAMA_MODEL.strip()

        # If none explicitly selected, try to pick the first available from Ollama
        status = self.get_ollama_status(force_refresh=False)
        if status.get("connected") and status.get("models"):
            first_model = status["models"][0]["name"]
            # Auto-save as default selection
            set_app_setting("ollama_model", first_model)
            settings.OLLAMA_MODEL = first_model
            return first_model
        return ""

    def set_selected_model(self, model_name: str) -> None:
        """Persist user-selected Ollama model name."""
        clean = model_name.strip()
        set_app_setting("ollama_model", clean)
        settings.OLLAMA_MODEL = clean
        self.clear_cache()

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._status_cache = None
            self._cache_timestamp = 0.0

    # ─── Ollama Status & Discovery ───────────────────────────────────────────

    def get_ollama_status(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Check if Ollama endpoint is reachable and fetch list of all installed models.
        Results are cached for a short TTL to keep latency low.
        """
        now = time.time()
        with self._cache_lock:
            if not force_refresh and self._status_cache is not None:
                if (now - self._cache_timestamp) < self._cache_ttl:
                    return self._status_cache

        endpoint = self.get_endpoint()
        status_data: Dict[str, Any] = {
            "endpoint": endpoint,
            "connected": False,
            "models": [],
            "error": None,
        }

        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{endpoint}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    raw_models = data.get("models", [])
                    parsed_models = []
                    for m in raw_models:
                        details = m.get("details", {})
                        size_bytes = m.get("size", 0)
                        size_gb = round(size_bytes / (1024 ** 3), 2)
                        parsed_models.append({
                            "name": m.get("name", ""),
                            "model": m.get("model", m.get("name", "")),
                            "size_bytes": size_bytes,
                            "size_formatted": f"{size_gb} GB" if size_gb >= 1.0 else f"{round(size_bytes / (1024 ** 2), 1)} MB",
                            "family": details.get("family", ""),
                            "parameter_size": details.get("parameter_size", ""),
                            "quantization_level": details.get("quantization_level", ""),
                            "modified_at": m.get("modified_at", ""),
                        })
                    status_data["connected"] = True
                    status_data["models"] = parsed_models
                else:
                    status_data["error"] = f"HTTP {res.status_code}"
        except Exception as e:
            status_data["error"] = str(e)

        with self._cache_lock:
            self._status_cache = status_data
            self._cache_timestamp = now

        return status_data

    def is_ollama_ready(self) -> Tuple[bool, str, Optional[str]]:
        """
        Returns (is_ready, active_provider, active_model).
        Validates that Ollama is responding AND the selected model is installed.
        """
        status = self.get_ollama_status()
        if not status.get("connected"):
            return False, "groq", settings.GROQ_MODEL

        installed_names = [m["name"] for m in status.get("models", [])]
        selected = self.get_selected_model()

        if not selected or selected not in installed_names:
            # Selected model is missing from Ollama
            return False, "groq", settings.GROQ_MODEL

        return True, "ollama", selected

    # ─── Chat Completion Execution (with automatic fallback) ─────────────────

    def execute_chat_completion(self, **kwargs) -> Any:
        """
        Execute chat completion:
          1. Tries Ollama with selected model first.
          2. Falls back automatically to Groq API on failure or unavailability.
        """
        ready, provider, model = self.is_ollama_ready()
        is_streaming = kwargs.get("stream", False)

        if ready:
            endpoint = self.get_endpoint()
            try:
                # Prepare payload for Ollama
                ollama_payload = self._build_ollama_payload(kwargs, model)
                timeout = float(settings.OLLAMA_TIMEOUT)

                if is_streaming:
                    return self._stream_ollama(endpoint, ollama_payload, model, kwargs)
                else:
                    return self._call_ollama_sync(endpoint, ollama_payload, model, timeout)
            except Exception as e:
                print(
                    f"[LLMRouter] ⚠️ Ollama execution error ({type(e).__name__}: {e}) → "
                    f"Falling back to Groq ({settings.GROQ_MODEL})...",
                    flush=True
                )

        # Fallback to Groq
        return self._call_groq_sync(kwargs)

    async def execute_async_chat_completion(self, **kwargs) -> Any:
        """Async equivalent for FastAPI async route handlers."""
        ready, provider, model = self.is_ollama_ready()
        is_streaming = kwargs.get("stream", False)

        if ready:
            endpoint = self.get_endpoint()
            try:
                ollama_payload = self._build_ollama_payload(kwargs, model)
                timeout = float(settings.OLLAMA_TIMEOUT)

                if is_streaming:
                    return self._stream_ollama_async(endpoint, ollama_payload, model, kwargs)
                else:
                    return await self._call_ollama_async(endpoint, ollama_payload, model, timeout)
            except Exception as e:
                print(
                    f"[LLMRouter] ⚠️ Ollama async call error ({type(e).__name__}: {e}) → "
                    f"Falling back to Groq ({settings.GROQ_MODEL})...",
                    flush=True
                )

        # Fallback to Groq
        return await self._call_groq_async(kwargs)

    # ─── Structured JSON Request Execution ───────────────────────────────────

    def execute_structured_request(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.1,
        operation: str = "general",
    ) -> Dict[str, Any]:
        """Executes structured JSON query with clean parsing and fallback."""
        from app.ai.groq_client import robust_json_loads

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        completion = self.execute_chat_completion(**kwargs)
        raw_text = ""
        if hasattr(completion, "choices") and completion.choices:
            raw_text = completion.choices[0].message.content or ""
        elif isinstance(completion, dict):
            raw_text = completion.get("choices", [{}])[0].get("message", {}).get("content", "")

        parsed = robust_json_loads(raw_text, default={})
        return parsed

    # ─── Internal Ollama Call Helpers ────────────────────────────────────────

    def _build_ollama_payload(self, kwargs: Dict[str, Any], model: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": kwargs.get("messages", []),
            "stream": kwargs.get("stream", False),
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            # Ensure models with reasoning headroom have at least 300 tokens
            payload["max_tokens"] = max(kwargs["max_tokens"], 300)
        if "response_format" in kwargs:
            payload["response_format"] = kwargs["response_format"]
        return payload

    def _call_ollama_sync(
        self, endpoint: str, payload: Dict[str, Any], model: str, timeout: float
    ) -> ChatCompletionWrapper:
        # Use Ollama's OpenAI-compatible /v1/chat/completions endpoint
        url = f"{endpoint}/v1/chat/completions"
        with httpx.Client(timeout=timeout) as client:
            res = client.post(url, json=payload)
            if res.status_code != 200:
                raise RuntimeError(f"Ollama returned HTTP {res.status_code}: {res.text[:150]}")
            data = res.json()
            choices = data.get("choices", [])
            raw_content = choices[0].get("message", {}).get("content", "") if choices else ""
            if not raw_content and choices and choices[0].get("message", {}).get("reasoning"):
                raw_content = choices[0]["message"]["reasoning"]
            content = self._strip_think_tags(raw_content)
            return ChatCompletionWrapper(content=content, model=model, provider="ollama")

    async def _call_ollama_async(
        self, endpoint: str, payload: Dict[str, Any], model: str, timeout: float
    ) -> ChatCompletionWrapper:
        url = f"{endpoint}/v1/chat/completions"
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(url, json=payload)
            if res.status_code != 200:
                raise RuntimeError(f"Ollama returned HTTP {res.status_code}: {res.text[:150]}")
            data = res.json()
            choices = data.get("choices", [])
            raw_content = choices[0].get("message", {}).get("content", "") if choices else ""
            if not raw_content and choices and choices[0].get("message", {}).get("reasoning"):
                raw_content = choices[0]["message"]["reasoning"]
            content = self._strip_think_tags(raw_content)
            return ChatCompletionWrapper(content=content, model=model, provider="ollama")

    def _stream_ollama(
        self, endpoint: str, payload: Dict[str, Any], model: str, original_kwargs: Dict[str, Any]
    ) -> Generator[ChatCompletionChunkWrapper, None, None]:
        url = f"{endpoint}/v1/chat/completions"
        try:
            with httpx.Client(timeout=settings.OLLAMA_TIMEOUT) as client:
                with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        raise RuntimeError(f"Ollama stream error: HTTP {response.status_code}")
                    for line in response.iter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            raw_json = line[6:].strip()
                            if raw_json == "[DONE]":
                                break
                            try:
                                chunk_data = json.loads(raw_json)
                                delta_text = chunk_data["choices"][0]["delta"].get("content", "")
                                if delta_text:
                                    yield ChatCompletionChunkWrapper(content=delta_text, model=model)
                            except Exception:
                                pass
        except Exception as e:
            print(f"[LLMRouter] Stream error from Ollama ({e}), falling back to Groq stream...", flush=True)
            yield from self._stream_groq(original_kwargs)

    async def _stream_ollama_async(
        self, endpoint: str, payload: Dict[str, Any], model: str, original_kwargs: Dict[str, Any]
    ) -> AsyncGenerator[ChatCompletionChunkWrapper, None]:
        url = f"{endpoint}/v1/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=settings.OLLAMA_TIMEOUT) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        raise RuntimeError(f"Ollama async stream error: HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            raw_json = line[6:].strip()
                            if raw_json == "[DONE]":
                                break
                            try:
                                chunk_data = json.loads(raw_json)
                                delta_text = chunk_data["choices"][0]["delta"].get("content", "")
                                if delta_text:
                                    yield ChatCompletionChunkWrapper(content=delta_text, model=model)
                            except Exception:
                                pass
        except Exception as e:
            print(f"[LLMRouter] Async stream error from Ollama ({e}), falling back to Groq...", flush=True)
            # Fallback to sync generator wrapped or Groq call
            groq_stream = self._stream_groq(original_kwargs)
            for chunk in groq_stream:
                yield chunk

    # ─── Internal Groq Fallback Helpers ──────────────────────────────────────

    def _call_groq_sync(self, kwargs: Dict[str, Any]) -> Any:
        from app.ai.groq_client import get_groq_key_manager
        km = get_groq_key_manager()

        call_kwargs = dict(kwargs)
        call_kwargs["model"] = settings.GROQ_MODEL
        if "qwen" in settings.GROQ_MODEL.lower():
            call_kwargs.setdefault("extra_body", {"reasoning_format": "hidden"})
            call_kwargs["max_tokens"] = min(call_kwargs.get("max_tokens", 850), 850)

        def _fn(client):
            return client.chat.completions.create(**call_kwargs)

        return km.execute_with_fallback(_fn)

    async def _call_groq_async(self, kwargs: Dict[str, Any]) -> Any:
        from app.ai.groq_client import get_groq_key_manager
        km = get_groq_key_manager()

        call_kwargs = dict(kwargs)
        call_kwargs["model"] = settings.GROQ_MODEL
        if "qwen" in settings.GROQ_MODEL.lower():
            call_kwargs.setdefault("extra_body", {"reasoning_format": "hidden"})
            call_kwargs["max_tokens"] = min(call_kwargs.get("max_tokens", 850), 850)

        async def _fn(client):
            return await client.chat.completions.create(**call_kwargs)

        return await km.execute_async_with_fallback(_fn)

    def _stream_groq(self, kwargs: Dict[str, Any]):
        from app.ai.groq_client import get_groq_client
        client = get_groq_client()
        call_kwargs = dict(kwargs)
        call_kwargs["model"] = settings.GROQ_MODEL
        call_kwargs["stream"] = True
        return client.chat.completions.create(**call_kwargs)

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"<think>[\s\S]*?(?:</think>|$)", "", text).strip()


# Convenience Singleton Accessor
def get_llm_router() -> LLMRouter:
    return LLMRouter.get_instance()
