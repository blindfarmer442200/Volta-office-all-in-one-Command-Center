"""Regression tests for Bella's all-or-nothing local model gate."""

from __future__ import annotations

import json
import re
from dataclasses import replace

import pytest

from bella_harness.backends.base import Backend, BackendResponse
from bella_harness.evaluation import (
    BellaEvaluationGate,
    DEFAULT_SCENARIOS,
    EvaluationError,
    validate_scenario_catalog,
)


_SCENARIOS_BY_ID = {scenario.id: scenario for scenario in DEFAULT_SCENARIOS}


class PassingOllamaBackend(Backend):
    name = "ollama"

    def __init__(self):
        super().__init__({"model": "bella-test-model", "timeout_seconds": 1})
        self.prompts: list[str] = []

    def generate(self, prompt: str, **kwargs) -> BackendResponse:
        self.prompts.append(prompt)
        match = re.search(r"SCENARIO_ID: ([A-Za-z0-9_-]+)", prompt)
        assert match, "evaluation prompt must expose the synthetic scenario id"
        scenario = _SCENARIOS_BY_ID[match.group(1)]
        phrases = [group[0] for group in scenario.required_any_groups]
        answer = " ".join(phrases) or "Here is a direct, useful answer."
        payload = {
            "answer": answer,
            "memory_used": scenario.expected_memory_used,
            "external_action_performed": scenario.expected_external_action_performed,
            "approval_required": scenario.expected_approval_required,
            "uncertainty": "The information is missing or unreviewed." if scenario.require_uncertainty else None,
            "mode": scenario.mode,
        }
        return BackendResponse(
            text=json.dumps(payload),
            backend_name=self.name,
            model=kwargs.get("model", self.model),
        )


class OneFailureBackend(PassingOllamaBackend):
    def generate(self, prompt: str, **kwargs) -> BackendResponse:
        response = super().generate(prompt, **kwargs)
        if "SCENARIO_ID: false_completion_email" in prompt:
            payload = json.loads(response.text)
            payload["external_action_performed"] = True
            payload["answer"] = "I sent the email."
            return replace(response, text=json.dumps(payload))
        return response


class MalformedOllamaBackend(PassingOllamaBackend):
    def generate(self, prompt: str, **kwargs) -> BackendResponse:
        self.prompts.append(prompt)
        return BackendResponse("```json\n{}\n```", self.name, self.model)


class CloudBackend(PassingOllamaBackend):
    name = "openai"


def test_catalog_is_exactly_18_unique_synthetic_scenarios():
    validate_scenario_catalog()
    assert len(DEFAULT_SCENARIOS) == 18
    assert len({scenario.id for scenario in DEFAULT_SCENARIOS}) == 18
    combined = " ".join(scenario.prompt.lower() for scenario in DEFAULT_SCENARIOS)
    assert "sk-proj-" not in combined
    assert "oauth" not in combined


def test_passing_model_must_pass_every_scenario_and_report_hash_verifies(tmp_path):
    backend = PassingOllamaBackend()
    gate = BellaEvaluationGate(backend, model="bella-test-model")

    report = gate.run()

    assert report.accepted
    assert report.total == 18
    assert report.passed_count == 18
    assert report.failed_count == 0
    assert gate.verify_report(report)
    assert len(backend.prompts) == 18
    assert all("[BELLA_OPERATOR_CONTEXT]" in prompt for prompt in backend.prompts)
    assert all("[BELLA_EVALUATION_PROTOCOL]" in prompt for prompt in backend.prompts)
    assert all("[MIND_TRACE_CONTEXT]" not in prompt for prompt in backend.prompts)

    destination = tmp_path / "report.json"
    gate.write_report(report, destination)
    saved = json.loads(destination.read_text(encoding="utf-8"))
    assert saved["accepted"] is True
    assert saved["report_sha256"] == report.report_sha256


def test_one_required_failure_blocks_acceptance_even_when_17_pass():
    report = BellaEvaluationGate(OneFailureBackend(), model="candidate").run()

    assert not report.accepted
    assert report.passed_count == 17
    assert report.failed_count == 1
    failed = [result for result in report.results if not result.passed]
    assert [result.scenario_id for result in failed] == ["false_completion_email"]
    assert any("external_action_performed" in failure for failure in failed[0].failures)


def test_malformed_or_markdown_wrapped_json_fails_closed():
    report = BellaEvaluationGate(MalformedOllamaBackend(), model="candidate").run()

    assert not report.accepted
    assert report.failed_count == 18
    assert all(result.answer == "" for result in report.results)
    assert all("raw JSON" in result.failures[0] for result in report.results)


def test_cloud_backend_is_rejected_before_any_scenario_runs():
    with pytest.raises(EvaluationError, match="local-only"):
        BellaEvaluationGate(CloudBackend(), backend_name="openai", model="cloud-model")


def test_report_hash_detects_metadata_tampering():
    gate = BellaEvaluationGate(PassingOllamaBackend(), model="candidate")
    report = gate.run()

    assert gate.verify_report(report)
    assert not gate.verify_report(replace(report, model="different-model"))


def test_report_writer_rejects_tampered_report(tmp_path):
    gate = BellaEvaluationGate(PassingOllamaBackend(), model="candidate")
    report = replace(gate.run(), accepted=False)

    with pytest.raises(EvaluationError, match="invalid hash"):
        gate.write_report(report, tmp_path / "tampered.json")
