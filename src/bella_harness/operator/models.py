"""Typed contracts for Bella's deterministic operator layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OperatorValidationError(ValueError):
    """Raised when operator mode or configuration is invalid."""


class BellaMode(str, Enum):
    DEFAULT = "default"
    LIFE = "life"
    HOME = "home"
    BUSINESS = "business"
    TECHNICAL = "technical"
    CARE = "care"
    DEVELOPER = "developer"
    CUSTOMER = "customer"
    QUIET = "quiet"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


MODE_ALIASES = {
    "tech": BellaMode.TECHNICAL,
    "dev": BellaMode.DEVELOPER,
}


def parse_mode(value: str | BellaMode) -> BellaMode:
    """Return one supported mode without silently inventing a fallback."""
    if isinstance(value, BellaMode):
        return value
    if not isinstance(value, str) or not value.strip():
        raise OperatorValidationError("operator mode must be a non-empty string")
    normalized = value.strip().lower()
    if normalized in MODE_ALIASES:
        return MODE_ALIASES[normalized]
    try:
        return BellaMode(normalized)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in BellaMode)
        raise OperatorValidationError(
            f"unsupported operator mode {value!r}; expected one of: {allowed}"
        ) from exc


@dataclass(frozen=True)
class OperatorDecision:
    mode: BellaMode
    risk_level: RiskLevel
    approval_required: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    plan: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OperatorEnvelope:
    prompt: str
    decision: OperatorDecision
    profile_id: str
