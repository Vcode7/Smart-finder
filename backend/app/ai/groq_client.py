import re
import json
import time
import threading
from typing import Any, Dict, List, Optional, Tuple, Callable, Awaitable
import httpx
from groq import Groq, AsyncGroq

try:
    from groq import RateLimitError as GroqRateLimitError, APIStatusError
except ImportError:
    GroqRateLimitError = None
    APIStatusError = None

from app.core.config import settings

def is_groq_rate_limit_error(e: Exception) -> Tuple[bool, str]:
    """
    Detect Groq rate-limit / too-many-requests / quota-related errors reliably.
    Returns (is_rate_limit: bool, reason_description: str).
    """
    if GroqRateLimitError and isinstance(e, GroqRateLimitError):
        msg = str(e)
        return True, f"429 RateLimitError ({msg[:120]})" if msg else "429 RateLimitError"

    if APIStatusError and isinstance(e, APIStatusError):
        code = getattr(e, "status_code", None)
        if code == 429:
            return True, f"HTTP 429 Too Many Requests ({str(e)[:120]})"
        if code in (503, 504):
            return True, f"HTTP {code} Service Unavailable ({str(e)[:120]})"

    status_code = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    if status_code == 429:
        return True, f"HTTP 429 Too Many Requests ({str(e)[:120]})"
    if status_code in (503, 504):
        return True, f"HTTP {status_code} ({str(e)[:120]})"

    err_str = str(e).lower()
    rate_limit_patterns = [
        "rate limit",
        "rate_limit",
        "too many requests",
        "quota exceeded",
        "insufficient_quota",
        "resource_exhausted",
        "tokens per minute",
        "tpm",
        "otpm",
        "output tokens per minute",
        "requests per minute",
        "rpm",
        "requests per day",
        "rpd",
        "429",
        "exceeded your current quota",
    ]
    for pattern in rate_limit_patterns:
        if pattern in err_str:
            return True, f"Rate limit / quota signal detected ('{pattern}')"

    return False, str(e)[:120]


def _log_groq(msg: str) -> None:
    try:
        print(msg, flush=True)
    except (UnicodeEncodeError, Exception):
        try:
            print(msg.replace("→", "->"), flush=True)
        except Exception:
            pass
    try:
        logger.info(msg.replace("→", "->"))
    except Exception:
        pass


