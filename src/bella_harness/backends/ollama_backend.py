"""Hardened local/private Ollama backend."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx

from bella_harness.backends.base import Backend, BackendError, BackendResponse
from bella_harness.backends.network import (
    PrivateEndpointError,
    assert_private_resolution,
    normalize_private_http_base_url,
)


DEFAULT_MAX_PROMPT_CHARS = 128_000
DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
DEFAULT_MAX_OUTPUT_CHARS = 200_000
ABSOLUTE_MAX_RESPONSE_BYTES = 5_000_000


class OllamaBackend(Backend):
    """Local-first Ollama adapter with fail-closed network and size bounds."""

    name = "ollama"

    def __init__(self, config: dict):
        super().__init__(config)
        try:
            self.base_url = normalize_private_http_base_url(
                config.get("base_url", "http://localhost:11434")
            )
        except PrivateEndpointError as exc:
            raise BackendError(f"unsafe Ollama endpoint: {exc}") from exc
        self.host = urlsplit(self.base_url).hostname or ""
        self.max_prompt_chars = self._bounded_int(
            config.get("max_prompt_chars", DEFAULT_MAX_PROMPT_CHARS),
            name="max_prompt_chars",
            minimum=1_000,
            maximum=1_000_000,
        )
        self.max_response_bytes = self._bounded_int(
            config.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES),
            name="max_response_bytes",
            minimum=1_024,
            maximum=ABSOLUTE_MAX_RESPONSE_BYTES,
        )
        self.max_output_chars = self._bounded_int(
            config.get("max_output_chars", DEFAULT_MAX_OUTPUT_CHARS),
            name="max_output_chars",
            minimum=1_000,
            maximum=1_000_000,
        )
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(
            self.timeout_seconds, bool
        ):
            raise BackendError("ollama timeout_seconds must be numeric")
        if not 1 <= float(self.timeout_seconds) <= 300:
            raise BackendError("ollama timeout_seconds must be between 1 and 300")

    @staticmethod
    def _bounded_int(value: object, *, name: str, minimum: int, maximum: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise BackendError(f"ollama {name} must be an integer")
        if not minimum <= value <= maximum:
            raise BackendError(f"ollama {name} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _validate_model(model: object) -> str:
        if not isinstance(model, str) or not model.strip():
            raise BackendError("ollama model must be a non-empty string")
        if len(model) > 200:
            raise BackendError("ollama model tag exceeds 200 characters")
        if any(ord(character) < 32 or ord(character) == 127 for character in model):
            raise BackendError("ollama model tag contains control characters")
        return model.strip()

    def _read_json(self, response: httpx.Response) -> dict:
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                declared = int(content_length)
            except ValueError as exc:
                raise BackendError("ollama returned an invalid Content-Length") from exc
            if declared > self.max_response_bytes:
                raise BackendError("ollama response exceeds the configured byte limit")

        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > self.max_response_bytes:
                raise BackendError("ollama response exceeds the configured byte limit")
        try:
            decoded = bytes(body).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BackendError("ollama response is not valid UTF-8") from exc
        try:
            data = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise BackendError("ollama response is not valid JSON") from exc
        if not isinstance(data, dict):
            raise BackendError("ollama response JSON must be an object")
        return data

    def _request_json(self, method: str, path: str, *, payload: dict | None = None) -> dict:
        try:
            assert_private_resolution(self.host)
            with httpx.stream(
                method,
                f"{self.base_url}{path}",
                json=payload,
                timeout=float(self.timeout_seconds),
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise BackendError("ollama redirects are not allowed")
                response.raise_for_status()
                return self._read_json(response)
        except PrivateEndpointError as exc:
            raise BackendError(f"unsafe Ollama endpoint resolution: {exc}") from exc
        except httpx.HTTPError as exc:
            raise BackendError(f"ollama request failed: {exc}") from exc

    def generate(self, prompt: str, **kwargs) -> BackendResponse:
        if not isinstance(prompt, str):
            raise BackendError("ollama prompt must be a string")
        if len(prompt) > self.max_prompt_chars:
            raise BackendError("ollama prompt exceeds the configured character limit")
        model = self._validate_model(kwargs.get("model", self.model))
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if "temperature" in kwargs:
            temperature = kwargs["temperature"]
            if (
                not isinstance(temperature, (int, float))
                or isinstance(temperature, bool)
                or not 0 <= temperature <= 2
            ):
                raise BackendError("ollama temperature must be a number between 0 and 2")
            payload["options"] = {"temperature": float(temperature)}

        data = self._request_json("POST", "/api/generate", payload=payload)
        text = data.get("response")
        if not isinstance(text, str):
            raise BackendError("ollama response is missing the text response field")
        if len(text) > self.max_output_chars:
            raise BackendError("ollama generated text exceeds the configured character limit")
        return BackendResponse(text=text, backend_name=self.name, model=model, raw=data)

    def health_check(self) -> bool:
        """Check the local service without sending a user prompt."""
        try:
            data = self._request_json("GET", "/api/tags")
        except BackendError:
            return False
        models = data.get("models")
        return isinstance(models, list)
