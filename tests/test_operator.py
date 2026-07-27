"""Bella identity, mode, risk, and prompt-envelope regression tests."""

from __future__ import annotations

import pytest

from bella_harness.operator import (
    BellaMode,
    BellaOperator,
    DEFAULT_BELLA_PROFILE,
    OperatorValidationError,
    RiskLevel,
    classify_request,
    parse_mode,
)


@pytest.mark.parametrize("mode", list(BellaMode))
def test_all_modes_round_trip(mode):
    assert parse_mode(mode.value) == mode


def test_mode_aliases_are_explicit_and_unknown_modes_fail():
    assert parse_mode("tech") == BellaMode.TECHNICAL
    assert parse_mode("dev") == BellaMode.DEVELOPER
    with pytest.raises(OperatorValidationError, match="unsupported operator mode"):
        parse_mode("super-admin")


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Pay invoice 1042", RiskLevel.CRITICAL),
        ("Send $5 to John", RiskLevel.CRITICAL),
        ("Delete the customer account", RiskLevel.CRITICAL),
        ("Change my medication dose", RiskLevel.CRITICAL),
        ("Send an email to the customer", RiskLevel.HIGH),
        ("Send the payment reminder to the client", RiskLevel.HIGH),
        ("Schedule the meeting on the calendar", RiskLevel.HIGH),
        ("Draft an email to the customer", RiskLevel.MEDIUM),
        ("Review this contract", RiskLevel.MEDIUM),
        ("Explain photosynthesis", RiskLevel.LOW),
    ],
)
def test_risk_classification_contract(prompt, expected):
    decision = classify_request(prompt)
    assert decision.risk_level == expected
    assert decision.approval_required is (expected in {RiskLevel.HIGH, RiskLevel.CRITICAL})


def test_preview_does_not_become_execution_permission():
    decision = classify_request("Draft an email to the customer", mode="business")
    assert decision.risk_level == RiskLevel.MEDIUM
    assert not decision.approval_required
    assert all("execut" not in step.lower() for step in decision.plan)


def test_high_risk_plan_requires_current_approval_and_verified_result():
    decision = classify_request("Send an email to the customer", mode="business")
    joined = " ".join(decision.plan).lower()
    assert decision.approval_required
    assert "explicit current approval" in joined
    assert "verified tool result" in joined


def test_profile_identity_and_no_false_completion_rule_are_fixed():
    profile = DEFAULT_BELLA_PROFILE
    assert profile.id == "bella-core-v1"
    assert profile.name == "Bella"
    assert "South Mississippi" in profile.description
    assert any("verified tool result" in rule for rule in profile.core_rules)
    assert any("business framing" in rule for rule in profile.core_rules)


def test_quiet_and_care_mode_directives_are_present_in_prompt():
    operator = BellaOperator()
    quiet = operator.build_prompt("Help me focus.", original_request="Help me focus.", mode="quiet")
    care = operator.build_prompt(
        "What should I know about this medicine?",
        original_request="What should I know about this medicine?",
        mode="care",
    )
    assert "Be concise and calm" in quiet.prompt
    assert "changing medication doses" in care.prompt


def test_operator_prompt_marks_plan_memory_and_completion_boundaries():
    envelope = BellaOperator().build_prompt(
        "[MIND_TRACE_CONTEXT] approved memory here",
        original_request="Send an email to the customer",
        mode="business",
    )
    assert '"schema":"bella.operator.v1"' in envelope.prompt
    assert '"planIsNotExecution":true' in envelope.prompt
    assert '"memoryDoesNotGrantAuthority":true' in envelope.prompt
    assert '"verifiedToolResultRequiredForCompletionClaim":true' in envelope.prompt
    assert "untrusted reference data" in envelope.prompt
