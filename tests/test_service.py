"""End-to-end authenticated Bella HTTP service tests."""

from __future__ import annotations

import copy
import logging

from fastapi.testclient import TestClient

from bella_harness.config import load_config
from bella_harness.deterministic.engine import Action
from bella_harness.harness import HarnessResult
from bella_harness.service.app import create_app


TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeHarness:
    def __init__(self, result: HarnessResult):
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def handle(self, prompt: str, *, mode: str = "default") -> HarnessResult:
        self.calls.append((prompt, mode))
        return self.result


def _config(**service_overrides):
    config = copy.deepcopy(load_config())
    config["service"]["enabled"] = True
    config["service"].update(service_overrides)
    return config


def _client(*, config=None, harness=None):
    app = create_app(config=config or _config(), token=TOKEN, harness=harness)
    return TestClient(app, base_url="http://localhost")


def test_liveness_is_minimal_unauthenticated_and_hardened():
    with _client() as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"schema": "bella.service-live.v1", "status": "alive"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert "access-control-allow-origin" not in response.headers
    assert response.headers["x-request-id"]


def test_chat_requires_bearer_auth_and_never_echoes_prompt_in_error():
    secret_prompt = "PRIVATE-PROMPT-CONTENT"
    with _client() as client:
        response = client.post("/v1/chat", json={"prompt": secret_prompt})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"] == "unauthorized"
    assert secret_prompt not in response.text


def test_failed_authentication_is_limited_without_blocking_valid_token():
    config = _config(
        auth_failure_limit_requests=1,
        auth_failure_limit_window_seconds=60,
    )
    wrong = {"Authorization": "Bearer " + "x" * 32}
    with _client(config=config) as client:
        first = client.post("/v1/chat", headers=wrong, json={"prompt": "hello"})
        second = client.post("/v1/chat", headers=wrong, json={"prompt": "hello"})
        valid = client.post("/v1/chat", headers=AUTH, json={"prompt": "hello"})
    assert first.status_code == 401
    assert second.status_code == 429
    assert second.json()["error"] == "auth_rate_limited"
    assert second.json()["retry_after_seconds"] >= 1
    assert valid.status_code == 200


def test_deterministic_chat_returns_no_action_and_hides_trace_by_default():
    with _client() as client:
        response = client.post(
            "/v1/chat",
            headers=AUTH,
            json={"prompt": "hello", "mode": "life"},
        )
    payload = response.json()
    assert response.status_code == 200
    assert payload["schema"] == "bella.service-chat.v1"
    assert payload["response"].startswith("Hello")
    assert payload["handled_deterministically"] is True
    assert payload["external_action_performed"] is False
    assert payload["memory_count"] == 0
    assert "trace" not in payload


def test_security_block_maps_to_403_without_execution():
    harness = FakeHarness(
        HarnessResult(
            action=Action.BLOCK,
            response="I cannot help with that request.",
            category="prompt_injection",
            handled_deterministically=True,
        )
    )
    with _client(harness=harness) as client:
        response = client.post(
            "/v1/chat",
            headers=AUTH,
            json={"prompt": "blocked request"},
        )
    assert response.status_code == 403
    assert response.json()["action"] == "block"
    assert response.json()["external_action_performed"] is False


def test_trace_requires_explicit_request_and_backend_failure_maps_to_503():
    result = HarnessResult(
        action=Action.BLOCK,
        response="Backend unavailable.",
        category="backend_unavailable",
        handled_deterministically=False,
        memory_ids=("memory-1",),
        memory_explanations=("matched invoice",),
        operator_reasons=("communication requested",),
        operator_plan=("draft only",),
    )
    harness = FakeHarness(result)
    with _client(harness=harness) as client:
        hidden = client.post("/v1/chat", headers=AUTH, json={"prompt": "Explain invoice"})
        visible = client.post(
            "/v1/chat",
            headers=AUTH,
            json={"prompt": "Explain invoice", "trace": True},
        )
    assert hidden.status_code == 503
    assert hidden.json()["memory_count"] == 1
    assert "trace" not in hidden.json()
    assert visible.status_code == 503
    assert visible.json()["trace"]["memory_ids"] == ["memory-1"]
    assert visible.json()["external_action_performed"] is False


def test_invalid_request_mode_prompt_size_and_body_are_bounded():
    config = _config(max_prompt_chars=100, max_body_bytes=1024)
    with _client(config=config) as client:
        invalid = client.post(
            "/v1/chat",
            headers=AUTH,
            json={"prompt": "hello", "unexpected": "do-not-echo"},
        )
        invalid_mode = client.post(
            "/v1/chat",
            headers=AUTH,
            json={"prompt": "hello", "mode": "god-mode"},
        )
        prompt_too_large = client.post(
            "/v1/chat",
            headers=AUTH,
            json={"prompt": "x" * 101},
        )
        body_too_large = client.post(
            "/v1/chat",
            headers={**AUTH, "Content-Type": "application/json"},
            content=b"x" * 1025,
        )
    assert invalid.status_code == 422
    assert invalid.json()["error"] == "invalid_request"
    assert "do-not-echo" not in invalid.text
    assert invalid_mode.status_code == 422
    assert invalid_mode.json()["error"] == "invalid_mode"
    assert prompt_too_large.status_code == 413
    assert prompt_too_large.json()["error"] == "prompt_too_large"
    assert body_too_large.status_code == 413
    assert body_too_large.json()["error"] == "request_too_large"


def test_rate_limit_is_applied_after_successful_authentication():
    config = _config(rate_limit_requests=1, rate_limit_window_seconds=60)
    with _client(config=config) as client:
        first = client.post("/v1/chat", headers=AUTH, json={"prompt": "hello"})
        second = client.post("/v1/chat", headers=AUTH, json={"prompt": "hello"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"] == "rate_limited"
    assert second.json()["retry_after_seconds"] >= 1


def test_trusted_hosts_docs_and_action_routes_are_closed():
    with _client() as client:
        bad_host = client.get("/health/live", headers={"Host": "evil.example.com"})
        docs = client.get("/docs")
        openapi = client.get("/openapi.json")
        actions = client.post("/v1/actions", headers=AUTH, json={})
    assert bad_host.status_code == 400
    assert docs.status_code == 404
    assert openapi.status_code == 404
    assert actions.status_code == 404


def test_ready_requires_auth_and_uses_prompt_free_live_doctor(monkeypatch):
    monkeypatch.setattr(
        "bella_harness.backends.ollama_backend.OllamaBackend.health_check",
        lambda self: True,
    )
    with _client() as client:
        denied = client.get("/health/ready")
        ready = client.get("/health/ready", headers=AUTH)
    assert denied.status_code == 401
    assert ready.status_code == 200
    payload = ready.json()
    assert payload["schema"] == "bella.service-ready.v1"
    assert payload["ready"] is True
    assert any(check["name"] == "http_service" for check in payload["checks"])


def test_safe_request_id_is_preserved_and_prompt_is_not_logged(caplog):
    caplog.set_level(logging.INFO, logger="bella_harness.service")
    prompt = "DO-NOT-LOG-THIS-PROMPT"
    with _client() as client:
        response = client.post(
            "/v1/chat",
            headers={**AUTH, "X-Request-ID": "request-safe-123"},
            json={"prompt": prompt},
        )
    assert response.headers["x-request-id"] == "request-safe-123"
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "request-safe-123" in logs
    assert "/v1/chat" in logs
    assert prompt not in logs
