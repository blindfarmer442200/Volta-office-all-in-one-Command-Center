"""Facade for deterministic Bella identity, mode, risk, and prompt policy."""

from __future__ import annotations

from bella_harness.operator.context import build_operator_prompt
from bella_harness.operator.models import BellaMode, OperatorDecision, OperatorEnvelope
from bella_harness.operator.profile import BellaProfile, DEFAULT_BELLA_PROFILE
from bella_harness.operator.risk import classify_request


class BellaOperator:
    """Prepare a model prompt without performing or authorizing actions."""

    def __init__(self, profile: BellaProfile = DEFAULT_BELLA_PROFILE):
        self.profile = profile

    def decide(
        self,
        original_request: str,
        mode: str | BellaMode = BellaMode.DEFAULT,
    ) -> OperatorDecision:
        return classify_request(original_request, mode=mode)

    def wrap(
        self,
        request_context: str,
        decision: OperatorDecision,
    ) -> OperatorEnvelope:
        return build_operator_prompt(request_context, decision, self.profile)

    def build_prompt(
        self,
        request_context: str,
        *,
        original_request: str,
        mode: str | BellaMode = BellaMode.DEFAULT,
    ) -> OperatorEnvelope:
        decision = self.decide(original_request, mode=mode)
        return self.wrap(request_context, decision)
