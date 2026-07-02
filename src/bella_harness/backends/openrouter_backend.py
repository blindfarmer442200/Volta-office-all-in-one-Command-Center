"""OpenRouter backend: OpenAI-compatible chat completions API, many models behind one key."""

from __future__ import annotations

import httpx

from bella_harness.backends.base import Backend, BackendError, BackendResponse
from bella_harness.config import resolve_api_key


class OpenRouterBackend(Backend):
    name = "openrouter"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://openrouter.ai/api/v1").rstrip("/")
        self.api_key = resolve_api_key(config)
        if not self.api_key:
            raise BackendError(
                f"OpenRouter backend enabled but {config.get('api_key_env', 'OPENROUTER_API_KEY')} is not set"
            )

    def generate(self, prompt: str, **kwargs) -> BackendResponse:
        model = kwargs.get("model", self.model)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if "max_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_tokens"]

        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendError(f"openrouter request failed: {exc}") from exc

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise BackendError(f"unexpected openrouter response shape: {data}") from exc

        return BackendResponse(text=text, backend_name=self.name, model=model, raw=data)
