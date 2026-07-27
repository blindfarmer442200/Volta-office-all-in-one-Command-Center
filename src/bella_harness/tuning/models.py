"""Typed contracts for Bella's human-reviewed correction and tuning loop."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


MAX_ID_CHARS = 200
MAX_PROMPT_CHARS = 32_000
MAX_RESPONSE_CHARS = 64_000
MAX_NOTE_CHARS = 4_000
MAX_MODEL_CHARS = 200
MAX_PROFILE_CHARS = 200


class TuningError(RuntimeError):
    """Base error for the tuning subsystem."""


class TuningValidationError(TuningError, ValueError):
    """Raised when human-reviewed tuning data is malformed or unbounded."""


class FeedbackRating(str, Enum):
    GOOD = "good"
    TOO_SOFT = "too_soft"
    TOO_HARSH = "too_harsh"
    TOO_LONG = "too_long"
    TOO_VAGUE = "too_vague"
    MISSED_POINT = "missed_point"
    WRONG_MEMORY = "wrong_memory"
    UNSAFE_OVERREACH = "unsafe_overreach"

    @property
    def is_positive(self) -> bool:
        return self is FeedbackRating.GOOD


class ExportDisposition(str, Enum):
    SFT_CANDIDATE = "sft_candidate"
    PREFERENCE_CANDIDATE = "preference_candidate"
    EVALUATION_ONLY = "evaluation_only"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TuningValidationError("timestamp must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise TuningValidationError(f"invalid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_text(name: str, value: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TuningValidationError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise TuningValidationError(f"{name} must not be empty")
    if len(value) > maximum:
        raise TuningValidationError(f"{name} exceeds the {maximum:,} character limit")
    return value


def validate_id(name: str, value: str) -> str:
    return _bounded_text(name, value, MAX_ID_CHARS)


@dataclass(frozen=True)
class TuningInteraction:
    id: str
    prompt: str
    original_response: str
    mode: str
    risk_level: str
    profile_id: str
    source_model: str
    created_at: str
    prompt_sha256: str
    original_response_sha256: str

    def __post_init__(self) -> None:
        validate_id("interaction id", self.id)
        _bounded_text("prompt", self.prompt, MAX_PROMPT_CHARS)
        _bounded_text("original response", self.original_response, MAX_RESPONSE_CHARS)
        _bounded_text("mode", self.mode, 80)
        _bounded_text("risk level", self.risk_level, 80)
        _bounded_text("profile id", self.profile_id, MAX_PROFILE_CHARS)
        _bounded_text("source model", self.source_model, MAX_MODEL_CHARS)
        parse_timestamp(self.created_at)
        if self.prompt_sha256 != sha256_text(self.prompt):
            raise TuningValidationError("prompt SHA-256 does not match prompt")
        if self.original_response_sha256 != sha256_text(self.original_response):
            raise TuningValidationError("original-response SHA-256 does not match response")


@dataclass(frozen=True)
class TuningFeedback:
    id: str
    interaction_id: str
    rating: FeedbackRating
    note: str
    created_at: str
    reviewed_by_human: bool = True

    def __post_init__(self) -> None:
        validate_id("feedback id", self.id)
        validate_id("interaction id", self.interaction_id)
        if not isinstance(self.rating, FeedbackRating):
            try:
                object.__setattr__(self, "rating", FeedbackRating(self.rating))
            except ValueError as exc:
                raise TuningValidationError(f"unsupported feedback rating: {self.rating!r}") from exc
        _bounded_text("feedback note", self.note, MAX_NOTE_CHARS, allow_empty=True)
        parse_timestamp(self.created_at)
        if self.reviewed_by_human is not True:
            raise TuningValidationError("tuning feedback must be explicitly human reviewed")


@dataclass(frozen=True)
class TuningCorrection:
    id: str
    interaction_id: str
    version: int
    corrected_response: str
    rationale: str
    created_at: str
    active: bool = True
    reviewed_by_human: bool = True
    corrected_response_sha256: str = ""

    def __post_init__(self) -> None:
        validate_id("correction id", self.id)
        validate_id("interaction id", self.interaction_id)
        if not isinstance(self.version, int) or self.version < 1:
            raise TuningValidationError("correction version must be a positive integer")
        _bounded_text("corrected response", self.corrected_response, MAX_RESPONSE_CHARS)
        _bounded_text("correction rationale", self.rationale, MAX_NOTE_CHARS, allow_empty=True)
        parse_timestamp(self.created_at)
        if not isinstance(self.active, bool):
            raise TuningValidationError("correction active flag must be boolean")
        if self.reviewed_by_human is not True:
            raise TuningValidationError("tuning corrections must be explicitly human reviewed")
        expected = sha256_text(self.corrected_response)
        if self.corrected_response_sha256 and self.corrected_response_sha256 != expected:
            raise TuningValidationError("corrected-response SHA-256 does not match response")
        if not self.corrected_response_sha256:
            object.__setattr__(self, "corrected_response_sha256", expected)


@dataclass(frozen=True)
class ReviewedTuningExample:
    interaction: TuningInteraction
    feedback: TuningFeedback
    correction: TuningCorrection | None
    disposition: ExportDisposition

    def __post_init__(self) -> None:
        if self.feedback.interaction_id != self.interaction.id:
            raise TuningValidationError("feedback does not belong to interaction")
        if self.correction is not None and self.correction.interaction_id != self.interaction.id:
            raise TuningValidationError("correction does not belong to interaction")
        if self.feedback.rating.is_positive:
            if self.disposition is not ExportDisposition.SFT_CANDIDATE:
                raise TuningValidationError("positive feedback must export as an SFT candidate")
        elif self.correction is not None:
            if self.disposition is not ExportDisposition.PREFERENCE_CANDIDATE:
                raise TuningValidationError("corrected negative feedback must export as preference data")
        elif self.disposition is not ExportDisposition.EVALUATION_ONLY:
            raise TuningValidationError("uncorrected negative feedback must remain evaluation only")
