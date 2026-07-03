"""BackendAbstraction: build and fall back across configured LLM backends."""

from __future__ import annotations

from bella_harness.backends.anthropic_backend import AnthropicBackend
from bella_harness.backends.base import Backend, BackendError, BackendResponse
from bella_harness.backends.ollama_backend import OllamaBackend
from bella_harness.backends.openai_backend import OpenAIBackend
from bella_harness.backends.openrouter_backend import OpenRouterBackend

BACKEND_CLASSES: dict[str, type[Backend]] = {
    "ollama": OllamaBackend,
    "openai": OpenAIBackend,
    "anthropic": AnthropicBackend,
    "openrouter": OpenRouterBackend,
}


class BackendAbstraction:
    """Builds enabled backends from config and calls them with fallback.

    Backends are tried in order: the configured default_backend first, then
    the remaining enabled backends in config file order. The first backend
    that returns successfully wins; if all fail, the last error is raised.
    """

    def __init__(self, config: dict):
        self.config = config
        backends_config = config.get("backends", {}) or {}
        default_name = config.get("harness", {}).get("default_backend")

        names = [
            name for name, cfg in backends_config.items()
            if isinstance(cfg, dict) and cfg.get("enabled")
        ]
        if default_name in names:
            names.remove(default_name)
            names.insert(0, default_name)

        self._order = names
        self._instances: dict[str, Backend] = {}
        for name in names:
            backend_cls = BACKEND_CLASSES.get(name)
            if backend_cls is None:
                continue
            self._instances[name] = backend_cls(backends_config[name])

    @property
    def order(self) -> list[str]:
        return list(self._order)

    def get(self, name: str) -> Backend:
        return self._instances[name]

    def generate(self, prompt: str, backend: str | None = None, **kwargs) -> BackendResponse:
        """Generate a response, optionally pinned to one backend, else fall back in order."""
        if backend:
            return self._instances[backend].generate(prompt, **kwargs)

        if not self._order:
            raise BackendError("no backends are enabled in configuration")

        last_error: Exception | None = None
        for name in self._order:
            try:
                return self._instances[name].generate(prompt, **kwargs)
            except BackendError as exc:
                last_error = exc
                continue

        raise BackendError(f"all backends failed; last error: {last_error}")


__all__ = [
    "Backend",
    "BackendAbstraction",
    "BackendError",
    "BackendResponse",
    "BACKEND_CLASSES",
]
