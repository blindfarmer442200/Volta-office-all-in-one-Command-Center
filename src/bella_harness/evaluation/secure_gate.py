"""Hardened report verification wrapper for Bella's evaluation gate."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from bella_harness.evaluation.gate import (
    REPORT_SCHEMA,
    BellaEvaluationGate as _BaseBellaEvaluationGate,
    _canonical_json,
    _report_payload_without_hash,
)
from bella_harness.evaluation.models import EvaluationError, EvaluationReport


class BellaEvaluationGate(_BaseBellaEvaluationGate):
    """Evaluation gate with strict report metadata and hash verification."""

    @staticmethod
    def verify_report(report: EvaluationReport) -> bool:
        payload = _report_payload_without_hash(
            profile_id=report.profile_id,
            backend=report.backend,
            model=report.model,
            generated_at=report.generated_at,
            results=report.results,
        )
        metadata_matches = (
            report.schema == REPORT_SCHEMA
            and report.backend == "ollama"
            and report.total == payload["total"]
            and report.passed_count == payload["passed_count"]
            and report.failed_count == payload["failed_count"]
            and report.accepted is payload["accepted"]
        )
        if not metadata_matches:
            return False
        expected = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected, report.report_sha256)

    @staticmethod
    def write_report(report: EvaluationReport, path: str | Path) -> None:
        if not BellaEvaluationGate.verify_report(report):
            raise EvaluationError("refusing to write an evaluation report with an invalid hash")
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
