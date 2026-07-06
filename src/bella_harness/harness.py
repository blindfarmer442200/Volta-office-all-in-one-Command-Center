"""The orchestrator: routes a request through the deterministic engine first,
falling back to an LLM backend only when the deterministic engine defers.
"""

from __future__ import annotations

from dataclasses import dataclass

from bella_harness.backends import BackendAbstraction, BackendError
from bella_harness.config import load_config
from bella_harness.deterministic.engine import Action, DeterministicEngine

REFUSAL_MESSAGE = "I can't help with that request."
BACKEND_UNAVAILABLE_MESSAGE = (
    "I'm unable to reach a model backend right now, so I can't answer that safely."
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


class BellaHarness:
    """Deterministic-first request handler.

    The deterministic engine resolves as much traffic as it safely can --
    answering trivial requests directly and blocking obvious attacks outright --
    without ever reaching an LLM backend. Only requests it defers on are sent to
    a configured backend, and the model's response is re-scanned on the way out.
    (The exact deterministic-resolution share depends on real traffic mix; the
    red-team report records it for the probe suite rather than asserting a
    fixed percentage here.)
    """

    def __init__(self, config: dict | None = None, config_path: str | None = None):
        self.config = config if config is not None else load_config(config_path)
        self.deterministic_engine = DeterministicEngine(self.config)
        self._backends: BackendAbstraction | None = None

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

    def handle(self, request_text: str) -> HarnessResult:
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

        # DEFER_TO_LLM
        try:
            backend_response = self.backends.generate(request_text)
        except BackendError:
            if self.fail_closed:
                return HarnessResult(
                    action=Action.BLOCK,
                    response=BACKEND_UNAVAILABLE_MESSAGE,
                    category="backend_unavailable",
                    handled_deterministically=False,
                )
            raise

        # Output half of the harness: re-check the model's response before
        # returning it, so leaked secrets / system-prompt content are withheld
        # even when the input cleared the gate.
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
                )

        return HarnessResult(
            action=Action.DEFER_TO_LLM,
            response=backend_response.text,
            backend_used=backend_response.backend_name,
            handled_deterministically=False,
        )
