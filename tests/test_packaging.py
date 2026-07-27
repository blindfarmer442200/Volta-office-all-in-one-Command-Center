"""Package-data and installed-default regression tests."""

from __future__ import annotations

from pathlib import Path

from bella_harness.config import DEFAULT_CONFIG_PATH, load_config


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_packaged_default_config_is_inside_bella_package():
    assert DEFAULT_CONFIG_PATH.name == "default.yaml"
    assert DEFAULT_CONFIG_PATH.parent.name == "bella_harness"
    assert DEFAULT_CONFIG_PATH.is_file()


def test_repository_and_packaged_default_configs_are_identical():
    repository_copy = REPO_ROOT / "config" / "default.yaml"
    assert repository_copy.read_bytes() == DEFAULT_CONFIG_PATH.read_bytes()


def test_packaged_defaults_include_private_ollama_and_disabled_automation():
    config = load_config()
    ollama = config["backends"]["ollama"]
    service = config["service"]
    assert config["harness"]["allow_cloud_fallback"] is False
    assert ollama["base_url"] == "http://localhost:11434"
    assert ollama["max_prompt_chars"] == 128000
    assert ollama["max_response_bytes"] == 1000000
    assert ollama["max_output_chars"] == 200000
    assert config["tuning"]["automatic_capture"] is False
    assert config["tuning"]["automatic_upload"] is False
    assert config["tuning"]["automatic_training"] is False
    assert config["tuning"]["automatic_model_activation"] is False
    assert service["enabled"] is False
    assert service["host"] == "127.0.0.1"
    assert service["allow_remote_bind"] is False
    assert service["token_env"] == "BELLA_SERVICE_TOKEN"
    assert service["max_concurrent_requests"] == 4


def test_source_distribution_manifest_includes_service_deployment_files():
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for required in (
        "include .dockerignore",
        "include Dockerfile",
        "include compose.service.yml",
        "recursive-include docs *.md",
    ):
        assert required in manifest
