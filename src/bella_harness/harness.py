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


@dataclass
class HarnessResult:
    action: Action
    response: str
    category: str | None = None
    backend_used: str | None = None
    handled_deterministically: bool = True


class BellaHarness:
    """Deterministic-first request handler.

    ~70-75% of traffic should be resolved by the deterministic engine alone
    (either answered directly or blocked outright) without ever reaching an
    LLM backend. Only requests the deterministic engine defers on are sent
    to a configured backend.
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

        return HarnessResult(
            action=Action.DEFER_TO_LLM,
            response=backend_response.text,
            backend_used=backend_response.backend_name,
            handled_deterministically=False,
        )