class GroqKeyManager:
    """
    Centralized manager for primary and fallback Groq API keys.
    Maintains thread-safe and async-safe key rotation, cooldown tracking,
    and automatic retries without losing request context or exposing secrets.
    """
    COOLDOWN_SECONDS: float = 60.0

    def __init__(self):
        self._lock = threading.Lock()
        self._current_index: int = 0
        self._exhausted_until: Dict[int, float] = {}
        self._sync_clients: Dict[str, Groq] = {}
        self._async_clients: Dict[str, AsyncGroq] = {}

    def get_configured_keys(self) -> List[Dict[str, str]]:
        return settings.get_groq_api_keys()

    def get_active_key_index(self, keys: List[Dict[str, str]]) -> int:
        now = time.time()
        with self._lock:
            total = len(keys)
            if total == 0:
                return 0
            # If current index is in cooldown, advance to first available non-cooldown key
            if self._exhausted_until.get(self._current_index, 0.0) > now:
                for offset in range(total):
                    idx = (self._current_index + offset) % total
                    if self._exhausted_until.get(idx, 0.0) <= now:
                        self._current_index = idx
                        break
            return self._current_index

    def mark_key_rate_limited(self, key_idx: int, keys: List[Dict[str, str]], reason: str) -> Optional[int]:
        now = time.time()
        with self._lock:
            total = len(keys)
            if total <= 1:
                return None
            self._exhausted_until[key_idx] = now + self.COOLDOWN_SECONDS
            current_label = keys[key_idx]["label"]
            next_idx = (key_idx + 1) % total
            next_label = keys[next_idx]["label"]
            self._current_index = next_idx

            _log_groq(f"[GROQ] {current_label} rate limited ({reason}) → switching to {next_label}")
            return next_idx

    def mark_key_success(self, key_idx: int, keys: List[Dict[str, str]]) -> None:
        with self._lock:
            self._current_index = key_idx
            self._exhausted_until.pop(key_idx, None)
            if key_idx > 0:
                label = keys[key_idx]["label"]
                _log_groq(f"[GROQ] Request succeeded using {label}")

    def get_sync_client_for_key(self, api_key: str) -> Groq:
        if api_key not in self._sync_clients:
            self._sync_clients[api_key] = Groq(api_key=api_key, http_client=httpx.Client(timeout=30.0))
        return self._sync_clients[api_key]

    def get_async_client_for_key(self, api_key: str) -> AsyncGroq:
        if api_key not in self._async_clients:
            self._async_clients[api_key] = AsyncGroq(api_key=api_key, http_client=httpx.AsyncClient(timeout=30.0))
        return self._async_clients[api_key]

    def execute_with_fallback(self, call_fn: Callable[[Groq], Any]) -> Any:
        keys = self.get_configured_keys()
        if not keys:
            raise ValueError("No GROQ_API_KEY configured in environment.")

        total_keys = len(keys)
        start_idx = self.get_active_key_index(keys)
        last_error: Optional[Exception] = None

        for attempt in range(total_keys):
            idx = (start_idx + attempt) % total_keys
            key_info = keys[idx]
            client = self.get_sync_client_for_key(key_info["key"])

            try:
                result = call_fn(client)
                self.mark_key_success(idx, keys)
                return result
            except Exception as e:
                is_rate_limit, reason = is_groq_rate_limit_error(e)
                last_error = e
                if is_rate_limit and attempt < total_keys - 1:
                    self.mark_key_rate_limited(idx, keys, reason)
                    continue
                elif is_rate_limit:
                    _log_groq(f"[GROQ] All {total_keys} Groq keys exhausted. Last error: {reason}")
                    raise e
                else:
                    raise e

        if last_error:
            raise last_error

    async def execute_async_with_fallback(self, call_fn: Callable[[AsyncGroq], Awaitable[Any]]) -> Any:
        keys = self.get_configured_keys()
        if not keys:
            raise ValueError("No GROQ_API_KEY configured in environment.")

        total_keys = len(keys)
        start_idx = self.get_active_key_index(keys)
        last_error: Optional[Exception] = None

        for attempt in range(total_keys):
            idx = (start_idx + attempt) % total_keys
            key_info = keys[idx]
            client = self.get_async_client_for_key(key_info["key"])

            try:
                result = await call_fn(client)
                self.mark_key_success(idx, keys)
                return result
            except Exception as e:
                is_rate_limit, reason = is_groq_rate_limit_error(e)
                last_error = e
                if is_rate_limit and attempt < total_keys - 1:
                    self.mark_key_rate_limited(idx, keys, reason)
                    continue
                elif is_rate_limit:
                    _log_groq(f"[GROQ] All {total_keys} Groq keys exhausted. Last error: {reason}")
                    raise e
                else:
                    raise e

        if last_error:
            raise last_error


# Singleton Manager
_key_manager = GroqKeyManager()

# ─── Transparent Proxies for get_groq_client & get_async_groq_client ─────────

class _SyncChatCompletionsProxy:
    def __init__(self, manager: GroqKeyManager):
        self._manager = manager

    def create(self, **kwargs):
        return self._manager.execute_with_fallback(
            lambda client: client.chat.completions.create(**kwargs)
        )

class _SyncAudioTranscriptionsProxy:
    def __init__(self, manager: GroqKeyManager):
        self._manager = manager

    def create(self, **kwargs):
        return self._manager.execute_with_fallback(
            lambda client: client.audio.transcriptions.create(**kwargs)
        )

class _SyncAudioProxy:
    def __init__(self, manager: GroqKeyManager):
        self.transcriptions = _SyncAudioTranscriptionsProxy(manager)

class _SyncChatProxy:
    def __init__(self, manager: GroqKeyManager):
        self.completions = _SyncChatCompletionsProxy(manager)

class FallbackGroqClient:
    def __init__(self, manager: GroqKeyManager):
        self._manager = manager
        self.chat = _SyncChatProxy(manager)
        self.audio = _SyncAudioProxy(manager)

    def __getattr__(self, name):
        keys = self._manager.get_configured_keys()
        if not keys:
            raise ValueError("No GROQ_API_KEY configured in environment.")
        idx = self._manager.get_active_key_index(keys)
        real_client = self._manager.get_sync_client_for_key(keys[idx]["key"])
        return getattr(real_client, name)


class _AsyncChatCompletionsProxy:
    def __init__(self, manager: GroqKeyManager):
        self._manager = manager

    async def create(self, **kwargs):
        return await self._manager.execute_async_with_fallback(
            lambda client: client.chat.completions.create(**kwargs)
        )

class _AsyncAudioTranscriptionsProxy:
    def __init__(self, manager: GroqKeyManager):
        self._manager = manager

    async def create(self, **kwargs):
        return await self._manager.execute_async_with_fallback(
            lambda client: client.audio.transcriptions.create(**kwargs)
        )

