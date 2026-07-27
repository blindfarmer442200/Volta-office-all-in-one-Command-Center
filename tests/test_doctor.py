"""Production-readiness doctor regression tests."""

from __future__ import annotations

import copy
import json

from click.testing import CliRunner

from bella_harness.config import load_config
from bella_harness.doctor import run_doctor
from bella_harness.entrypoint import main


def _checks(report):
    return {check.name: check for check in report.checks}


def test_default_offline_doctor_is_ready_with_noncritical_store_warnings():
    report = run_doctor(load_config())
    checks = _checks(report)
    assert report.ready is True
    assert checks["fail_closed"].status == "pass"
    assert checks["output_scanning"].status == "pass"
    assert checks["operator"].status == "pass"
    assert checks["action_gate"].status == "pass"
    assert checks["evaluation_gate"].status == "pass"
    assert checks["tuning_automation"].status == "pass"
    assert checks["ollama_endpoint"].status == "pass"
    assert checks["memory_store"].status == "warn"
    assert checks["tuning_store"].status == "warn"
    assert checks["ollama_live"].status == "skip"


def test_doctor_fails_unsafe_endpoint_and_disabled_safety_layers():
    config = copy.deepcopy(load_config())
    config["harness"]["fail_closed"] = False
    config["harness"]["output_scanning"]["enabled"] = False
    config["operator"]["enabled"] = False
    config["backends"]["ollama"]["base_url"] = "https://ollama.example.com"

    report = run_doctor(config)
    checks = _checks(report)
    assert report.ready is False
    assert checks["fail_closed"].status == "fail"
    assert checks["output_scanning"].status == "fail"
    assert checks["operator"].status == "fail"
    assert checks["ollama_endpoint"].status == "fail"


def test_doctor_fails_invalid_memory_store(tmp_path):
    config = copy.deepcopy(load_config())
    memory_path = tmp_path / "memory.jsonl"
    memory_path.write_text("not-json\n", encoding="utf-8")
    config["memory"]["store_path"] = str(memory_path)

    report = run_doctor(config)
    assert report.ready is False
    assert _checks(report)["memory_store"].status == "fail"


def test_live_doctor_fails_when_ollama_health_check_fails(monkeypatch):
    monkeypatch.setattr(
        "bella_harness.backends.ollama_backend.OllamaBackend.health_check",
        lambda self: False,
    )
    report = run_doctor(load_config(), live=True)
    assert report.ready is False
    assert _checks(report)["ollama_live"].status == "fail"


def test_installed_entrypoint_registers_json_doctor_command():
    runner = CliRunner()
    result = runner.invoke(main, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "bella.doctor-report.v1"
    assert payload["ready"] is True
    assert any(check["name"] == "ollama_endpoint" for check in payload["checks"])
    lowered = result.output.lower()
    assert "memory_ids" not in lowered
    assert "original_response" not in lowered
    assert "api_key" not in lowered
