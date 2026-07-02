"""Ollama backend: local-first, no API key required."""

from __future__ import annotations

import httpx

from bella_harness.backends.base import Backend, BackendError, BackendResponse


class OllamaBackend(Backend):
    name = "ollama"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get("base_url", "http://localhost:11434").rstrip("/")

    def generate(self, prompt: str, **kwargs) -> BackendResponse:
        payload = {
            "model": kwargs.get("model", self.model),
            "prompt": prompt,
            "stream": False,
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendError(f"ollama request failed: {exc}") from exc

        data = resp.json()
        text = data.get("response", "")
        return BackendResponse(text=text, backend_name=self.name, model=payload["model"], raw=data)
