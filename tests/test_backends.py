"""Backend transport, credentials, fallback, and cloud-egress tests."""

from __future__ import annotations

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


def _ollama_config(**overrides):
    config = {
        "enabled": True,
        "base_url": "http://localhost:11434",
        "model": "llama3.1",
    }
    config.update(overrides)
    return config


def _openai_config():
    return {
        "enabled": True,
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
    }


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
    response = OllamaBackend(_ollama_config()).generate("hi")
    assert response.text == "hello there"
    assert response.backend_name == "ollama"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/generate")
    assert captured["follow_redirects"] is False


def test_ollama_backend_raises_backend_error_on_http_failure(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "stream",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    with pytest.raises(BackendError):
        OllamaBackend(_ollama_config()).generate("hi")


def test_ollama_rejects_redirect_malformed_json_and_oversized_response(monkeypatch):
    backend = OllamaBackend(_ollama_config(max_response_bytes=1024))

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
    unsafe_urls = [
        "https://ollama.example.com",
        "http://user:pass@localhost:11434",
        "http://localhost:11434/prefix",
        "http://localhost:11434?query=yes",
        "http://8.8.8.8:11434",
    ]
    for base_url in unsafe_urls:
        with pytest.raises(BackendError, match="unsafe Ollama endpoint"):
            OllamaBackend(_ollama_config(base_url=base_url))


def test_ollama_accepts_loopback_and_explicitly_approved_private_http():
    assert OllamaBackend(_ollama_config(base_url="http://127.0.0.1:11434")).base_url == (
        "http://127.0.0.1:11434"
    )
    assert OllamaBackend(
        _ollama_config(
            base_url="http://192.168.1.20:11434",
            allow_insecure_private_http=True,
        )
    ).base_url == "http://192.168.1.20:11434"
    assert OllamaBackend(
        _ollama_config(
            base_url="http://[fd00::1]:11434/",
            allow_insecure_private_http=True,
        )
    ).base_url == "http://[fd00::1]:11434"


def test_ollama_prompt_model_output_timeout_and_temperature_bounds(monkeypatch):
    backend = OllamaBackend(
        _ollama_config(max_prompt_chars=1000, max_output_chars=1000)
    )
    with pytest.raises(BackendError, match="prompt exceeds"):
        backend.generate("x" * 1001)
    with pytest.raises(BackendError, match="control characters"):
        backend.generate("hi", model="bad\nmodel")
    with pytest.raises(BackendError, match="temperature"):
        backend.generate("hi", temperature=True)
    with pytest.raises(BackendError, match="timeout_seconds"):
        OllamaBackend(_ollama_config(timeout_seconds=0))

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
    assert OllamaBackend(_ollama_config()).health_check()
    assert captured == {
        "method": "GET",
        "url": "http://localhost:11434/api/tags",
        "payload": None,
    }


def test_openai_backend_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(BackendError):
        OpenAIBackend(_openai_config())


def test_openai_backend_generate(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_post(url, json, headers, timeout):
        assert headers["Authorization"] == "Bearer test-key"
        return _FakeResponse({"choices": [{"message": {"content": "hi from openai"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    response = OpenAIBackend(_openai_config()).generate("hi")
    assert response.text == "hi from openai"


def test_anthropic_backend_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BackendError):
        AnthropicBackend(
            {"api_key_env": "ANTHROPIC_API_KEY", "model": "claude-3-5-sonnet-latest"}
        )


def test_anthropic_backend_generate_and_shape_validation(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def fake_post(url, json, headers, timeout):
        assert url.endswith("/messages")
        assert headers["x-api-key"] == "test-key"
        return _FakeResponse(
            {"content": [{"type": "text", "text": "hi "}, {"type": "text", "text": "there"}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = AnthropicBackend(
        {"api_key_env": "ANTHROPIC_API_KEY", "model": "claude-3-5-sonnet-latest"}
    )
    assert backend.generate("hi").text == "hi there"

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _FakeResponse({"unexpected": "shape"}),
    )
    with pytest.raises(BackendError):
        backend.generate("hi")


def test_openrouter_backend_requires_api_key_and_generates(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config = {
        "api_key_env": "OPENROUTER_API_KEY",
        "model": "meta-llama/llama-3.1-70b-instruct",
    }
    with pytest.raises(BackendError):
        OpenRouterBackend(config)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def fake_post(url, json, headers, timeout):
        assert url.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer test-key"
        return _FakeResponse({"choices": [{"message": {"content": "router reply"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    assert OpenRouterBackend(config).generate("hi").text == "router reply"


def test_backend_abstraction_rejects_nonboolean_cloud_fallback():
    with pytest.raises(BackendError, match="allow_cloud_fallback must be boolean"):
        BackendAbstraction(
            {
                "harness": {
                    "default_backend": "ollama",
                    "allow_cloud_fallback": "yes",
                },
                "backends": {"ollama": _ollama_config()},
            }
        )


def test_local_failure_does_not_call_cloud_without_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    cloud_called = False

    def fake_stream(*args, **kwargs):
        raise httpx.ConnectError("ollama down")

    def fake_post(*args, **kwargs):
        nonlocal cloud_called
        cloud_called = True
        return _FakeResponse({"choices": [{"message": {"content": "cloud"}}]})

    monkeypatch.setattr(httpx, "stream", fake_stream)
    monkeypatch.setattr(httpx, "post", fake_post)
    abstraction = BackendAbstraction(
        {
            "harness": {"default_backend": "ollama"},
            "backends": {
                "ollama": _ollama_config(),
                "openai": _openai_config(),
            },
        }
    )
    assert abstraction.order == ["ollama", "openai"]
    assert abstraction.automatic_order == ["ollama"]
    with pytest.raises(BackendError, match="cloud fallback is disabled"):
        abstraction.generate("private prompt")
    assert cloud_called is False


def test_local_failure_can_use_cloud_after_explicit_opt_in(monkeypatch):
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
    abstraction = BackendAbstraction(
        {
            "harness": {
                "default_backend": "ollama",
                "allow_cloud_fallback": True,
            },
            "backends": {
                "ollama": _ollama_config(),
                "openai": _openai_config(),
            },
        }
    )
    assert abstraction.automatic_order == ["ollama", "openai"]
    response = abstraction.generate("approved cloud-routable prompt")
    assert response.text == "served by openai"
    assert response.backend_name == "openai"
    assert any("11434" in url for url in seen)


def test_explicit_pinned_cloud_backend_remains_an_explicit_route(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _FakeResponse(
            {"choices": [{"message": {"content": "explicit cloud"}}]}
        ),
    )
    abstraction = BackendAbstraction(
        {
            "harness": {
                "default_backend": "ollama",
                "allow_cloud_fallback": False,
            },
            "backends": {
                "ollama": _ollama_config(),
                "openai": _openai_config(),
            },
        }
    )
    response = abstraction.generate("explicit route", backend="openai")
    assert response.text == "explicit cloud"


def test_pinned_backend_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    abstraction = BackendAbstraction(
        {
            "harness": {"default_backend": "ollama"},
            "backends": {
                "ollama": _ollama_config(),
                "openai": _openai_config(),
            },
        }
    )
    with pytest.raises(BackendError):
        abstraction.generate("hi", backend="openai")


def test_default_cloud_backend_is_an_explicit_cloud_configuration(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _FakeResponse(
            {"choices": [{"message": {"content": "cloud default"}}]}
        ),
    )
    abstraction = BackendAbstraction(
        {
            "harness": {
                "default_backend": "openai",
                "allow_cloud_fallback": False,
            },
            "backends": {
                "ollama": _ollama_config(),
                "openai": _openai_config(),
            },
        }
    )
    assert abstraction.automatic_order[0] == "openai"
    assert abstraction.generate("hi").text == "cloud default"


def test_no_enabled_or_unknown_pinned_backend_raises():
    abstraction = BackendAbstraction(
        {"harness": {"default_backend": "ollama"}, "backends": {}}
    )
    with pytest.raises(BackendError, match="no backends"):
        abstraction.generate("hi")
    with pytest.raises(BackendError, match="not enabled"):
        abstraction.generate("hi", backend="openai")
