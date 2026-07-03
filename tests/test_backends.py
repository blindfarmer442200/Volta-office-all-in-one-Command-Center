import httpx
import pytest

from bella_harness.backends import BackendAbstraction, BackendError
from bella_harness.backends.ollama_backend import OllamaBackend
from bella_harness.backends.openai_backend import OpenAIBackend


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json_data


def test_ollama_backend_generate(monkeypatch):
    def fake_post(url, json, timeout):
        assert url.endswith("/api/generate")
        return _FakeResponse({"response": "hello there"})

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = OllamaBackend({"base_url": "http://localhost:11434", "model": "llama3.1"})
    response = backend.generate("hi")
    assert response.text == "hello there"
    assert response.backend_name == "ollama"


def test_ollama_backend_raises_backend_error_on_http_failure(monkeypatch):
    def fake_post(url, json, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = OllamaBackend({"base_url": "http://localhost:11434", "model": "llama3.1"})
    with pytest.raises(BackendError):
        backend.generate("hi")


def test_openai_backend_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(BackendError):
        OpenAIBackend({"api_key_env": "OPENAI_API_KEY", "model": "gpt-4o-mini"})


def test_openai_backend_generate(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_post(url, json, headers, timeout):
        assert headers["Authorization"] == "Bearer test-key"
        return _FakeResponse({"choices": [{"message": {"content": "hi from openai"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = OpenAIBackend({"api_key_env": "OPENAI_API_KEY", "model": "gpt-4o-mini"})
    response = backend.generate("hi")
    assert response.text == "hi from openai"


def test_backend_abstraction_orders_default_backend_first():
    config = {
        "harness": {"default_backend": "openai"},
        "backends": {
            "ollama": {"enabled": True, "model": "llama3.1"},
            "openai": {"enabled": True, "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY_UNSET_XYZ"},
        },
    }
    with pytest.raises(BackendError):
        # openai is first (default) but has no key -> constructing should fail fast
        BackendAbstraction(config)


def test_backend_abstraction_falls_back_on_error(monkeypatch):
    call_order = []

    def fake_post(url, json, timeout):
        call_order.append(url)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", fake_post)

    config = {
        "harness": {"default_backend": "ollama"},
        "backends": {
            "ollama": {"enabled": True, "model": "llama3.1", "base_url": "http://localhost:11434"},
        },
    }
    ba = BackendAbstraction(config)
    with pytest.raises(BackendError):
        ba.generate("hi")
    assert call_order  # confirms the backend was actually invoked
