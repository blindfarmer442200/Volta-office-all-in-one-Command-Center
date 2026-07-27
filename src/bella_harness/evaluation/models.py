"""Typed records for Bella's deterministic model-evaluation gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUITE_VERSION = "bella-behavior-v1"
REPORT_SCHEMA = "bella.evaluation-report.v1"
ACCEPTANCE_SCHEMA = "bella.model-acceptance.v1"


class EvaluationError(RuntimeError):
    """Raised when an evaluation, report, or promotion record is invalid."""


@dataclass(frozen=True)
class EvaluationScenario:
    """One synthetic request and its deterministic response contract."""

    id: str
    title: str
    category: str
    mode: str
    user_request: str
    reference_context: str = ""
    required_any: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    forbidden_terms: tuple[str, ...] = field(default_factory=tuple)
    max_words: int | None = None
    require_no_completion_claim: bool = False
    required: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("id", self.id),
            ("title", self.title),
            ("category", self.category),
            ("mode", self.mode),
            ("user_request", self.user_request),
        ):
            if not isinstance(value, str) or not value.strip():
                raise EvaluationError(f"scenario {name} must be a non-empty string")
        if self.max_words is not None and not 1 <= self.max_words <= 1_000:
            raise EvaluationError("scenario max_words must be between 1 and 1000")
        for group in self.required_any:
            if not group or any(not isinstance(term, str) or not term.strip() for term in group):
                raise EvaluationError("required_any groups must contain non-empty strings")
        if any(not isinstance(term, str) or not term.strip() for term in self.forbidden_terms):
            raise EvaluationError("forbidden_terms must contain non-empty strings")


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    title: str
    category: str
    required: bool
    passed: bool
    response: str
    checks: tuple[CheckResult, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "category": self.category,
            "required": self.required,
            "passed": self.passed,
            "response": self.response,
            "checks": [check.to_dict() for check in self.checks],
            "error": self.error,
        }


@dataclass(frozen=True)
class EvaluationReport:
    suite_version: str
    profile_id: str
    backend_name: str
    model: str
    endpoint: str
    started_at: str
    completed_at: str
    passed: bool
    score: int
    passed_scenarios: int
    total_scenarios: int
    required_failures: tuple[str, ...]
    results: tuple[ScenarioResult, ...]
    digest: str = ""

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema": REPORT_SCHEMA,
            "suite_version": self.suite_version,
            "profile_id": self.profile_id,
            "backend_name": self.backend_name,
            "model": self.model,
            "endpoint": self.endpoint,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "passed": self.passed,
            "score": self.score,
            "passed_scenarios": self.passed_scenarios,
            "total_scenarios": self.total_scenarios,
            "required_failures": list(self.required_failures),
            "results": [result.to_dict() for result in self.results],
        }
        if include_digest:
            payload["digest"] = self.digest
        return payload
