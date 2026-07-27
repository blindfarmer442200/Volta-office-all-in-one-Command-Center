"""Installed live deployment acceptance command tests."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from bella_harness.deployment import DeploymentCheck, DeploymentReport
from bella_harness.entrypoint import main


TOKEN = "z" * 48


def _report(*, accepted: bool) -> DeploymentReport:
    check = DeploymentCheck(
        name="production_doctor",
        status="pass" if accepted else "fail",
        critical=True,
        message="Doctor result.",
        evidence={},
    )
    return DeploymentReport(
        schema="bella.deployment-acceptance.v1",
        package_version="0.2.0",
        generated_at="2026-07-27T12:00:00+00:00",
        service_url="http://127.0.0.1:8765",
        model="qwen3.5:exact",
        accepted=accepted,
        checks=(check,),
        evaluation_report_sha256="a" * 64 if accepted else None,
        report_sha256="b" * 64,
    )


def test_accept_deployment_outputs_safe_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "bella_harness.deployment_cli.resolve_service_token",
        lambda token_env: TOKEN,
    )
    monkeypatch.setattr(
        "bella_harness.deployment_cli.run_deployment_acceptance",
        lambda *args, **kwargs: _report(accepted=True),
    )
    result = CliRunner().invoke(
        main,
        [
            "accept-deployment",
            "--service-url",
            "http://127.0.0.1:8765",
            "--model",
            "qwen3.5:exact",
            "--evaluation-report",
            str(tmp_path / "evaluation.json"),
            "--report",
            str(tmp_path / "deployment.json"),
        ],
        env={"BELLA__SERVICE__ENABLED": "true"},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["accepted"] is True
    assert payload["model_activated"] is False
    assert payload["external_action_performed"] is False
    assert TOKEN not in result.output


def test_accept_deployment_exits_nonzero_when_critical_gate_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "bella_harness.deployment_cli.resolve_service_token",
        lambda token_env: TOKEN,
    )
    monkeypatch.setattr(
        "bella_harness.deployment_cli.run_deployment_acceptance",
        lambda *args, **kwargs: _report(accepted=False),
    )
    result = CliRunner().invoke(
        main,
        [
            "accept-deployment",
            "--evaluation-report",
            str(tmp_path / "evaluation.json"),
            "--report",
            str(tmp_path / "deployment.json"),
        ],
        env={"BELLA__SERVICE__ENABLED": "true"},
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["accepted"] is False


def test_verify_deployment_command_reports_validity(monkeypatch, tmp_path):
    report = tmp_path / "deployment.json"
    report.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "bella_harness.deployment_cli.verify_deployment_report",
        lambda path: Path(path) == report,
    )
    success = CliRunner().invoke(main, ["verify-deployment", "--report", str(report)])
    assert success.exit_code == 0
    assert json.loads(success.output)["verified"] is True

    monkeypatch.setattr(
        "bella_harness.deployment_cli.verify_deployment_report",
        lambda path: False,
    )
    failure = CliRunner().invoke(main, ["verify-deployment", "--report", str(report)])
    assert failure.exit_code == 1
    assert json.loads(failure.output)["verified"] is False
