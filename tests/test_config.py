import os

import pytest

from bella_harness.config import ConfigError, get_enabled_backends, load_config, resolve_api_key


def test_load_default_config():
    config = load_config()
    assert config["harness"]["default_backend"] == "ollama"
    assert "backends" in config


def test_enabled_backends_defaults_to_ollama_only():
    config = load_config()
    assert get_enabled_backends(config) == ["ollama"]


def test_rejects_literal_api_key_in_config(tmp_path):
    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text("backends:\n  openai:\n    api_key: sk-not-allowed\n")
    with pytest.raises(ConfigError):
        load_config(bad_config)


def test_missing_config_file_raises():
    with pytest.raises(ConfigError):
        load_config("/nonexistent/path/config.yaml")


def test_env_override(monkeypatch):
    monkeypatch.setenv("BELLA__BACKENDS__OLLAMA__MODEL", "mistral")
    config = load_config()
    assert config["backends"]["ollama"]["model"] == "mistral"


def test_env_override_nested_bool(monkeypatch):
    monkeypatch.setenv("BELLA__BACKENDS__OPENAI__ENABLED", "true")
    config = load_config()
    assert config["backends"]["openai"]["enabled"] is True


def test_resolve_api_key_reads_only_from_env(monkeypatch):
    monkeypatch.setenv("MY_TEST_KEY", "secret-value")
    backend_config = {"api_key_env": "MY_TEST_KEY"}
    assert resolve_api_key(backend_config) == "secret-value"


def test_resolve_api_key_missing_env_returns_none(monkeypatch):
    monkeypatch.delenv("SOME_UNSET_KEY", raising=False)
    backend_config = {"api_key_env": "SOME_UNSET_KEY"}
    assert resolve_api_key(backend_config) is None