class _AsyncAudioProxy:
    def __init__(self, manager: GroqKeyManager):
        self.transcriptions = _AsyncAudioTranscriptionsProxy(manager)

class _AsyncChatProxy:
    def __init__(self, manager: GroqKeyManager):
        self.completions = _AsyncChatCompletionsProxy(manager)

class FallbackAsyncGroqClient:
    def __init__(self, manager: GroqKeyManager):
        self._manager = manager
        self.chat = _AsyncChatProxy(manager)
        self.audio = _AsyncAudioProxy(manager)

    def __getattr__(self, name):
        keys = self._manager.get_configured_keys()
        if not keys:
            raise ValueError("No GROQ_API_KEY configured in environment.")
        idx = self._manager.get_active_key_index(keys)
        real_client = self._manager.get_async_client_for_key(keys[idx]["key"])
        return getattr(real_client, name)


_sync_proxy = FallbackGroqClient(_key_manager)
_async_proxy = FallbackAsyncGroqClient(_key_manager)

def get_groq_client() -> Groq:
    """Return transparent Groq client proxy backed by multi-key fallback."""
    if not settings.get_groq_api_keys():
        raise ValueError("No GROQ_API_KEY configured in .env file.")
    return _sync_proxy  # type: ignore

def get_async_groq_client() -> AsyncGroq:
    """Return transparent AsyncGroq client proxy backed by multi-key fallback."""
    if not settings.get_groq_api_keys():
        raise ValueError("No GROQ_API_KEY configured in .env file.")
    return _async_proxy  # type: ignore

def execute_with_groq_fallback(call_fn: Callable[[Groq], Any]) -> Any:
    """Execute a synchronous Groq operation with automatic multi-key fallback."""
    return _key_manager.execute_with_fallback(call_fn)

async def execute_async_with_groq_fallback(call_fn: Callable[[AsyncGroq], Awaitable[Any]]) -> Any:
    """Execute an asynchronous Groq operation with automatic multi-key fallback."""
    return await _key_manager.execute_async_with_fallback(call_fn)

def get_groq_key_manager() -> GroqKeyManager:
    return _key_manager


# ─── Utility Helpers ─────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)

def clean_json_response(content: str) -> str:
    if not content:
        return ""
    cleaned = content.strip()
    cleaned = re.sub(r"<think>[\s\S]*?(?:</think>|$)", "", cleaned).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```", "", cleaned)

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    first_bracket = cleaned.find("[")
    last_bracket = cleaned.rfind("]")

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        if first_bracket != -1 and first_bracket < first_brace and last_bracket > last_brace:
            cleaned = cleaned[first_bracket:last_bracket + 1]
        else:
            cleaned = cleaned[first_brace:last_brace + 1]
    elif first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        cleaned = cleaned[first_bracket:last_bracket + 1]

    return cleaned.strip()

def robust_json_loads(content: str, default: Any = None) -> Any:
    if not content or not str(content).strip():
        return default if default is not None else {}
    cleaned = clean_json_response(content)
    if not cleaned:
        return default if default is not None else {}

    try:
        return json.loads(cleaned, strict=False)
    except Exception:
        pass

    try:
        no_trailing = re.sub(r",\s*([\]}])", r"\1", cleaned)
        return json.loads(no_trailing, strict=False)
    except Exception:
        pass

    try:
        fixed_quotes = re.sub(r"(?<!\\)'", '"', cleaned)
        return json.loads(fixed_quotes, strict=False)
    except Exception:
        pass

    return default if default is not None else {}


def execute_groq_request(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.1,
    operation: str = "general"
) -> Dict[str, Any]:
    """Execute Groq request with multi-key rate-limit fallback and JSON parsing."""
    model = settings.GROQ_MODEL

    def _do_call(client: Groq):
        safe_max_tokens = min(max_tokens, 850) if "qwen" in model.lower() else max_tokens
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": safe_max_tokens,
            "temperature": temperature,
        }
        if "qwen" in model.lower():
            kwargs["extra_body"] = {"reasoning_format": "hidden"}
        elif "r1" not in model.lower():
            kwargs["response_format"] = {"type": "json_object"}

        completion = client.chat.completions.create(**kwargs)
        raw = completion.choices[0].message.content or "{}"
        return robust_json_loads(raw, default={})

    try:
        return _key_manager.execute_with_fallback(_do_call)
    except Exception as e:
        print(f"[Groq Execution Failed] Operation: {operation.upper()}: {e}")
        raise e
