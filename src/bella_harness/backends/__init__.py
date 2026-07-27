"""Backend construction and privacy-aware fallback routing."""

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
LOCAL_BACKENDS = frozenset({"ollama"})


class BackendAbstraction:
    """Build enabled backends and enforce the configured egress boundary.

    The configured default backend is tried first. When that default is local,
    cloud fallback is disabled unless ``harness.allow_cloud_fallback`` is
    explicitly true. A caller may still pin a specifically enabled cloud
    backend, which is treated as an explicit routing decision.
    """

    def __init__(self, config: dict):
        self.config = config
        backends_config = config.get("backends", {}) or {}
        harness_config = config.get("harness", {}) or {}
        default_name = harness_config.get("default_backend")
        allow_cloud_fallback = harness_config.get("allow_cloud_fallback", False)
        if not isinstance(allow_cloud_fallback, bool):
            raise BackendError("harness.allow_cloud_fallback must be boolean")
        self.allow_cloud_fallback = allow_cloud_fallback

        names = [
            name
            for name, backend_config in backends_config.items()
            if isinstance(backend_config, dict) and backend_config.get("enabled")
        ]
        if default_name in names:
            names.remove(default_name)
            names.insert(0, default_name)

        self._order = names
        self._instances: dict[str, Backend] = {}
        for name in names:
            backend_class = BACKEND_CLASSES.get(name)
            if backend_class is None:
                continue
            self._instances[name] = backend_class(backends_config[name])

    @property
    def order(self) -> list[str]:
        return list(self._order)

    @property
    def automatic_order(self) -> list[str]:
        """Return the backends eligible for an unpinned request."""
        if not self._order:
            return []
        default_name = self._order[0]
        if default_name in LOCAL_BACKENDS and not self.allow_cloud_fallback:
            return [name for name in self._order if name in LOCAL_BACKENDS]
        return list(self._order)

    def get(self, name: str) -> Backend:
        try:
            return self._instances[name]
        except KeyError as exc:
            raise BackendError(f"backend {name!r} is not enabled") from exc

    def generate(
        self,
        prompt: str,
        backend: str | None = None,
        **kwargs,
    ) -> BackendResponse:
        """Generate through an explicit backend or the privacy-aware fallback order."""
        if backend:
            return self.get(backend).generate(prompt, **kwargs)

        candidates = self.automatic_order
        if not candidates:
            raise BackendError("no backends are enabled in configuration")

        last_error: Exception | None = None
        for name in candidates:
            try:
                return self._instances[name].generate(prompt, **kwargs)
            except BackendError as exc:
                last_error = exc

        cloud_was_suppressed = (
            not self.allow_cloud_fallback
            and bool(self._order)
            and self._order[0] in LOCAL_BACKENDS
            and any(name not in LOCAL_BACKENDS for name in self._order)
        )
        if cloud_was_suppressed:
            raise BackendError(
                "local backends failed; cloud fallback is disabled to prevent "
                f"unapproved data egress; last error: {last_error}"
            )
        raise BackendError(f"all eligible backends failed; last error: {last_error}")


__all__ = [
    "Backend",
    "BackendAbstraction",
    "BackendError",
    "BackendResponse",
    "BACKEND_CLASSES",
    "LOCAL_BACKENDS",
]
