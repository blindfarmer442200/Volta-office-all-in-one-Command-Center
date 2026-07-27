"""Authenticated service configuration and token validation tests."""

from __future__ import annotations

import copy

import pytest

from bella_harness.config import load_config
from bella_harness.service.doctor import run_service_doctor
from bella_harness.service.settings import (
    ServiceConfigurationError,
    ServiceSettings,
    resolve_service_token,
)


TOKEN = "s" * 32


def _config():
    config = copy.deepcopy(load_config())
    config["service"]["enabled"] = True
    return config


def test_default_service_is_disabled_and_loopback_bounded():
    settings = ServiceSettings.from_config(load_config())
    assert settings.enabled is False
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.remote_bind is False
    assert settings.max_body_bytes == 65536
    assert settings.max_prompt_chars == 32000


def test_service_token_must_be_strong_environment_value():
    assert resolve_service_token("TOKEN", environment={"TOKEN": TOKEN}) == TOKEN
    with pytest.raises(ServiceConfigurationError, match="not set"):
        resolve_service_token("TOKEN", environment={})
    with pytest.raises(ServiceConfigurationError, match="32 and 512"):
        resolve_service_token("TOKEN", environment={"TOKEN": "short"})
    with pytest.raises(ServiceConfigurationError, match="whitespace"):
        resolve_service_token("TOKEN", environment={"TOKEN": "x" * 31 + " "})


def test_remote_bind_requires_explicit_consent_and_nonloopback_trusted_host():
    config = _config()
    config["service"]["host"] = "0.0.0.0"
    with pytest.raises(ServiceConfigurationError, match="allow_remote_bind"):
        ServiceSettings.from_config(config)

    config["service"]["allow_remote_bind"] = True
    with pytest.raises(ServiceConfigurationError, match="non-loopback trusted host"):
        ServiceSettings.from_config(config)

    config["service"]["trusted_hosts"] = ["bella.example.com"]
    settings = ServiceSettings.from_config(config)
    assert settings.remote_bind is True


def test_service_rejects_dns_bind_wildcard_hosts_and_invalid_bounds():
    config = _config()
    config["service"]["host"] = "bella.example.com"
    with pytest.raises(ServiceConfigurationError, match="literal IP"):
        ServiceSettings.from_config(config)

    config = _config()
    config["service"]["trusted_hosts"] = ["*"]
    with pytest.raises(ServiceConfigurationError, match="wildcard"):
        ServiceSettings.from_config(config)

    config = _config()
    config["service"]["max_concurrent_requests"] = 0
    with pytest.raises(ServiceConfigurationError, match="max_concurrent_requests"):
        ServiceSettings.from_config(config)


def test_service_doctor_skips_disabled_and_fails_missing_token():
    disabled = run_service_doctor(load_config())
    service_check = next(check for check in disabled.checks if check.name == "http_service")
    assert service_check.status == "skip"
    assert disabled.ready is True

    enabled = run_service_doctor(_config(), environment={})
    service_check = next(check for check in enabled.checks if check.name == "http_service")
    assert service_check.status == "fail"
    assert enabled.ready is False

    valid = run_service_doctor(_config(), token_override=TOKEN)
    service_check = next(check for check in valid.checks if check.name == "http_service")
    assert service_check.status == "pass"
    assert valid.ready is True
