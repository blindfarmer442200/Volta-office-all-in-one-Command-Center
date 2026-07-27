"""Canonical JSON, SHA-256, and strict report loading."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from bella_harness.evaluation.models import (
    REPORT_SCHEMA,
    SUITE_VERSION,
    EvaluationError,
    EvaluationReport,
)


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def report_digest(payload: dict[str, Any]) -> str:
    material = dict(payload)
    material.pop("digest", None)
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def finalize_report(report: EvaluationReport) -> EvaluationReport:
    digest = report_digest(report.to_dict(include_digest=False))
    return replace(report, digest=digest)


def write_report(report: EvaluationReport, path: str | Path) -> Path:
    finalized = report if report.digest else finalize_report(report)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(finalized.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_verified_report(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvaluationError(f"unable to read evaluation report: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"evaluation report is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvaluationError("evaluation report must be a JSON object")

    required = {
        "schema",
        "suite_version",
        "profile_id",
        "backend_name",
        "model",
        "endpoint",
        "started_at",
        "completed_at",
        "passed",
        "score",
        "passed_scenarios",
        "total_scenarios",
        "required_failures",
        "results",
        "digest",
    }
    missing = sorted(required - set(payload))
    unknown = sorted(set(payload) - required)
    if missing:
        raise EvaluationError(f"evaluation report is missing fields: {', '.join(missing)}")
    if unknown:
        raise EvaluationError(f"evaluation report contains unknown fields: {', '.join(unknown)}")
    if payload["schema"] != REPORT_SCHEMA:
        raise EvaluationError("evaluation report schema is not supported")
    if payload["suite_version"] != SUITE_VERSION:
        raise EvaluationError("evaluation report suite version is stale or unsupported")
    if not isinstance(payload["passed"], bool):
        raise EvaluationError("evaluation report passed must be a boolean")
    if not isinstance(payload["score"], int) or not 0 <= payload["score"] <= 100:
        raise EvaluationError("evaluation report score must be an integer from 0 to 100")
    if not isinstance(payload["results"], list) or len(payload["results"]) != 18:
        raise EvaluationError("evaluation report must contain exactly 18 scenario results")
    if not isinstance(payload["required_failures"], list):
        raise EvaluationError("evaluation report required_failures must be a list")
    if not isinstance(payload["digest"], str) or len(payload["digest"]) != 64:
        raise EvaluationError("evaluation report digest is malformed")

    expected = report_digest(payload)
    if not hmac.compare_digest(payload["digest"], expected):
        raise EvaluationError("evaluation report digest verification failed")
    return payload
