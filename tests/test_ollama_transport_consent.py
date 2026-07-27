"""Remote private Ollama transport requires explicit operator consent."""

from __future__ import annotations

import copy

import pytest

from bella_harness.backends import BackendError
from bella_harness.backends.ollama_backend import OllamaBackend
from bella_harness.config import load_config
from bella_harness.doctor import run_doctor


def _config(base_url: str, **overrides):
    config = {
        "enabled": True,
        "base_url": base_url,
        "model": "qwen3.5",
    }
    config.update(overrides)
    return config


def test_loopback_http_remains_allowed():
    assert OllamaBackend(_config("http://localhost:11434")).base_url == (
        "http://localhost:11434"
    )
    assert OllamaBackend(_config("http://127.0.0.1:11434")).base_url == (
        "http://127.0.0.1:11434"
    )
    assert OllamaBackend(_config("http://[::1]:11434")).base_url == (
        "http://[::1]:11434"
    )


def test_remote_private_http_is_rejected_without_explicit_consent():
    for base_url in ("http://192.168.1.20:11434", "http://[fd00::1]:11434"):
        with pytest.raises(BackendError, match="must use https"):
            OllamaBackend(_config(base_url))


def test_remote_private_https_is_allowed():
    assert OllamaBackend(_config("https://192.168.1.20:11434")).base_url == (
        "https://192.168.1.20:11434"
    )
    assert OllamaBackend(_config("https://[fd00::1]:11434")).base_url == (
        "https://[fd00::1]:11434"
    )


def test_remote_private_http_requires_boolean_explicit_opt_in():
    with pytest.raises(BackendError, match="must be boolean"):
        OllamaBackend(
            _config(
                "http://192.168.1.20:11434",
                allow_insecure_private_http="yes",
            )
        )

    backend = OllamaBackend(
        _config(
            "http://192.168.1.20:11434",
            allow_insecure_private_http=True,
        )
    )
    assert backend.allow_insecure_private_http is True


def test_doctor_fails_unapproved_remote_http_and_accepts_explicit_opt_in():
    unsafe = copy.deepcopy(load_config())
    unsafe["backends"]["ollama"]["base_url"] = "http://192.168.1.20:11434"
    unsafe_report = run_doctor(unsafe)
    unsafe_checks = {check.name: check for check in unsafe_report.checks}
    assert unsafe_report.ready is False
    assert unsafe_checks["ollama_endpoint"].status == "fail"

    approved = copy.deepcopy(unsafe)
    approved["backends"]["ollama"]["allow_insecure_private_http"] = True
    approved_report = run_doctor(approved)
    approved_checks = {check.name: check for check in approved_report.checks}
    assert approved_report.ready is True
    assert approved_checks["ollama_endpoint"].status == "pass"
