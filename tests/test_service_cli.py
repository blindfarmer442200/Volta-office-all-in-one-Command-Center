"""Installed `bella serve` command safety tests."""

from __future__ import annotations

from click.testing import CliRunner

from bella_harness.entrypoint import main


TOKEN = "v" * 32


def test_serve_refuses_disabled_service_before_starting_server():
    result = CliRunner().invoke(main, ["serve"])
    assert result.exit_code != 0
    assert "service is disabled" in result.output.lower()


def test_serve_refuses_remote_override_without_remote_consent():
    result = CliRunner().invoke(
        main,
        ["serve", "--host", "0.0.0.0"],
        env={
            "BELLA__SERVICE__ENABLED": "true",
            "BELLA_SERVICE_TOKEN": TOKEN,
        },
    )
    assert result.exit_code != 0
    assert "allow_remote_bind" in result.output


def test_serve_uses_hardened_uvicorn_options(monkeypatch):
    captured = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = CliRunner().invoke(
        main,
        ["serve", "--port", "8877", "--log-level", "warning"],
        env={
            "BELLA__SERVICE__ENABLED": "true",
            "BELLA_SERVICE_TOKEN": TOKEN,
        },
    )
    assert result.exit_code == 0, result.output
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8877
    assert captured["log_level"] == "warning"
    assert captured["access_log"] is False
    assert captured["proxy_headers"] is False
    assert captured["server_header"] is False
    assert captured["date_header"] is False
