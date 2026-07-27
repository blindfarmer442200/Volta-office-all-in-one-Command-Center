"""Bella orchestration: deterministic gate, operator, memory, backend, actions.

Memory and operator context are inserted only after the deterministic input gate
defers a request to an LLM. Blocked and deterministic-answerable requests never
read memory or build a model prompt. Consequential actions use a separate exact
Action Gate API and cannot execute through the ordinary response path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bella_harness.action_gate import (
    ActionAuthorization,
    ActionExecution,
    ActionGate,
    ActionGateError,
    ActionPreview,
    ActionSpec,
)
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
from bella_harness.operator import (
    BellaOperator,
    OperatorDecision,
    OperatorValidationError,
)

REFUSAL_MESSAGE = "I can't help with that request."
BACKEND_UNAVAILABLE_MESSAGE = (
    "I'm unable to reach a model backend right now, so I can't answer that safely."
)
MEMORY_UNAVAILABLE_MESSAGE = (
    "I'm unable to verify the approved memory store right now, so I withheld the "
    "model response rather than answer with uncertain context."
)
INVALID_OPERATOR_MODE_MESSAGE = (
    "I can't continue because the requested Bella mode is not recognized."
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
    operator_profile_id: str | None = None
    operator_mode: str | None = None
    risk_level: str | None = None
    approval_required: bool = False
    operator_reasons: tuple[str, ...] = field(default_factory=tuple)
    operator_plan: tuple[str, ...] = field(default_factory=tuple)

    @property
    def memory_used(self) -> bool:
        return bool(self.memory_ids)


class BellaHarness:
    """Deterministic-first assistant with memory, operator, and action boundaries.

    Mind Trace is read-only context. BellaOperator adds model-independent
    identity, mode, risk, accessibility, and approval policy. ActionGate is a
    separate exact-preview protocol limited to a local side-effect-free sandbox.
    None of these layers allow memory or a model response to grant authority.
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
        self._operator: BellaOperator | None = None
        self._action_gate: ActionGate | None = None

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
        return bool(self._output_scanning_config.get("enabled", True))

    @property
    def output_canary(self) -> str | None:
        return self._output_scanning_config.get("canary")

    @property
    def _memory_config(self) -> dict:
        return self.config.get("memory", {}) or {}

    @property
    def memory_enabled(self) -> bool:
        return bool(self._memory_config.get("enabled", True))

    @property
    def memory_fail_closed(self) -> bool:
        return bool(self._memory_config.get("fail_closed", True))

    def _memory_content_is_safe(self, content: str) -> bool:
        return self.deterministic_engine.evaluate(content).action != Action.BLOCK

    @property
    def memory(self) -> MindTraceMemoryService:
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

    @property
    def _operator_config(self) -> dict:
        return self.config.get("operator", {}) or {}

    @property
    def operator_enabled(self) -> bool:
        return bool(self._operator_config.get("enabled", False))

    @property
    def operator(self) -> BellaOperator:
        if self._operator is None:
            self._operator = BellaOperator()
        return self._operator

    @property
    def _action_gate_config(self) -> dict:
        return self.config.get("action_gate", {}) or {}

    @property
    def action_gate_enabled(self) -> bool:
        # Legacy embedded configs remain unchanged unless they opt in. The
        # shipped default config enables only the local mock sandbox.
        return bool(self._action_gate_config.get("enabled", False))

    @property
    def action_gate(self) -> ActionGate:
        if not self.action_gate_enabled:
            raise ActionGateError("Action Gate is disabled")
        if self._action_gate is None:
            cfg = self._action_gate_config
            self._action_gate = ActionGate(
                preview_ttl_seconds=int(cfg.get("preview_ttl_seconds", 15 * 60)),
                authorization_ttl_seconds=int(
                    cfg.get("authorization_ttl_seconds", 5 * 60)
                ),
            )
        return self._action_gate

    def prepare_action(
        self,
        request_text: str,
        spec: ActionSpec,
        *,
        mode: str = "default",
    ) -> ActionPreview:
        """Create an exact sandbox preview through deterministic policy only."""
        input_decision = self.deterministic_engine.evaluate(request_text)
        if input_decision.action == Action.BLOCK:
            raise ActionGateError("blocked requests cannot create action previews")
        if input_decision.action != Action.DEFER_TO_LLM:
            raise ActionGateError(
                "deterministic-answerable requests cannot be upgraded into actions"
            )
        if not self.operator_enabled:
            raise ActionGateError("Bella Operator must be enabled before Action Gate use")
        try:
            operator_decision = self.operator.decide(request_text, mode=mode)
        except OperatorValidationError as exc:
            raise ActionGateError("invalid Bella operator mode") from exc
        return self.action_gate.prepare(spec, operator_decision)

    def authorize_action(
        self,
        preview_id: str,
        fingerprint: str,
        *,
        owner_confirmed: bool,
    ) -> ActionAuthorization:
        return self.action_gate.authorize(
            preview_id,
            fingerprint,
            owner_confirmed=owner_confirmed,
        )

    def execute_sandbox_action(
        self,
        preview_id: str,
        spec: ActionSpec,
        fingerprint: str,
        capability: str,
    ) -> ActionExecution:
        return self.action_gate.execute_sandbox(
            preview_id,
            spec,
            fingerprint,
            capability,
        )

    def revoke_action(self, preview_id: str) -> ActionPreview:
        return self.action_gate.revoke(preview_id)

    @staticmethod
    def _operator_result_fields(
        decision: OperatorDecision | None,
        profile_id: str | None = None,
    ) -> dict:
        if decision is None:
            return {}
        return {
            "operator_profile_id": profile_id,
            "operator_mode": decision.mode.value,
            "risk_level": decision.risk_level.value,
            "approval_required": decision.approval_required,
            "operator_reasons": decision.reasons,
            "operator_plan": decision.plan,
        }

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

        operator_decision: OperatorDecision | None = None
        selected_mode = mode
        if self.operator_enabled:
            try:
                operator_decision = self.operator.decide(request_text, mode=mode)
                selected_mode = operator_decision.mode.value
            except OperatorValidationError:
                return HarnessResult(
                    action=Action.BLOCK,
                    response=INVALID_OPERATOR_MODE_MESSAGE,
                    category="invalid_operator_mode",
                    handled_deterministically=False,
                )

        prompt = request_text
        memory_ids: tuple[str, ...] = ()
        memory_explanations: tuple[str, ...] = ()
        excluded_unsafe_memory_ids: tuple[str, ...] = ()
        if self.memory_enabled:
            try:
                envelope = self.memory.build_prompt(request_text, mode=selected_mode)
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
                        **self._operator_result_fields(operator_decision),
                    )
                prompt = request_text

        operator_profile_id: str | None = None
        if operator_decision is not None:
            operator_envelope = self.operator.wrap(prompt, operator_decision)
            prompt = operator_envelope.prompt
            operator_profile_id = operator_envelope.profile_id

        operator_fields = self._operator_result_fields(
            operator_decision,
            profile_id=operator_profile_id,
        )

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
                    **operator_fields,
                )
            raise

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
                    **operator_fields,
                )

        return HarnessResult(
            action=Action.DEFER_TO_LLM,
            response=backend_response.text,
            backend_used=backend_response.backend_name,
            handled_deterministically=False,
            memory_ids=memory_ids,
            memory_explanations=memory_explanations,
            excluded_unsafe_memory_ids=excluded_unsafe_memory_ids,
            **operator_fields,
        )
