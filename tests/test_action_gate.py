"""Exact-preview, authorization, replay, expiry, intent, and audit tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bella_harness.action_gate import (
    ActionGate,
    ActionGateError,
    ActionKind,
    ActionSpec,
    ActionStatus,
    ActionValidationError,
    action_fingerprint,
)
from bella_harness.operator import BellaMode, OperatorDecision, RiskLevel


class MutableClock:
    def __init__(self):
        self.value = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds: int):
        self.value += timedelta(seconds=seconds)


def _decision(
    risk=RiskLevel.HIGH,
    approval=True,
    reason="external communication",
):
    return OperatorDecision(
        mode=BellaMode.BUSINESS,
        risk_level=risk,
        approval_required=approval,
        reasons=(reason,),
        plan=("preview", "approve", "verify"),
    )


def _message_spec(body="Invoice 1042 is overdue."):
    return ActionSpec(
        kind=ActionKind.SEND_MESSAGE,
        target="customer@example.com",
        payload={"subject": "Invoice 1042", "body": body},
    )


def _gate(clock=None):
    return ActionGate(
        preview_ttl_seconds=60,
        authorization_ttl_seconds=30,
        clock=clock or MutableClock(),
        token_factory=lambda: "c" * 43,
        id_factory=lambda: "preview-1",
    )


def test_fingerprint_is_canonical_and_changes_with_payload():
    first = ActionSpec(
        kind="send_message",
        target="customer@example.com",
        payload={"subject": "Due", "body": "Please pay"},
    )
    reordered = ActionSpec(
        kind="send_message",
        target="customer@example.com",
        payload={"body": "Please pay", "subject": "Due"},
    )
    changed = replace(reordered, payload={"body": "Different", "subject": "Due"})

    assert action_fingerprint(first) == action_fingerprint(reordered)
    assert action_fingerprint(first) != action_fingerprint(changed)


def test_only_mock_connector_and_non_secret_json_payloads_are_allowed():
    with pytest.raises(ActionValidationError, match="only 'mock_action_sandbox'"):
        ActionSpec(
            kind="send_message",
            connector="gmail",
            target="customer@example.com",
            payload={"body": "hello"},
        )

    with pytest.raises(ActionValidationError, match="secret-bearing"):
        ActionSpec(
            kind="send_message",
            target="customer@example.com",
            payload={"api_key": "do-not-store-this"},
        )


def test_draft_or_low_risk_decision_cannot_be_upgraded_into_action():
    gate = _gate()
    with pytest.raises(ActionGateError, match="does not require approval"):
        gate.prepare(_message_spec(), _decision(RiskLevel.MEDIUM, approval=False))


def test_high_risk_cannot_authorize_critical_payment_kind():
    gate = _gate()
    payment = ActionSpec(
        kind=ActionKind.PAYMENT,
        target="invoice-1042",
        payload={"amount": 50, "currency": "USD"},
    )
    with pytest.raises(ActionGateError, match="below the 'critical' floor"):
        gate.prepare(payment, _decision(RiskLevel.HIGH, approval=True))


def test_same_risk_wrong_action_kind_is_rejected():
    gate = _gate()
    calendar = ActionSpec(
        kind=ActionKind.CALENDAR_CHANGE,
        target="calendar-event-1",
        payload={"operation": "reschedule", "time": "2026-07-28T10:00:00-05:00"},
    )
    with pytest.raises(ActionGateError, match="does not authorize action kind"):
        gate.prepare(
            calendar,
            _decision(RiskLevel.HIGH, approval=True, reason="external communication"),
        )


def test_unrecognized_or_non_executable_reason_fails_closed():
    gate = _gate()
    with pytest.raises(ActionGateError, match="does not authorize action kind"):
        gate.prepare(
            _message_spec(),
            _decision(RiskLevel.HIGH, approval=True, reason="unknown reason"),
        )


def test_owner_confirmation_and_exact_fingerprint_are_required():
    gate = _gate()
    preview = gate.prepare(_message_spec(), _decision())

    with pytest.raises(ActionGateError, match="owner confirmation"):
        gate.authorize(preview.id, preview.fingerprint, owner_confirmed=False)
    with pytest.raises(ActionGateError, match="does not match"):
        gate.authorize(preview.id, "0" * 64, owner_confirmed=True)

    authorization = gate.authorize(
        preview.id,
        preview.fingerprint,
        owner_confirmed=True,
    )
    assert len(authorization.capability) >= 32
    assert gate.get_preview(preview.id).status == ActionStatus.AUTHORIZED


def test_raw_capability_is_not_stored_or_written_to_audit():
    gate = _gate()
    preview = gate.prepare(_message_spec(), _decision())
    authorization = gate.authorize(preview.id, preview.fingerprint, owner_confirmed=True)

    state = gate._states[preview.id]  # security invariant inspection
    assert state.token_hash != authorization.capability
    assert authorization.capability not in repr(gate.audit_events())
    assert any(
        event.details.get("raw_capability_stored") is False
        for event in gate.audit_events()
    )


def test_exact_action_executes_once_in_side_effect_free_sandbox():
    gate = _gate()
    spec = _message_spec()
    preview = gate.prepare(spec, _decision())
    authorization = gate.authorize(preview.id, preview.fingerprint, owner_confirmed=True)

    execution = gate.execute_sandbox(
        preview.id,
        spec,
        preview.fingerprint,
        authorization.capability,
    )
    assert execution.simulated
    assert not execution.side_effects_performed
    assert execution.result["sideEffectsPerformed"] is False
    assert gate.get_preview(preview.id).status == ActionStatus.EXECUTED

    with pytest.raises(ActionGateError, match="status 'executed'"):
        gate.execute_sandbox(
            preview.id,
            spec,
            preview.fingerprint,
            authorization.capability,
        )


def test_changed_payload_is_rejected_after_authorization():
    gate = _gate()
    reviewed = _message_spec("Original body")
    preview = gate.prepare(reviewed, _decision())
    authorization = gate.authorize(preview.id, preview.fingerprint, owner_confirmed=True)
    changed = _message_spec("Changed after review")

    with pytest.raises(ActionGateError, match="changed after review"):
        gate.execute_sandbox(
            preview.id,
            changed,
            preview.fingerprint,
            authorization.capability,
        )


def test_preview_and_authorization_expire_fail_closed():
    clock = MutableClock()
    gate = _gate(clock)
    preview = gate.prepare(_message_spec(), _decision())
    clock.advance(61)
    assert gate.get_preview(preview.id).status == ActionStatus.EXPIRED
    with pytest.raises(ActionGateError, match="status 'expired'"):
        gate.authorize(preview.id, preview.fingerprint, owner_confirmed=True)

    clock = MutableClock()
    gate = _gate(clock)
    preview = gate.prepare(_message_spec(), _decision())
    authorization = gate.authorize(preview.id, preview.fingerprint, owner_confirmed=True)
    clock.advance(31)
    with pytest.raises(ActionGateError, match="status 'expired'"):
        gate.execute_sandbox(
            preview.id,
            _message_spec(),
            preview.fingerprint,
            authorization.capability,
        )


def test_revoke_clears_authorization_and_audit_chain_verifies():
    gate = _gate()
    preview = gate.prepare(_message_spec(), _decision())
    gate.authorize(preview.id, preview.fingerprint, owner_confirmed=True)
    revoked = gate.revoke(preview.id)

    assert revoked.status == ActionStatus.REVOKED
    assert gate.verify_audit_chain()
    assert [event.event_type for event in gate.audit_events()] == [
        "action_preview_created",
        "action_authorized",
        "action_revoked",
    ]


def test_audit_tampering_is_detected():
    gate = _gate()
    gate.prepare(_message_spec(), _decision())
    assert gate.verify_audit_chain()
    gate._audit[0].details["kind"] = "payment"
    assert not gate.verify_audit_chain()
