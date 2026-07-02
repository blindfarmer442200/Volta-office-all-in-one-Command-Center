"""Anthropic backend, using the Messages API."""

from __future__ import annotations

import httpx

from bella_harness.backends.base import Backend, BackendError, BackendResponse
from bella_harness.config import resolve_api_key

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicBackend(Backend):
    name = "anthropic"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://api.anthropic.com/v1").rstrip("/")
        self.api_key = resolve_api_key(config)
        if not self.api_key:
            raise BackendError(
                f"Anthropic backend enabled but {config.get('api_key_env', 'ANTHROPIC_API_KEY')} is not set"
            )

    def generate(self, prompt: str, **kwargs) -> BackendResponse:
        model = kwargs.get("model", self.model)
        payload = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", 1024),
            "messages": [{"role": "user", "content": prompt}],
        }

        try:
            resp = httpx.post(
                f"{self.base_url}/messages",
                json=payload,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendError(f"anthropic request failed: {exc}") from exc

        data = resp.json()
        try:
            text = "".join(block.get("text", "") for block in data["content"])
        except (KeyError, TypeError) as exc:
            raise BackendError(f"unexpected anthropic response shape: {data}") from exc

        return BackendResponse(text=text, backend_name=self.name, model=model, raw=data)
