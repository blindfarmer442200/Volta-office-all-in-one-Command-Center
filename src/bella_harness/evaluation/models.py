"""Typed contracts for Bella's model acceptance gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MAX_EVALUATION_ANSWER_CHARS = 8_000


class EvaluationError(RuntimeError):
    """Raised when an evaluation cannot be run or verified safely."""


@dataclass(frozen=True)
class EvaluationScenario:
    """One synthetic, mandatory Bella behavior scenario."""

    id: str
    title: str
    prompt: str
    mode: str
    expected_approval_required: bool = False
    expected_memory_used: bool = False
    expected_external_action_performed: bool = False
    require_uncertainty: bool = False
    max_answer_chars: int | None = None
    required_any_groups: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    forbidden_phrases: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.id or not self.id.replace("_", "").replace("-", "").isalnum():
            raise EvaluationError("scenario id must contain only letters, numbers, '_' or '-'")
        if not self.title.strip() or not self.prompt.strip() or not self.mode.strip():
            raise EvaluationError("scenario title, prompt, and mode are required")
        if self.max_answer_chars is not None and not 1 <= self.max_answer_chars <= MAX_EVALUATION_ANSWER_CHARS:
            raise EvaluationError("scenario max_answer_chars is out of bounds")
        for group in self.required_any_groups:
            if not group or any(not isinstance(term, str) or not term.strip() for term in group):
                raise EvaluationError("required phrase groups must contain non-empty strings")
        if any(not isinstance(term, str) or not term.strip() for term in self.forbidden_phrases):
            raise EvaluationError("forbidden phrases must be non-empty strings")


@dataclass(frozen=True)
class EvaluationResponse:
    """Strict JSON response returned by a candidate model."""

    answer: str
    memory_used: bool
    external_action_performed: bool
    approval_required: bool
    uncertainty: str | None
    mode: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationResponse":
        if not isinstance(data, dict):
            raise EvaluationError("candidate response must be a JSON object")
        expected = {
            "answer",
            "memory_used",
            "external_action_performed",
            "approval_required",
            "uncertainty",
            "mode",
        }
        unknown = sorted(set(data) - expected)
        missing = sorted(expected - set(data))
        if missing:
            raise EvaluationError(f"candidate response is missing fields: {', '.join(missing)}")
        if unknown:
            raise EvaluationError(f"candidate response contains unknown fields: {', '.join(unknown)}")

        answer = data["answer"]
        uncertainty = data["uncertainty"]
        mode = data["mode"]
        if not isinstance(answer, str) or not answer.strip():
            raise EvaluationError("candidate answer must be a non-empty string")
        if len(answer) > MAX_EVALUATION_ANSWER_CHARS:
            raise EvaluationError("candidate answer exceeds the 8,000 character limit")
        if not isinstance(data["memory_used"], bool):
            raise EvaluationError("memory_used must be a boolean")
        if not isinstance(data["external_action_performed"], bool):
            raise EvaluationError("external_action_performed must be a boolean")
        if not isinstance(data["approval_required"], bool):
            raise EvaluationError("approval_required must be a boolean")
        if uncertainty is not None and not isinstance(uncertainty, str):
            raise EvaluationError("uncertainty must be a string or null")
        if not isinstance(mode, str) or not mode.strip():
            raise EvaluationError("mode must be a non-empty string")

        return cls(
            answer=answer.strip(),
            memory_used=data["memory_used"],
            external_action_performed=data["external_action_performed"],
            approval_required=data["approval_required"],
            uncertainty=uncertainty.strip() if isinstance(uncertainty, str) else None,
            mode=mode.strip().lower(),
        )


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    title: str
    passed: bool
    failures: tuple[str, ...]
    answer: str
    mode: str
    memory_used: bool
    external_action_performed: bool
    approval_required: bool
    uncertainty: str | None


@dataclass(frozen=True)
class EvaluationReport:
    schema: str
    profile_id: str
    backend: str
    model: str
    generated_at: str
    total: int
    passed_count: int
    failed_count: int
    accepted: bool
    results: tuple[ScenarioResult, ...]
    report_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "profile_id": self.profile_id,
            "backend": self.backend,
            "model": self.model,
            "generated_at": self.generated_at,
            "total": self.total,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "accepted": self.accepted,
            "results": [
                {
                    "scenario_id": result.scenario_id,
                    "title": result.title,
                    "passed": result.passed,
                    "failures": list(result.failures),
                    "answer": result.answer,
                    "mode": result.mode,
                    "memory_used": result.memory_used,
                    "external_action_performed": result.external_action_performed,
                    "approval_required": result.approval_required,
                    "uncertainty": result.uncertainty,
                }
                for result in self.results
            ],
            "report_sha256": self.report_sha256,
        }
