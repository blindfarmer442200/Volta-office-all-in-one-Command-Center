"""Ollama option tests used by Bella's model evaluation gate."""

from __future__ import annotations

import json

import httpx
import pytest

from bella_harness.backends import BackendError
from bella_harness.backends.ollama_backend import OllamaBackend


class _FakeStreamResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload=None):
        self.raw = json.dumps(payload or {"response": "{}"}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield self.raw


def test_ollama_forwards_temperature_zero_for_repeatable_evaluation(monkeypatch):
    captured = {}

    def fake_stream(method, url, json, timeout, follow_redirects):
        captured.update(json)
        return _FakeStreamResponse()

    monkeypatch.setattr(httpx, "stream", fake_stream)
    backend = OllamaBackend({"model": "candidate", "base_url": "http://localhost:11434"})
    backend.generate("evaluate", temperature=0)

    assert captured["options"] == {"temperature": 0.0}


def test_ollama_rejects_invalid_temperature_before_network_call(monkeypatch):
    called = False

    def fake_stream(*args, **kwargs):
        nonlocal called
        called = True
        return _FakeStreamResponse()

    monkeypatch.setattr(httpx, "stream", fake_stream)
    backend = OllamaBackend({"model": "candidate"})

    with pytest.raises(BackendError, match="temperature"):
        backend.generate("evaluate", temperature=3)
    assert not called
