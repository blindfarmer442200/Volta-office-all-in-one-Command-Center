"""Live host acceptance, container evidence, and report integrity tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bella_harness.config import load_config
from bella_harness.deployment import (
    DeploymentAcceptanceError,
    run_deployment_acceptance,
    verify_deployment_report,
)


TOKEN = "d" * 48
EVALUATION_SHA = "a" * 64


def _config():
    config = copy.deepcopy(load_config())
    config["service"]["enabled"] = True
    return config


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, *, action_status: int = 404, bad_token_status: int = 401, **kwargs):
        self.action_status = action_status
        self.bad_token_status = bad_token_status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, path: str, headers=None):
        if path == "/health/live":
            return FakeResponse(200, {"schema": "bella.service-live.v1", "status": "alive"})
        if path == "/health/ready":
            return FakeResponse(
                200,
                {
                    "schema": "bella.service-ready.v1",
                    "ready": True,
                    "package_version": "0.2.0",
                    "checks": [],
                },
            )
        raise AssertionError(path)

    def post(self, path: str, headers=None, json=None):
        if path == "/v1/actions":
            return FakeResponse(self.action_status, {"error": "not_found"})
        if path == "/v1/chat":
            authorization = (headers or {}).get("Authorization", "")
            if authorization != f"Bearer {TOKEN}":
                return FakeResponse(self.bad_token_status, {"error": "unauthorized"})
            return FakeResponse(
                200,
                {
                    "schema": "bella.service-chat.v1",
                    "response": "Hello.",
                    "action": "allow_deterministic",
                    "handled_deterministically": True,
                    "external_action_performed": False,
                },
            )
        raise AssertionError(path)


def _client_factory(**kwargs):
    return FakeClient(**kwargs)


class FakeGate:
    accepted = True
    passed = 18

    def __init__(self, backend, *, backend_name: str, model: str):
        assert backend_name == "ollama"
        self.model = model

    def run(self):
        return SimpleNamespace(
            accepted=self.accepted,
            passed_count=self.passed,
            total=18,
            report_sha256=EVALUATION_SHA,
        )

    def write_report(self, report, path):
        Path(path).write_text(
            json.dumps(
                {
                    "schema": "bella.evaluation-report.v1",
                    "model": self.model,
                    "accepted": report.accepted,
                    "report_sha256": report.report_sha256,
                }
            ),
            encoding="utf-8",
        )


def _doctor(*args, **kwargs):
    return SimpleNamespace(
        ready=True,
        package_version="0.2.0",
        checks=(),
    )


def _container_runner(command, **kwargs):
    assert command[:2] == ["docker", "inspect"]
    return SimpleNamespace(
        stdout=json.dumps(
            [
                {
                    "Config": {"User": "10001:10001"},
                    "HostConfig": {
                        "ReadonlyRootfs": True,
                        "CapDrop": ["ALL"],
                        "SecurityOpt": ["no-new-privileges:true"],
                    },
                    "State": {"Running": True},
                }
            ]
        ),
        stderr="",
    )


def test_live_acceptance_writes_verified_report_without_token(monkeypatch, tmp_path):
    monkeypatch.setattr("bella_harness.deployment.run_service_doctor", _doctor)
    monkeypatch.setattr("bella_harness.deployment.__file__", "/missing/wheel/location/deployment.py")
    evaluation = tmp_path / "evaluation.json"
    deployment = tmp_path / "deployment.json"

    report = run_deployment_acceptance(
        _config(),
        service_token=TOKEN,
        service_url="http://127.0.0.1:8765",
        model="qwen3.5:exact",
        evaluation_report_path=evaluation,
        deployment_report_path=deployment,
        container_name="bella-service",
        client_factory=_client_factory,
        container_runner=_container_runner,
        gate_factory=FakeGate,
    )

    assert report.accepted is True
    assert report.package_version == "0.2.0"
    assert report.evaluation_report_sha256 == EVALUATION_SHA
    assert evaluation.exists()
    assert verify_deployment_report(deployment)
    text = deployment.read_text(encoding="utf-8")
    assert TOKEN not in text
    assert "external_action_performed" not in text
    assert all(check.status == "pass" for check in report.checks)


def test_17_of_18_model_is_rejected_but_report_remains_verifiable(monkeypatch, tmp_path):
    monkeypatch.setattr("bella_harness.deployment.run_service_doctor", _doctor)

    class FailingGate(FakeGate):
        accepted = False
        passed = 17

    deployment = tmp_path / "deployment.json"
    report = run_deployment_acceptance(
        _config(),
        service_token=TOKEN,
        service_url="http://localhost:8765",
        model="candidate",
        evaluation_report_path=tmp_path / "evaluation.json",
        deployment_report_path=deployment,
        client_factory=_client_factory,
        gate_factory=FailingGate,
    )
    assert report.accepted is False
    evaluation_check = next(
        check for check in report.checks if check.name == "live_model_evaluation"
    )
    assert evaluation_check.status == "fail"
    assert verify_deployment_report(deployment)


def test_action_route_or_auth_contract_failure_rejects_host(monkeypatch, tmp_path):
    monkeypatch.setattr("bella_harness.deployment.run_service_doctor", _doctor)

    def unsafe_client_factory(**kwargs):
        return FakeClient(action_status=200, bad_token_status=200, **kwargs)

    report = run_deployment_acceptance(
        _config(),
        service_token=TOKEN,
        service_url="http://127.0.0.1:8765",
        model="candidate",
        evaluation_report_path=tmp_path / "evaluation.json",
        deployment_report_path=tmp_path / "deployment.json",
        client_factory=unsafe_client_factory,
        gate_factory=FakeGate,
    )
    assert report.accepted is False
    failed = {check.name for check in report.checks if check.status == "fail"}
    assert "service_authentication" in failed
    assert "service_action_route_closed" in failed


def test_public_service_url_is_rejected_before_live_checks(tmp_path):
    with pytest.raises(DeploymentAcceptanceError, match="unsafe service URL"):
        run_deployment_acceptance(
            _config(),
            service_token=TOKEN,
            service_url="https://bella.example.com",
            model="candidate",
            evaluation_report_path=tmp_path / "evaluation.json",
            deployment_report_path=tmp_path / "deployment.json",
            client_factory=_client_factory,
            gate_factory=FakeGate,
        )


def test_container_hardening_failure_is_critical(monkeypatch, tmp_path):
    monkeypatch.setattr("bella_harness.deployment.run_service_doctor", _doctor)

    def weak_container(command, **kwargs):
        return SimpleNamespace(
            stdout=json.dumps(
                [
                    {
                        "Config": {"User": "root"},
                        "HostConfig": {
                            "ReadonlyRootfs": False,
                            "CapDrop": [],
                            "SecurityOpt": [],
                        },
                        "State": {"Running": True},
                    }
                ]
            ),
            stderr="",
        )

    report = run_deployment_acceptance(
        _config(),
        service_token=TOKEN,
        service_url="http://127.0.0.1:8765",
        model="candidate",
        evaluation_report_path=tmp_path / "evaluation.json",
        deployment_report_path=tmp_path / "deployment.json",
        container_name="weak-container",
        client_factory=_client_factory,
        container_runner=weak_container,
        gate_factory=FakeGate,
    )
    assert report.accepted is False
    check = next(check for check in report.checks if check.name == "container_hardening")
    assert check.status == "fail"
    assert check.critical is True


def test_report_tampering_and_malformed_checks_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("bella_harness.deployment.run_service_doctor", _doctor)
    path = tmp_path / "deployment.json"
    run_deployment_acceptance(
        _config(),
        service_token=TOKEN,
        service_url="http://127.0.0.1:8765",
        model="candidate",
        evaluation_report_path=tmp_path / "evaluation.json",
        deployment_report_path=path,
        client_factory=_client_factory,
        gate_factory=FakeGate,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["model"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert not verify_deployment_report(path)

    payload["report_sha256"] = "b" * 64
    payload["checks"] = ["not-a-check"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert not verify_deployment_report(path)
