import json

import httpx
import pytest

from bella_harness.backends import BackendAbstraction, BackendError
from bella_harness.backends.anthropic_backend import AnthropicBackend
from bella_harness.backends.ollama_backend import OllamaBackend
from bella_harness.backends.openai_backend import OpenAIBackend
from bella_harness.backends.openrouter_backend import OpenRouterBackend


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json_data


class _FakeStreamResponse:
    def __init__(self, json_data=None, *, raw=None, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._raw = raw if raw is not None else json.dumps(json_data or {}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def iter_bytes(self):
        midpoint = max(1, len(self._raw) // 2)
        yield self._raw[:midpoint]
        yield self._raw[midpoint:]


def test_ollama_backend_generate_uses_bounded_private_stream(monkeypatch):
    captured = {}

    def fake_stream(method, url, json, timeout, follow_redirects):
        captured.update(
            method=method,
            url=url,
            payload=json,
            timeout=timeout,
            follow_redirects=follow_redirects,
        )
        return _FakeStreamResponse({"response": "hello there"})

    monkeypatch.setattr(httpx, "stream", fake_stream)
    backend = OllamaBackend({"base_url": "http://localhost:11434", "model": "llama3.1"})
    response = backend.generate("hi")
    assert response.text == "hello there"
    assert response.backend_name == "ollama"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/generate")
    assert captured["follow_redirects"] is False


def test_ollama_backend_raises_backend_error_on_http_failure(monkeypatch):
    def fake_stream(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "stream", fake_stream)
    backend = OllamaBackend({"base_url": "http://localhost:11434", "model": "llama3.1"})
    with pytest.raises(BackendError):
        backend.generate("hi")


def test_ollama_rejects_redirects_malformed_json_and_oversized_response(monkeypatch):
    backend = OllamaBackend(
        {
            "base_url": "http://localhost:11434",
            "model": "llama3.1",
            "max_response_bytes": 1024,
        }
    )

    monkeypatch.setattr(
        httpx,
        "stream",
        lambda *args, **kwargs: _FakeStreamResponse({}, status_code=302),
    )
    with pytest.raises(BackendError, match="redirect"):
        backend.generate("hi")

    monkeypatch.setattr(
        httpx,
        "stream",
        lambda *args, **kwargs: _FakeStreamResponse(raw=b"not-json"),
    )
    with pytest.raises(BackendError, match="valid JSON"):
        backend.generate("hi")

    monkeypatch.setattr(
        httpx,
        "stream",
        lambda *args, **kwargs: _FakeStreamResponse(
            raw=b"{}", headers={"content-length": "2048"}
        ),
    )
    with pytest.raises(BackendError, match="byte limit"):
        backend.generate("hi")


def test_ollama_rejects_public_hostname_credentials_path_and_public_ip():
    unsafe = [
        "https://ollama.example.com",
        "http://user:pass@localhost:11434",
        "http://localhost:11434/prefix",
        "http://8.8.8.8:11434",
    ]
    for base_url in unsafe:
        with pytest.raises(BackendError, match="unsafe Ollama endpoint"):
            OllamaBackend({"base_url": base_url, "model": "llama3.1"})


def test_ollama_accepts_loopback_private_ipv4_and_private_ipv6():
    assert OllamaBackend({"base_url": "http://127.0.0.1:11434", "model": "m"}).base_url == (
        "http://127.0.0.1:11434"
    )
    assert OllamaBackend({"base_url": "http://192.168.1.20:11434", "model": "m"}).base_url == (
        "http://192.168.1.20:11434"
    )
    assert OllamaBackend({"base_url": "http://[fd00::1]:11434/", "model": "m"}).base_url == (
        "http://[fd00::1]:11434"
    )


def test_ollama_prompt_model_and_output_bounds(monkeypatch):
    backend = OllamaBackend(
        {
            "base_url": "http://localhost:11434",
            "model": "llama3.1",
            "max_prompt_chars": 1000,
            "max_output_chars": 1000,
        }
    )
    with pytest.raises(BackendError, match="prompt exceeds"):
        backend.generate("x" * 1001)
    with pytest.raises(BackendError, match="control characters"):
        backend.generate("hi", model="bad\nmodel")

    monkeypatch.setattr(
        httpx,
        "stream",
        lambda *args, **kwargs: _FakeStreamResponse({"response": "x" * 1001}),
    )
    with pytest.raises(BackendError, match="generated text exceeds"):
        backend.generate("hi")


def test_ollama_health_check_uses_tags_without_prompt(monkeypatch):
    captured = {}

    def fake_stream(method, url, json, timeout, follow_redirects):
        captured.update(method=method, url=url, payload=json)
        return _FakeStreamResponse({"models": []})

    monkeypatch.setattr(httpx, "stream", fake_stream)
    backend = OllamaBackend({"base_url": "http://localhost:11434", "model": "llama3.1"})
    assert backend.health_check()
    assert captured == {
        "method": "GET",
        "url": "http://localhost:11434/api/tags",
        "payload": None,
    }


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
        BackendAbstraction(config)


def test_backend_abstraction_falls_back_on_error(monkeypatch):
    calls = []

    def fake_stream(method, url, **kwargs):
        calls.append(url)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "stream", fake_stream)
    config = {
        "harness": {"default_backend": "ollama"},
        "backends": {
            "ollama": {"enabled": True, "model": "llama3.1", "base_url": "http://localhost:11434"},
        },
    }
    ba = BackendAbstraction(config)
    with pytest.raises(BackendError):
        ba.generate("hi")
    assert calls


def test_anthropic_backend_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BackendError):
        AnthropicBackend({"api_key_env": "ANTHROPIC_API_KEY", "model": "claude-3-5-sonnet-latest"})


def test_anthropic_backend_generate(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def fake_post(url, json, headers, timeout):
        assert url.endswith("/messages")
        assert headers["x-api-key"] == "test-key"
        assert headers["anthropic-version"]
        return _FakeResponse({"content": [{"type": "text", "text": "hi from "}, {"type": "text", "text": "claude"}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = AnthropicBackend({"api_key_env": "ANTHROPIC_API_KEY", "model": "claude-3-5-sonnet-latest"})
    response = backend.generate("hi")
    assert response.text == "hi from claude"
    assert response.backend_name == "anthropic"


def test_anthropic_backend_raises_on_unexpected_shape(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def fake_post(url, json, headers, timeout):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = AnthropicBackend({"api_key_env": "ANTHROPIC_API_KEY", "model": "claude-3-5-sonnet-latest"})
    with pytest.raises(BackendError):
        backend.generate("hi")


def test_openrouter_backend_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(BackendError):
        OpenRouterBackend({"api_key_env": "OPENROUTER_API_KEY", "model": "meta-llama/llama-3.1-70b-instruct"})


def test_openrouter_backend_generate(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def fake_post(url, json, headers, timeout):
        assert url.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer test-key"
        return _FakeResponse({"choices": [{"message": {"content": "hi from openrouter"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = OpenRouterBackend({"api_key_env": "OPENROUTER_API_KEY", "model": "meta-llama/llama-3.1-70b-instruct"})
    response = backend.generate("hi")
    assert response.text == "hi from openrouter"
    assert response.backend_name == "openrouter"


def test_backend_abstraction_falls_back_to_second_backend(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    seen = []

    def fake_stream(method, url, **kwargs):
        seen.append(url)
        raise httpx.ConnectError("ollama down")

    def fake_post(url, json, **kwargs):
        seen.append(url)
        return _FakeResponse({"choices": [{"message": {"content": "served by openai"}}]})

    monkeypatch.setattr(httpx, "stream", fake_stream)
    monkeypatch.setattr(httpx, "post", fake_post)
    config = {
        "harness": {"default_backend": "ollama"},
        "backends": {
            "ollama": {"enabled": True, "model": "llama3.1", "base_url": "http://localhost:11434"},
            "openai": {"enabled": True, "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"},
        },
    }
    ba = BackendAbstraction(config)
    assert ba.order[0] == "ollama"
    response = ba.generate("hi")
    assert response.text == "served by openai"
    assert response.backend_name == "openai"
    assert any("11434" in url for url in seen)


def test_backend_abstraction_pinned_backend_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_post(url, json, **kwargs):
        raise httpx.ConnectError("openai down")

    monkeypatch.setattr(httpx, "post", fake_post)
    config = {
        "harness": {"default_backend": "ollama"},
        "backends": {
            "ollama": {"enabled": True, "model": "llama3.1", "base_url": "http://localhost:11434"},
            "openai": {"enabled": True, "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"},
        },
    }
    ba = BackendAbstraction(config)
    with pytest.raises(BackendError):
        ba.generate("hi", backend="openai")


def test_backend_abstraction_no_enabled_backends_raises():
    config = {"harness": {"default_backend": "ollama"}, "backends": {}}
    ba = BackendAbstraction(config)
    with pytest.raises(BackendError):
        ba.generate("hi")
