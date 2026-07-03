"""Backend abstraction: a single interface over Ollama, OpenAI, Anthropic, and OpenRouter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class BackendError(RuntimeError):
    """Raised when a backend fails to produce a response."""


@dataclass
class BackendResponse:
    text: str
    backend_name: str
    model: str
    raw: dict | None = None


class Backend(ABC):
    """Common interface every LLM backend must implement."""

    name: str = "backend"

    def __init__(self, config: dict):
        self.config = config
        self.model = config.get("model", "")
        self.timeout_seconds = config.get("timeout_seconds", 60)

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> BackendResponse:
        """Send a prompt to the backend and return its response.

        Must raise BackendError (not a transport-specific exception) on
        failure so callers can uniformly fall back to the next backend.
        """
        raise NotImplementedError

    def health_check(self) -> bool:
        """Best-effort liveness check. Backends may override for a cheaper probe."""
        try:
            self.generate("ping", max_tokens=1)
            return True
        except BackendError:
            return False
