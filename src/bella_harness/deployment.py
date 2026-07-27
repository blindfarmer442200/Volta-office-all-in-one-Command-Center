"""Live host acceptance gate for a deployed Bella service and Ollama model."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from bella_harness.backends import BackendAbstraction, BackendError
from bella_harness.backends.network import (
    PrivateEndpointError,
    normalize_private_http_base_url,
)
from bella_harness.evaluation import BellaEvaluationGate, EvaluationError
from bella_harness.release_manifest import read_project_version
from bella_harness.service.doctor import run_service_doctor
from bella_harness.service.settings import ServiceConfigurationError, ServiceSettings


DEPLOYMENT_REPORT_SCHEMA = "bella.deployment-acceptance.v1"
MAX_SERVICE_RESPONSE_BYTES = 1_000_000


class DeploymentAcceptanceError(RuntimeError):
    """Raised when acceptance cannot run safely or its evidence is malformed."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


@dataclass(frozen=True)
class DeploymentCheck:
    name: str
    status: str
    critical: bool
    message: str
    evidence: dict[str, Any]

    def __post_init__(self) -> None:
        if self.status not in {"pass", "fail", "skip"}:
            raise DeploymentAcceptanceError("deployment check status is invalid")
        if not self.name or len(self.name) > 120:
            raise DeploymentAcceptanceError("deployment check name is invalid")
        if not self.message or len(self.message) > 1000:
            raise DeploymentAcceptanceError("deployment check message is invalid")
        if not isinstance(self.critical, bool) or not isinstance(self.evidence, dict):
            raise DeploymentAcceptanceError("deployment check metadata is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "critical": self.critical,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class DeploymentReport:
    schema: str
    package_version: str
    generated_at: str
    service_url: str
    model: str
    accepted: bool
    checks: tuple[DeploymentCheck, ...]
    evaluation_report_sha256: str | None
    report_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "package_version": self.package_version,
            "generated_at": self.generated_at,
            "service_url": self.service_url,
            "model": self.model,
            "accepted": self.accepted,
            "checks": [check.to_dict() for check in self.checks],
            "evaluation_report_sha256": self.evaluation_report_sha256,
            "report_sha256": self.report_sha256,
        }


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    if len(response.content) > MAX_SERVICE_RESPONSE_BYTES:
        raise DeploymentAcceptanceError("service response exceeds the 1 MiB limit")
    try:
        payload = response.json()
    except (ValueError, UnicodeError) as exc:
        raise DeploymentAcceptanceError("service response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise DeploymentAcceptanceError("service response JSON must be an object")
    return payload


def _service_checks(
    *,
    service_url: str,
    service_token: str,
    client_factory: Any = httpx.Client,
) -> list[DeploymentCheck]:
    checks: list[DeploymentCheck] = []
    authorization = {"Authorization": f"Bearer {service_token}"}
    wrong_authorization = {"Authorization": f"Bearer {secrets.token_urlsafe(48)}"}
    try:
        with client_factory(
            base_url=service_url,
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            live = client.get("/health/live")
            live_payload = _safe_json(live)
            live_ok = (
                live.status_code == 200
                and live_payload.get("schema") == "bella.service-live.v1"
                and live_payload.get("status") == "alive"
            )
            checks.append(
                DeploymentCheck(
                    name="service_liveness",
                    status="pass" if live_ok else "fail",
                    critical=True,
                    message=(
                        "Minimal unauthenticated liveness is healthy."
                        if live_ok
                        else "Minimal liveness response is invalid."
                    ),
                    evidence={"http_status": live.status_code},
                )
            )

            unauthorized = client.post(
                "/v1/chat",
                headers=wrong_authorization,
                json={"prompt": "hello", "mode": "default"},
            )
            unauthorized_payload = _safe_json(unauthorized)
            auth_ok = (
                unauthorized.status_code == 401
                and unauthorized_payload.get("error") == "unauthorized"
            )
            checks.append(
                DeploymentCheck(
                    name="service_authentication",
                    status="pass" if auth_ok else "fail",
                    critical=True,
                    message=(
                        "Invalid bearer tokens are rejected."
                        if auth_ok
                        else "Invalid bearer-token rejection failed."
                    ),
                    evidence={"http_status": unauthorized.status_code},
                )
            )

            ready = client.get("/health/ready", headers=authorization)
            ready_payload = _safe_json(ready)
            ready_ok = (
                ready.status_code == 200
                and ready_payload.get("schema") == "bella.service-ready.v1"
                and ready_payload.get("ready") is True
            )
            checks.append(
                DeploymentCheck(
                    name="service_readiness",
                    status="pass" if ready_ok else "fail",
                    critical=True,
                    message=(
                        "Authenticated prompt-free readiness is healthy."
                        if ready_ok
                        else "Authenticated readiness failed."
                    ),
                    evidence={"http_status": ready.status_code},
                )
            )

            chat = client.post(
                "/v1/chat",
                headers=authorization,
                json={"prompt": "hello", "mode": "life"},
            )
            chat_payload = _safe_json(chat)
            chat_ok = (
                chat.status_code == 200
                and chat_payload.get("schema") == "bella.service-chat.v1"
                and chat_payload.get("handled_deterministically") is True
                and chat_payload.get("external_action_performed") is False
                and "trace" not in chat_payload
            )
            checks.append(
                DeploymentCheck(
                    name="service_deterministic_chat",
                    status="pass" if chat_ok else "fail",
                    critical=True,
                    message=(
                        "Authenticated deterministic chat is safe and trace-minimal."
                        if chat_ok
                        else "Authenticated deterministic chat contract failed."
                    ),
                    evidence={"http_status": chat.status_code},
                )
            )

            action = client.post("/v1/actions", headers=authorization, json={})
            action_closed = action.status_code == 404
            checks.append(
                DeploymentCheck(
                    name="service_action_route_closed",
                    status="pass" if action_closed else "fail",
                    critical=True,
                    message=(
                        "No HTTP action route exists."
                        if action_closed
                        else "An unexpected HTTP action route is reachable."
                    ),
                    evidence={"http_status": action.status_code},
                )
            )
    except (httpx.HTTPError, OSError, DeploymentAcceptanceError) as exc:
        checks.append(
            DeploymentCheck(
                name="service_connection",
                status="fail",
                critical=True,
                message=f"Service acceptance request failed: {type(exc).__name__}.",
                evidence={},
            )
        )
    return checks


def _container_check(
    container_name: str | None,
    *,
    runner: Any = subprocess.run,
) -> DeploymentCheck:
    if not container_name:
        return DeploymentCheck(
            name="container_hardening",
            status="skip",
            critical=False,
            message="Container inspection was not requested for this host deployment.",
            evidence={},
        )
    if len(container_name) > 128 or any(character.isspace() for character in container_name):
        raise DeploymentAcceptanceError("container name is malformed")
    try:
        completed = runner(
            ["docker", "inspect", container_name],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
        payload = json.loads(completed.stdout)
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise DeploymentAcceptanceError("docker inspect response is invalid")
        inspection = payload[0]
        config = inspection.get("Config") or {}
        host_config = inspection.get("HostConfig") or {}
        state = inspection.get("State") or {}
        cap_drop = {str(value).upper() for value in host_config.get("CapDrop") or []}
        security_opt = [str(value).lower() for value in host_config.get("SecurityOpt") or []]
        checks = {
            "running": state.get("Running") is True,
            "non_root": str(config.get("User")) == "10001:10001",
            "read_only": host_config.get("ReadonlyRootfs") is True,
            "capabilities_dropped": "ALL" in cap_drop,
            "no_new_privileges": any("no-new-privileges" in value for value in security_opt),
        }
        passed = all(checks.values())
        return DeploymentCheck(
            name="container_hardening",
            status="pass" if passed else "fail",
            critical=True,
            message=(
                "Running container satisfies the hardened runtime contract."
                if passed
                else "Running container does not satisfy the hardened runtime contract."
            ),
            evidence=checks,
        )
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        DeploymentAcceptanceError,
    ) as exc:
        return DeploymentCheck(
            name="container_hardening",
            status="fail",
            critical=True,
            message=f"Container inspection failed: {type(exc).__name__}.",
            evidence={},
        )


def _report_core(
    *,
    package_version: str,
    generated_at: str,
    service_url: str,
    model: str,
    accepted: bool,
    checks: tuple[DeploymentCheck, ...],
    evaluation_report_sha256: str | None,
) -> dict[str, Any]:
    return {
        "schema": DEPLOYMENT_REPORT_SCHEMA,
        "package_version": package_version,
        "generated_at": generated_at,
        "service_url": service_url,
        "model": model,
        "accepted": accepted,
        "checks": [check.to_dict() for check in checks],
        "evaluation_report_sha256": evaluation_report_sha256,
    }


def run_deployment_acceptance(
    config: dict,
    *,
    service_token: str,
    service_url: str,
    model: str | None,
    evaluation_report_path: str | Path,
    deployment_report_path: str | Path,
    container_name: str | None = None,
    client_factory: Any = httpx.Client,
    container_runner: Any = subprocess.run,
    gate_factory: Any = BellaEvaluationGate,
) -> DeploymentReport:
    """Run live host gates and write hashed evaluation/deployment evidence."""
    try:
        normalized_url = normalize_private_http_base_url(service_url)
    except PrivateEndpointError as exc:
        raise DeploymentAcceptanceError(f"unsafe service URL: {exc}") from exc

    settings = ServiceSettings.from_config(config)
    if not settings.enabled:
        raise DeploymentAcceptanceError("service must be enabled for deployment acceptance")
    if not isinstance(service_token, str) or len(service_token) < 32:
        raise DeploymentAcceptanceError("a strong service token is required")

    checks: list[DeploymentCheck] = []
    doctor = run_service_doctor(
        config,
        live=True,
        token_override=service_token,
    )
    checks.append(
        DeploymentCheck(
            name="production_doctor",
            status="pass" if doctor.ready else "fail",
            critical=True,
            message=(
                "Live production doctor passed."
                if doctor.ready
                else "Live production doctor reported a critical failure."
            ),
            evidence={
                "package_version": doctor.package_version,
                "critical_failures": sum(
                    1
                    for check in doctor.checks
                    if check.critical and check.status == "fail"
                ),
            },
        )
    )

    backends = BackendAbstraction(config)
    try:
        ollama = backends.get("ollama")
    except BackendError as exc:
        raise DeploymentAcceptanceError("Ollama must be enabled for acceptance") from exc
    selected_model = model or (config.get("evaluation", {}) or {}).get("model") or ollama.model
    if not isinstance(selected_model, str) or not selected_model.strip():
        raise DeploymentAcceptanceError("an exact Ollama model tag is required")

    evaluation_sha: str | None = None
    try:
        gate = gate_factory(
            ollama,
            backend_name="ollama",
            model=selected_model,
        )
        evaluation = gate.run()
        gate.write_report(evaluation, evaluation_report_path)
        evaluation_sha = evaluation.report_sha256
        evaluation_ok = (
            evaluation.accepted is True
            and evaluation.passed_count == evaluation.total
            and evaluation.total == 18
        )
        checks.append(
            DeploymentCheck(
                name="live_model_evaluation",
                status="pass" if evaluation_ok else "fail",
                critical=True,
                message=(
                    "The exact live Ollama model passed all 18 Bella scenarios."
                    if evaluation_ok
                    else "The exact live Ollama model failed one or more scenarios."
                ),
                evidence={
                    "model": selected_model,
                    "passed": evaluation.passed_count,
                    "total": evaluation.total,
                    "report_sha256": evaluation.report_sha256,
                },
            )
        )
    except (EvaluationError, BackendError, OSError, ValueError) as exc:
        checks.append(
            DeploymentCheck(
                name="live_model_evaluation",
                status="fail",
                critical=True,
                message=f"Live model evaluation failed: {type(exc).__name__}.",
                evidence={"model": selected_model},
            )
        )

    checks.extend(
        _service_checks(
            service_url=normalized_url,
            service_token=service_token,
            client_factory=client_factory,
        )
    )
    checks.append(_container_check(container_name, runner=container_runner))

    checks_tuple = tuple(checks)
    accepted = not any(check.critical and check.status != "pass" for check in checks_tuple)
    generated_at = datetime.now(timezone.utc).isoformat()
    version = read_project_version(Path(__file__).resolve().parents[2] / "pyproject.toml")
    core = _report_core(
        package_version=version,
        generated_at=generated_at,
        service_url=normalized_url,
        model=selected_model,
        accepted=accepted,
        checks=checks_tuple,
        evaluation_report_sha256=evaluation_sha,
    )
    report_sha256 = hashlib.sha256(_canonical_json(core).encode("utf-8")).hexdigest()
    report = DeploymentReport(
        schema=DEPLOYMENT_REPORT_SCHEMA,
        package_version=version,
        generated_at=generated_at,
        service_url=normalized_url,
        model=selected_model,
        accepted=accepted,
        checks=checks_tuple,
        evaluation_report_sha256=evaluation_sha,
        report_sha256=report_sha256,
    )
    _atomic_write(
        Path(deployment_report_path),
        (json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        ),
    )
    return report


def verify_deployment_report(path: str | Path) -> bool:
    """Verify deployment report hash, schema, checks, and acceptance state."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return False
        provided = payload.pop("report_sha256", None)
        if not isinstance(provided, str):
            return False
        if payload.get("schema") != DEPLOYMENT_REPORT_SCHEMA:
            return False
        checks = payload.get("checks")
        if not isinstance(checks, list) or not checks:
            return False
        accepted = not any(
            isinstance(check, dict)
            and check.get("critical") is True
            and check.get("status") != "pass"
            for check in checks
        )
        if payload.get("accepted") is not accepted:
            return False
        expected = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return hmac.compare_digest(provided, expected)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
