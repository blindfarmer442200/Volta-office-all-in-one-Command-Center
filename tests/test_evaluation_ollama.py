"""Ollama option tests used by Bella's model evaluation gate."""

from __future__ import annotations

import httpx
import pytest

from bella_harness.backends import BackendError
from bella_harness.backends.ollama_backend import OllamaBackend


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"response": "{}"}


def test_ollama_forwards_temperature_zero_for_repeatable_evaluation(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured.update(json)
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = OllamaBackend({"model": "candidate", "base_url": "http://localhost:11434"})
    backend.generate("evaluate", temperature=0)

    assert captured["options"] == {"temperature": 0.0}


def test_ollama_rejects_invalid_temperature_before_network_call(monkeypatch):
    called = False

    def fake_post(url, json, timeout):
        nonlocal called
        called = True
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    backend = OllamaBackend({"model": "candidate"})

    with pytest.raises(BackendError, match="temperature"):
        backend.generate("evaluate", temperature=3)
    assert not called
