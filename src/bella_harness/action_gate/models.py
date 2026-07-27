"""Typed contracts for Bella's exact, one-use Action Gate."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from bella_harness.operator import RiskLevel


MAX_TARGET_CHARS = 500
MAX_PAYLOAD_BYTES = 16_384
MOCK_CONNECTOR = "mock_action_sandbox"
_SECRET_KEY_RE = re.compile(
    r"(api_?key|secret|token|password|passwd|credential|private_?key)",
    re.IGNORECASE,
)


class ActionGateError(RuntimeError):
    """Raised when an action cannot safely move through the gate."""


class ActionValidationError(ActionGateError, ValueError):
    """Raised when an action specification is malformed or unsafe."""


class ActionKind(str, Enum):
    SEND_MESSAGE = "send_message"
    CALENDAR_CHANGE = "calendar_change"
    FILE_CHANGE = "file_change"
    PAYMENT = "payment"
    ACCOUNT_CHANGE = "account_change"
    DEVICE_CONTROL = "device_control"


class ActionStatus(str, Enum):
    PREVIEW = "preview"
    AUTHORIZED = "authorized"
    EXECUTED = "executed"
    REVOKED = "revoked"
    EXPIRED = "expired"


ACTION_RISK_FLOOR: dict[ActionKind, RiskLevel] = {
    ActionKind.SEND_MESSAGE: RiskLevel.HIGH,
    ActionKind.CALENDAR_CHANGE: RiskLevel.HIGH,
    ActionKind.FILE_CHANGE: RiskLevel.HIGH,
    ActionKind.PAYMENT: RiskLevel.CRITICAL,
    ActionKind.ACCOUNT_CHANGE: RiskLevel.CRITICAL,
    ActionKind.DEVICE_CONTROL: RiskLevel.CRITICAL,
}

_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


def risk_meets_floor(actual: RiskLevel, required: RiskLevel) -> bool:
    return _RISK_ORDER[actual] >= _RISK_ORDER[required]


def _validate_json_value(value: Any, path: str = "payload") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ActionValidationError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ActionValidationError(f"{path} keys must be non-empty strings")
            if _SECRET_KEY_RE.search(key):
                raise ActionValidationError(
                    f"{path}.{key} looks secret-bearing; capabilities and credentials "
                    "must never be embedded in an action payload"
                )
            _validate_json_value(item, f"{path}.{key}")
        return
    raise ActionValidationError(
        f"{path} contains unsupported type {type(value).__name__}; use JSON values only"
    )


@dataclass(frozen=True)
class ActionSpec:
    """Exact action data reviewed by the human before sandbox execution."""

    kind: ActionKind
    target: str
    payload: dict[str, Any]
    connector: str = MOCK_CONNECTOR

    def __post_init__(self) -> None:
        try:
            kind = self.kind if isinstance(self.kind, ActionKind) else ActionKind(self.kind)
        except ValueError as exc:
            raise ActionValidationError(str(exc)) from exc
        object.__setattr__(self, "kind", kind)

        if self.connector != MOCK_CONNECTOR:
            raise ActionValidationError(
                f"unsupported connector {self.connector!r}; only {MOCK_CONNECTOR!r} is allowed"
            )
        if not isinstance(self.target, str) or not self.target.strip():
            raise ActionValidationError("action target must be a non-empty string")
        target = self.target.strip()
        if len(target) > MAX_TARGET_CHARS:
            raise ActionValidationError("action target is too long")
        object.__setattr__(self, "target", target)

        if not isinstance(self.payload, dict):
            raise ActionValidationError("action payload must be a JSON object")
        _validate_json_value(self.payload)
        try:
            encoded = json.dumps(
                self.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ActionValidationError("action payload is not canonical JSON") from exc
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise ActionValidationError(
                f"action payload exceeds the {MAX_PAYLOAD_BYTES}-byte limit"
            )

    @property
    def required_risk(self) -> RiskLevel:
        return ACTION_RISK_FLOOR[self.kind]


@dataclass(frozen=True)
class ActionPreview:
    id: str
    spec: ActionSpec
    fingerprint: str
    risk_level: RiskLevel
    created_at: str
    expires_at: str
    status: ActionStatus = ActionStatus.PREVIEW
    summary: str = ""


@dataclass(frozen=True)
class ActionAuthorization:
    preview_id: str
    fingerprint: str
    capability: str
    authorized_at: str
    expires_at: str


@dataclass(frozen=True)
class ActionExecution:
    preview_id: str
    fingerprint: str
    executed_at: str
    connector: str
    kind: ActionKind
    target: str
    simulated: bool = True
    side_effects_performed: bool = False
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionAuditEvent:
    sequence: int
    event_type: str
    preview_id: str
    occurred_at: str
    previous_hash: str
    event_hash: str
    details: dict[str, Any] = field(default_factory=dict)
