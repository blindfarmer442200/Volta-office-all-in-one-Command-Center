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


@pytest.mark.parametrize(
    "yaml_body",
    [
        "backends:\n  openai:\n    api_key: sk-xxx\n",          # api_key
        "backends:\n  openai:\n    apikey: sk-xxx\n",           # apikey
        "backends:\n  openai:\n    secret: hunter2\n",          # secret
        "backends:\n  openai:\n    token: abc123\n",            # token
        "harness:\n  nested:\n    deeply:\n      secret: x\n",  # deeply nested
    ],
)
def test_rejects_literal_secret_variants(tmp_path, yaml_body):
    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text(yaml_body)
    with pytest.raises(ConfigError):
        load_config(bad_config)


def test_allows_api_key_env_reference(tmp_path):
    # api_key_env is the *name* of an env var, not a secret -- it must be allowed.
    ok_config = tmp_path / "ok.yaml"
    ok_config.write_text(
        "harness:\n  default_backend: openai\n"
        "backends:\n  openai:\n    enabled: true\n    api_key_env: OPENAI_API_KEY\n"
    )
    config = load_config(ok_config)
    assert config["backends"]["openai"]["api_key_env"] == "OPENAI_API_KEY"


def test_rejects_secret_injected_via_env_override(tmp_path, monkeypatch):
    # Even if a literal secret is smuggled in through an env override, the
    # post-override re-validation must reject it.
    ok_config = tmp_path / "ok.yaml"
    ok_config.write_text("backends:\n  openai:\n    enabled: true\n    api_key_env: OPENAI_API_KEY\n")
    monkeypatch.setenv("BELLA__BACKENDS__OPENAI__API_KEY", "sk-smuggled")
    with pytest.raises(ConfigError):
        load_config(ok_config)


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
