"""The orchestrator: deterministic gate, Mind Trace recall, then LLM backend.

Memory is intentionally inserted only after the input gate defers a request to
an LLM. Blocked and deterministic-answerable requests never read the memory
store. The model's response still passes through output scanning before return.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bella_harness.backends import BackendAbstraction, BackendError
from bella_harness.config import load_config
from bella_harness.deterministic.engine import Action, DeterministicEngine
from bella_harness.memory import (
    JsonlMemoryStore,
    MemoryStore,
    MemoryStoreError,
    MindTraceMemoryService,
    NullMemoryStore,
)

REFUSAL_MESSAGE = "I can't help with that request."
BACKEND_UNAVAILABLE_MESSAGE = (
    "I'm unable to reach a model backend right now, so I can't answer that safely."
)
MEMORY_UNAVAILABLE_MESSAGE = (
    "I'm unable to verify the approved memory store right now, so I withheld the "
    "model response rather than answer with uncertain context."
)
OUTPUT_BLOCKED_MESSAGE = (
    "I generated a response but withheld it because it appeared to contain "
    "sensitive or leaked information."
)


@dataclass
class HarnessResult:
    action: Action
    response: str
    category: str | None = None
    backend_used: str | None = None
    handled_deterministically: bool = True
    memory_ids: tuple[str, ...] = field(default_factory=tuple)
    memory_explanations: tuple[str, ...] = field(default_factory=tuple)
    excluded_unsafe_memory_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def memory_used(self) -> bool:
        return bool(self.memory_ids)


class BellaHarness:
    """Deterministic-first request handler with bounded approved-memory recall.

    The deterministic engine remains the first and last security boundary. Mind
    Trace is a read-only context source reached only for requests that defer to
    an LLM. Memory is treated as untrusted data and cannot grant action authority.
    """

    def __init__(
        self,
        config: dict | None = None,
        config_path: str | None = None,
        memory_store: MemoryStore | None = None,
    ):
        self.config = config if config is not None else load_config(config_path)
        self.deterministic_engine = DeterministicEngine(self.config)
        self._backends: BackendAbstraction | None = None
        self._memory_store_override = memory_store
        self._memory: MindTraceMemoryService | None = None

    @property
    def backends(self) -> BackendAbstraction:
        if self._backends is None:
            self._backends = BackendAbstraction(self.config)
        return self._backends

    @property
    def fail_closed(self) -> bool:
        return bool(self.config.get("harness", {}).get("fail_closed", True))

    @property
    def _output_scanning_config(self) -> dict:
        return self.config.get("harness", {}).get("output_scanning", {}) or {}

    @property
    def output_scanning_enabled(self) -> bool:
        # Default on: an unconfigured harness should still screen output.
        return bool(self._output_scanning_config.get("enabled", True))

    @property
    def output_canary(self) -> str | None:
        return self._output_scanning_config.get("canary")

    @property
    def _memory_config(self) -> dict:
        return self.config.get("memory", {}) or {}

    @property
    def memory_enabled(self) -> bool:
        # Empty memory is safe and preserves the original prompt, so enabling the
        # boundary by default does not alter existing deployments.
        return bool(self._memory_config.get("enabled", True))

    @property
    def memory_fail_closed(self) -> bool:
        return bool(self._memory_config.get("fail_closed", True))

    def _memory_content_is_safe(self, content: str) -> bool:
        """Reject memory text that the deterministic input gate classifies BLOCK."""
        return self.deterministic_engine.evaluate(content).action != Action.BLOCK

    @property
    def memory(self) -> MindTraceMemoryService:
        """Lazily construct memory so blocked requests cannot touch its store."""
        if self._memory is None:
            cfg = self._memory_config
            if self._memory_store_override is not None:
                store = self._memory_store_override
            elif cfg.get("store_path"):
                store = JsonlMemoryStore(cfg["store_path"])
            else:
                store = NullMemoryStore()
            self._memory = MindTraceMemoryService(
                store,
                max_results=int(cfg.get("max_results", 5)),
                min_score=int(cfg.get("min_score", 10)),
                max_context_chars=int(cfg.get("max_context_chars", 6_000)),
                max_memory_chars=int(cfg.get("max_memory_chars", 1_200)),
                is_safe_for_context=self._memory_content_is_safe,
            )
        return self._memory

    def handle(self, request_text: str, *, mode: str = "default") -> HarnessResult:
        decision = self.deterministic_engine.evaluate(request_text)

        if decision.action == Action.BLOCK:
            return HarnessResult(
                action=Action.BLOCK,
                response=REFUSAL_MESSAGE,
                category=decision.category,
                handled_deterministically=True,
            )

        if decision.action == Action.ALLOW_DETERMINISTIC:
            return HarnessResult(
                action=Action.ALLOW_DETERMINISTIC,
                response=decision.response or "",
                category=decision.category,
                handled_deterministically=True,
            )

        # DEFER_TO_LLM. Only now may the request read approved memory.
        prompt = request_text
        memory_ids: tuple[str, ...] = ()
        memory_explanations: tuple[str, ...] = ()
        excluded_unsafe_memory_ids: tuple[str, ...] = ()
        if self.memory_enabled:
            try:
                envelope = self.memory.build_prompt(request_text, mode=mode)
                prompt = envelope.prompt
                memory_ids = envelope.memory_ids
                memory_explanations = envelope.explanations
                excluded_unsafe_memory_ids = envelope.excluded_unsafe_ids
            except (MemoryStoreError, OSError, ValueError):
                if self.memory_fail_closed:
                    return HarnessResult(
                        action=Action.BLOCK,
                        response=MEMORY_UNAVAILABLE_MESSAGE,
                        category="memory_unavailable",
                        handled_deterministically=False,
                    )
                # Explicit fail-open mode never passes partial/unverified memory;
                # it uses the original request with no memory instead.
                prompt = request_text

        try:
            backend_response = self.backends.generate(prompt)
        except BackendError:
            if self.fail_closed:
                return HarnessResult(
                    action=Action.BLOCK,
                    response=BACKEND_UNAVAILABLE_MESSAGE,
                    category="backend_unavailable",
                    handled_deterministically=False,
                    memory_ids=memory_ids,
                    memory_explanations=memory_explanations,
                    excluded_unsafe_memory_ids=excluded_unsafe_memory_ids,
                )
            raise

        # Output half of the harness: re-check the model's response before
        # returning it, so leaked secrets / system-prompt content are withheld.
        if self.output_scanning_enabled:
            output_decision = self.deterministic_engine.scan_output(
                backend_response.text, canary=self.output_canary
            )
            if output_decision is not None:
                return HarnessResult(
                    action=Action.BLOCK,
                    response=OUTPUT_BLOCKED_MESSAGE,
                    category=output_decision.category,
                    backend_used=backend_response.backend_name,
                    handled_deterministically=False,
                    memory_ids=memory_ids,
                    memory_explanations=memory_explanations,
                    excluded_unsafe_memory_ids=excluded_unsafe_memory_ids,
                )

        return HarnessResult(
            action=Action.DEFER_TO_LLM,
            response=backend_response.text,
            backend_used=backend_response.backend_name,
            handled_deterministically=False,
            memory_ids=memory_ids,
            memory_explanations=memory_explanations,
            excluded_unsafe_memory_ids=excluded_unsafe_memory_ids,
        )
