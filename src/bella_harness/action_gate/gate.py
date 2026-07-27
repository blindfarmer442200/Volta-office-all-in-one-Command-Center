"""Exact, expiring, one-use authorization for Bella's mock action sandbox."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from bella_harness.action_gate.canonical import action_fingerprint
from bella_harness.action_gate.models import (
    ActionAuditEvent,
    ActionAuthorization,
    ActionExecution,
    ActionGateError,
    ActionPreview,
    ActionSpec,
    ActionStatus,
    MOCK_CONNECTOR,
    risk_meets_floor,
)
from bella_harness.operator import OperatorDecision


Clock = Callable[[], datetime]
TokenFactory = Callable[[], str]
IdFactory = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _capability_hash(capability: str) -> str:
    return hashlib.sha256(capability.encode("utf-8")).hexdigest()


@dataclass
class _PreviewState:
    preview: ActionPreview
    token_hash: str | None = None
    authorization_expires_at: str | None = None


class ActionGate:
    """In-memory Action Gate for a side-effect-free mock connector.

    Raw capabilities are returned once to the caller and never retained. Only a
    SHA-256 digest is stored for one-time verification. This class deliberately
    supports no email, calendar, payment, file, account, or device connector.
    """

    def __init__(
        self,
        *,
        preview_ttl_seconds: int = 15 * 60,
        authorization_ttl_seconds: int = 5 * 60,
        clock: Clock = _utc_now,
        token_factory: TokenFactory | None = None,
        id_factory: IdFactory | None = None,
    ):
        if not 1 <= preview_ttl_seconds <= 15 * 60:
            raise ActionGateError("preview TTL must be between 1 and 900 seconds")
        if not 1 <= authorization_ttl_seconds <= 5 * 60:
            raise ActionGateError("authorization TTL must be between 1 and 300 seconds")
        self.preview_ttl_seconds = preview_ttl_seconds
        self.authorization_ttl_seconds = authorization_ttl_seconds
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._id_factory = id_factory or (lambda: secrets.token_hex(16))
        self._states: dict[str, _PreviewState] = {}
        self._audit: list[ActionAuditEvent] = []
        self._lock = threading.RLock()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _append_audit(
        self,
        event_type: str,
        preview_id: str,
        details: dict | None = None,
    ) -> ActionAuditEvent:
        details = details or {}
        previous_hash = self._audit[-1].event_hash if self._audit else "0" * 64
        sequence = len(self._audit) + 1
        occurred_at = _iso(self._now())
        material = json.dumps(
            {
                "sequence": sequence,
                "event_type": event_type,
                "preview_id": preview_id,
                "occurred_at": occurred_at,
                "previous_hash": previous_hash,
                "details": details,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        event_hash = hashlib.sha256(material).hexdigest()
        event = ActionAuditEvent(
            sequence=sequence,
            event_type=event_type,
            preview_id=preview_id,
            occurred_at=occurred_at,
            previous_hash=previous_hash,
            event_hash=event_hash,
            details=details,
        )
        self._audit.append(event)
        return event

    def _require_state(self, preview_id: str) -> _PreviewState:
        state = self._states.get(preview_id)
        if state is None:
            raise ActionGateError("unknown action preview")
        return state

    def _expire_if_needed(self, state: _PreviewState) -> None:
        if state.preview.status in {ActionStatus.EXECUTED, ActionStatus.REVOKED, ActionStatus.EXPIRED}:
            return
        now = self._now()
        preview_deadline = _parse_iso(state.preview.expires_at)
        authorization_deadline = (
            _parse_iso(state.authorization_expires_at)
            if state.authorization_expires_at is not None
            else None
        )
        expired = now >= preview_deadline or (
            state.preview.status == ActionStatus.AUTHORIZED
            and authorization_deadline is not None
            and now >= authorization_deadline
        )
        if expired:
            state.preview = replace(state.preview, status=ActionStatus.EXPIRED)
            state.token_hash = None
            state.authorization_expires_at = None
            self._append_audit("action_expired", state.preview.id)

    def prepare(self, spec: ActionSpec, decision: OperatorDecision) -> ActionPreview:
        """Create an exact preview only for an approval-gated operator decision."""
        with self._lock:
            if spec.connector != MOCK_CONNECTOR:
                raise ActionGateError("only the mock action sandbox is supported")
            if not decision.approval_required:
                raise ActionGateError(
                    "operator decision does not require approval; refusing to turn a "
                    "draft or low-risk request into an executable action"
                )
            if not risk_meets_floor(decision.risk_level, spec.required_risk):
                raise ActionGateError(
                    f"operator risk {decision.risk_level.value!r} is below the "
                    f"{spec.required_risk.value!r} floor for {spec.kind.value!r}"
                )

            now = self._now()
            preview_id = self._id_factory()
            if not isinstance(preview_id, str) or not preview_id:
                raise ActionGateError("preview id factory returned an invalid id")
            if preview_id in self._states:
                raise ActionGateError("preview id collision")

            fingerprint = action_fingerprint(spec)
            preview = ActionPreview(
                id=preview_id,
                spec=spec,
                fingerprint=fingerprint,
                risk_level=decision.risk_level,
                created_at=_iso(now),
                expires_at=_iso(now + timedelta(seconds=self.preview_ttl_seconds)),
                status=ActionStatus.PREVIEW,
                summary=(
                    f"Simulate {spec.kind.value} through {MOCK_CONNECTOR} "
                    f"for target {spec.target!r}. No outside side effects are possible."
                ),
            )
            self._states[preview_id] = _PreviewState(preview=preview)
            self._append_audit(
                "action_preview_created",
                preview_id,
                {
                    "fingerprint": fingerprint,
                    "kind": spec.kind.value,
                    "connector": spec.connector,
                    "risk_level": decision.risk_level.value,
                },
            )
            return preview

    def get_preview(self, preview_id: str) -> ActionPreview:
        with self._lock:
            state = self._require_state(preview_id)
            self._expire_if_needed(state)
            return state.preview

    def authorize(
        self,
        preview_id: str,
        fingerprint: str,
        *,
        owner_confirmed: bool,
    ) -> ActionAuthorization:
        """Issue one short-lived capability after explicit owner confirmation."""
        with self._lock:
            state = self._require_state(preview_id)
            self._expire_if_needed(state)
            if owner_confirmed is not True:
                raise ActionGateError("explicit owner confirmation is required")
            if state.preview.status != ActionStatus.PREVIEW:
                raise ActionGateError(
                    f"preview cannot be authorized from status {state.preview.status.value!r}"
                )
            if not hmac.compare_digest(state.preview.fingerprint, fingerprint):
                raise ActionGateError("reviewed fingerprint does not match the preview")

            capability = self._token_factory()
            if not isinstance(capability, str) or len(capability) < 32:
                raise ActionGateError("capability factory returned an invalid token")
            now = self._now()
            auth_expires = min(
                now + timedelta(seconds=self.authorization_ttl_seconds),
                _parse_iso(state.preview.expires_at),
            )
            state.token_hash = _capability_hash(capability)
            state.authorization_expires_at = _iso(auth_expires)
            state.preview = replace(state.preview, status=ActionStatus.AUTHORIZED)
            self._append_audit(
                "action_authorized",
                preview_id,
                {
                    "fingerprint": fingerprint,
                    "authorization_expires_at": state.authorization_expires_at,
                    "raw_capability_stored": False,
                },
            )
            return ActionAuthorization(
                preview_id=preview_id,
                fingerprint=fingerprint,
                capability=capability,
                authorized_at=_iso(now),
                expires_at=state.authorization_expires_at,
            )

    def execute_sandbox(
        self,
        preview_id: str,
        spec: ActionSpec,
        fingerprint: str,
        capability: str,
    ) -> ActionExecution:
        """Consume one capability and return a side-effect-free simulation result."""
        with self._lock:
            state = self._require_state(preview_id)
            self._expire_if_needed(state)
            if state.preview.status != ActionStatus.AUTHORIZED:
                raise ActionGateError(
                    f"preview cannot execute from status {state.preview.status.value!r}"
                )
            if action_fingerprint(spec) != state.preview.fingerprint:
                raise ActionGateError("action payload changed after review")
            if not hmac.compare_digest(state.preview.fingerprint, fingerprint):
                raise ActionGateError("execution fingerprint does not match the preview")
            if state.token_hash is None:
                raise ActionGateError("authorization capability is missing or already consumed")
            if not isinstance(capability, str) or not hmac.compare_digest(
                state.token_hash,
                _capability_hash(capability),
            ):
                raise ActionGateError("invalid one-time capability")

            # Consume before constructing the result so retries cannot replay.
            state.token_hash = None
            state.authorization_expires_at = None
            state.preview = replace(state.preview, status=ActionStatus.EXECUTED)
            executed_at = _iso(self._now())
            execution = ActionExecution(
                preview_id=preview_id,
                fingerprint=fingerprint,
                executed_at=executed_at,
                connector=spec.connector,
                kind=spec.kind,
                target=spec.target,
                simulated=True,
                side_effects_performed=False,
                result={
                    "status": "simulated",
                    "sideEffectsPerformed": False,
                    "message": "The exact action passed the gate and was simulated locally.",
                },
            )
            self._append_audit(
                "action_executed_in_sandbox",
                preview_id,
                {
                    "fingerprint": fingerprint,
                    "kind": spec.kind.value,
                    "connector": spec.connector,
                    "simulated": True,
                    "side_effects_performed": False,
                },
            )
            return execution

    def revoke(self, preview_id: str) -> ActionPreview:
        with self._lock:
            state = self._require_state(preview_id)
            self._expire_if_needed(state)
            if state.preview.status in {ActionStatus.EXECUTED, ActionStatus.EXPIRED}:
                raise ActionGateError(
                    f"preview cannot be revoked from status {state.preview.status.value!r}"
                )
            if state.preview.status == ActionStatus.REVOKED:
                return state.preview
            state.token_hash = None
            state.authorization_expires_at = None
            state.preview = replace(state.preview, status=ActionStatus.REVOKED)
            self._append_audit("action_revoked", preview_id)
            return state.preview

    def audit_events(self) -> tuple[ActionAuditEvent, ...]:
        with self._lock:
            return tuple(self._audit)

    def verify_audit_chain(self) -> bool:
        with self._lock:
            previous_hash = "0" * 64
            for expected_sequence, event in enumerate(self._audit, start=1):
                if event.sequence != expected_sequence or event.previous_hash != previous_hash:
                    return False
                material = json.dumps(
                    {
                        "sequence": event.sequence,
                        "event_type": event.event_type,
                        "preview_id": event.preview_id,
                        "occurred_at": event.occurred_at,
                        "previous_hash": event.previous_hash,
                        "details": event.details,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                expected_hash = hashlib.sha256(material).hexdigest()
                if not hmac.compare_digest(expected_hash, event.event_hash):
                    return False
                previous_hash = event.event_hash
            return True
