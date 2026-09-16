"""
backend/tests/test_llm_router.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit and Integration Tests for Unified LLM Endpoint Routing & Fallback.

Tests:
  1. Ollama status & model discovery.
  2. Persistent model selection via SQLite app_settings.
  3. Provider readiness validation (installed model matching).
  4. Automatic transparent fallback to Groq when Ollama is offline or fails.
  5. Structured request JSON handling.
  6. Settings REST API endpoints (/api/settings/ollama, /refresh, /test).
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.ai.llm_router import LLMRouter, get_llm_router, ChatCompletionWrapper
from app.database.session import get_app_setting, set_app_setting


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def router():
    r = LLMRouter()
    r.clear_cache()
    return r


def test_app_settings_persistence():
    """Verify get_app_setting and set_app_setting persist across queries."""
    set_app_setting("test_key_endpoint", "http://127.0.0.1:11434")
    assert get_app_setting("test_key_endpoint") == "http://127.0.0.1:11434"

    set_app_setting("test_key_endpoint", "http://192.168.1.50:11434")
    assert get_app_setting("test_key_endpoint") == "http://192.168.1.50:11434"


def test_ollama_status_discovery_mocked(router):
    """Test model tag parsing from Ollama /api/tags."""
    mock_tags_response = {
        "models": [
            {
                "name": "qwen2.5:7b",
                "model": "qwen2.5:7b",
                "size": 4700000000,
                "details": {
                    "family": "qwen2",
                    "parameter_size": "7B",
                    "quantization_level": "Q4_0",
                },
                "modified_at": "2026-09-01T12:00:00Z",
            },
            {
                "name": "gemma2:9b",
                "model": "gemma2:9b",
                "size": 5500000000,
                "details": {
                    "family": "gemma2",
                    "parameter_size": "9B",
                    "quantization_level": "Q4_K_M",
                },
                "modified_at": "2026-09-02T12:00:00Z",
            },
        ]
    }

    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: mock_tags_response)
        status = router.get_ollama_status(force_refresh=True)

        assert status["connected"] is True
        assert len(status["models"]) == 2
        assert status["models"][0]["name"] == "qwen2.5:7b"
        assert status["models"][0]["family"] == "qwen2"
        assert status["models"][1]["name"] == "gemma2:9b"
        assert status["models"][1]["family"] == "gemma2"


def test_ollama_status_when_offline(router):
    """Test graceful handling when Ollama endpoint is down."""
    with patch("httpx.Client.get", side_effect=Exception("Connection refused")):
        status = router.get_ollama_status(force_refresh=True)
        assert status["connected"] is False
        assert status["models"] == []
        assert "Connection refused" in status["error"]


def test_is_ollama_ready_logic(router):
    """Verify is_ollama_ready checks both connectivity and model presence."""
    # Scenario 1: Ollama offline -> fallback to Groq
    with patch.object(router, "get_ollama_status", return_value={"connected": False, "models": []}):
        ready, provider, model = router.is_ollama_ready()
        assert ready is False
        assert provider == "groq"
        assert model == settings.GROQ_MODEL

    # Scenario 2: Ollama online but selected model not in installed models -> fallback to Groq
    with patch.object(router, "get_ollama_status", return_value={
        "connected": True,
        "models": [{"name": "installed-model:latest"}],
    }):
        router.set_selected_model("missing-model:latest")
        ready, provider, model = router.is_ollama_ready()
        assert ready is False
        assert provider == "groq"

    # Scenario 3: Ollama online and selected model is installed -> Ollama ready
    with patch.object(router, "get_ollama_status", return_value={
        "connected": True,
        "models": [{"name": "installed-model:latest"}],
    }):
        router.set_selected_model("installed-model:latest")
        ready, provider, model = router.is_ollama_ready()
        assert ready is True
        assert provider == "ollama"
        assert model == "installed-model:latest"


def test_chat_completion_routes_to_ollama_when_ready(router):
    """Verify Ollama is called when is_ollama_ready is true."""
    with patch.object(router, "is_ollama_ready", return_value=(True, "ollama", "my-local-model")):
        with patch.object(router, "_call_ollama_sync") as mock_ollama:
            mock_ollama.return_value = ChatCompletionWrapper("Local Ollama Reply", "my-local-model", "ollama")
            resp = router.execute_chat_completion(
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=100,
            )
            assert mock_ollama.called
            assert resp.choices[0].message.content == "Local Ollama Reply"
            assert resp.provider == "ollama"


def test_chat_completion_falls_back_to_groq_when_ollama_unavailable(router):
    """Verify Groq fallback is invoked automatically when Ollama is not ready."""
    with patch.object(router, "is_ollama_ready", return_value=(False, "groq", settings.GROQ_MODEL)):
        with patch.object(router, "_call_groq_sync") as mock_groq:
            fake_choice = MagicMock()
            fake_choice.message.content = "Groq Cloud Reply"
            fake_resp = MagicMock()
            fake_resp.choices = [fake_choice]
            mock_groq.return_value = fake_resp

            resp = router.execute_chat_completion(
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=100,
            )
            assert mock_groq.called
            assert resp.choices[0].message.content == "Groq Cloud Reply"


def test_chat_completion_falls_back_to_groq_on_ollama_runtime_error(router):
    """Verify that if Ollama raises an unexpected error during execution, it transparently falls back to Groq."""
    with patch.object(router, "is_ollama_ready", return_value=(True, "ollama", "my-local-model")):
        with patch.object(router, "_call_ollama_sync", side_effect=RuntimeError("Ollama crashed")):
            with patch.object(router, "_call_groq_sync") as mock_groq:
                fake_choice = MagicMock()
                fake_choice.message.content = "Groq Cloud Fallback Reply"
                fake_resp = MagicMock()
                fake_resp.choices = [fake_choice]
                mock_groq.return_value = fake_resp

                resp = router.execute_chat_completion(
                    messages=[{"role": "user", "content": "hello"}],
                )
                assert mock_groq.called
                assert resp.choices[0].message.content == "Groq Cloud Fallback Reply"


def test_settings_api_get_ollama(client):
    """Test GET /api/settings/ollama returns status structure."""
    res = client.get("/api/settings/ollama")
    assert res.status_code == 200
    data = res.json()
    assert "endpoint" in data
    assert "connected" in data
    assert "models" in data
    assert "active_provider" in data
    assert data["fallback_provider"] == "groq"
    assert "fallback_model" in data


def test_settings_api_update_model(client):
    """Test POST /api/settings/ollama updates selected model."""
    res = client.post("/api/settings/ollama", json={"selected_model": "test-model:latest"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["selected_model"] == "test-model:latest"


def test_settings_api_refresh_models(client):
    """Test POST /api/settings/ollama/refresh returns status."""
    res = client.post("/api/settings/ollama/refresh")
    assert res.status_code == 200
    data = res.json()
    assert "connected" in data
    assert "models" in data
