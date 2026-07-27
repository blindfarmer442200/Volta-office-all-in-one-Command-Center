"""Production-readiness checks for an installed Bella harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from bella_harness.backends import BackendAbstraction, BackendError
from bella_harness.backends.ollama_backend import OllamaBackend
from bella_harness.config import DEFAULT_CONFIG_PATH
from bella_harness.memory import JsonlMemoryStore, MemoryStoreError
from bella_harness.tuning import SQLiteTuningStore, TuningError


DOCTOR_SCHEMA = "bella.doctor-report.v1"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    critical: bool
    message: str

    def __post_init__(self) -> None:
        if self.status not in {"pass", "warn", "fail", "skip"}:
            raise ValueError(f"invalid doctor status: {self.status}")


@dataclass(frozen=True)
class DoctorReport:
    schema: str
    package_version: str
    ready: bool
    live_checks_requested: bool
    checks: tuple[DoctorCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "package_version": self.package_version,
            "ready": self.ready,
            "live_checks_requested": self.live_checks_requested,
            "checks": [asdict(check) for check in self.checks],
        }


def _package_version() -> str:
    try:
        return version("bella-harness")
    except PackageNotFoundError:
        return "source-tree"


def _pass(name: str, message: str, *, critical: bool = True) -> DoctorCheck:
    return DoctorCheck(name=name, status="pass", critical=critical, message=message)


def _warn(name: str, message: str, *, critical: bool = False) -> DoctorCheck:
    return DoctorCheck(name=name, status="warn", critical=critical, message=message)


def _fail(name: str, message: str, *, critical: bool = True) -> DoctorCheck:
    return DoctorCheck(name=name, status="fail", critical=critical, message=message)


def _skip(name: str, message: str, *, critical: bool = False) -> DoctorCheck:
    return DoctorCheck(name=name, status="skip", critical=critical, message=message)


def _bool_check(
    checks: list[DoctorCheck],
    *,
    name: str,
    actual: bool,
    expected: bool,
    pass_message: str,
    fail_message: str,
    critical: bool = True,
) -> None:
    if actual is expected:
        checks.append(_pass(name, pass_message, critical=critical))
    else:
        checks.append(_fail(name, fail_message, critical=critical))


def run_doctor(config: dict, *, live: bool = False) -> DoctorReport:
    """Run offline policy/storage checks and optional prompt-free live checks."""
    checks: list[DoctorCheck] = []

    if DEFAULT_CONFIG_PATH.is_file():
        checks.append(
            _pass(
                "packaged_config",
                "The installed Bella package contains its default configuration.",
            )
        )
    else:
        checks.append(
            _fail(
                "packaged_config",
                "The installed Bella package is missing its default configuration.",
            )
        )

    harness = config.get("harness", {}) or {}
    _bool_check(
        checks,
        name="fail_closed",
        actual=bool(harness.get("fail_closed", True)),
        expected=True,
        pass_message="Harness failure handling is fail-closed.",
        fail_message="Harness failure handling is not fail-closed.",
    )
    output_scanning = harness.get("output_scanning", {}) or {}
    _bool_check(
        checks,
        name="output_scanning",
        actual=bool(output_scanning.get("enabled", True)),
        expected=True,
        pass_message="Model output scanning is enabled.",
        fail_message="Model output scanning is disabled.",
    )

    operator = config.get("operator", {}) or {}
    _bool_check(
        checks,
        name="operator",
        actual=bool(operator.get("enabled", False)),
        expected=True,
        pass_message="Bella Operator policy is enabled.",
        fail_message="Bella Operator policy is disabled.",
    )

    action_gate = config.get("action_gate", {}) or {}
    action_enabled = bool(action_gate.get("enabled", False))
    preview_ttl = action_gate.get("preview_ttl_seconds", 900)
    authorization_ttl = action_gate.get("authorization_ttl_seconds", 300)
    if (
        action_enabled
        and isinstance(preview_ttl, int)
        and not isinstance(preview_ttl, bool)
        and 1 <= preview_ttl <= 900
        and isinstance(authorization_ttl, int)
        and not isinstance(authorization_ttl, bool)
        and 1 <= authorization_ttl <= 300
    ):
        checks.append(
            _pass(
                "action_gate",
                "Mock-only Action Gate is enabled with bounded authorization lifetimes.",
            )
        )
    else:
        checks.append(
            _fail(
                "action_gate",
                "Action Gate is disabled or its lifetimes exceed safe bounds.",
            )
        )

    evaluation = config.get("evaluation", {}) or {}
    evaluation_ok = (
        bool(evaluation.get("enabled", False))
        and evaluation.get("backend", "ollama") == "ollama"
        and bool(evaluation.get("require_all", True))
    )
    if evaluation_ok:
        checks.append(
            _pass(
                "evaluation_gate",
                "Bella model evaluation is Ollama-only and requires every scenario.",
            )
        )
    else:
        checks.append(
            _fail(
                "evaluation_gate",
                "Bella model evaluation is disabled, not Ollama-only, or not all-or-nothing.",
            )
        )

    tuning = config.get("tuning", {}) or {}
    tuning_automation_safe = all(
        tuning.get(name, False) is False
        for name in (
            "automatic_capture",
            "automatic_upload",
            "automatic_training",
            "automatic_model_activation",
        )
    )
    if tuning_automation_safe:
        checks.append(
            _pass(
                "tuning_automation",
                "Automatic capture, upload, training, and model activation are disabled.",
            )
        )
    else:
        checks.append(
            _fail(
                "tuning_automation",
                "One or more automatic tuning actions are enabled.",
            )
        )

    memory = config.get("memory", {}) or {}
    memory_path = memory.get("store_path")
    if memory_path:
        try:
            count = len(JsonlMemoryStore(memory_path).list_records())
            checks.append(
                _pass(
                    "memory_store",
                    f"Configured Mind Trace store verified with {count} records.",
                )
            )
        except MemoryStoreError as exc:
            checks.append(_fail("memory_store", f"Mind Trace store failed verification: {exc}"))
    else:
        checks.append(
            _warn(
                "memory_store",
                "No persistent Mind Trace store is configured; Bella will use no saved memory.",
            )
        )

    tuning_path = tuning.get("store_path")
    if tuning_path:
        try:
            verified = SQLiteTuningStore(tuning_path).verify_integrity()
        except TuningError as exc:
            checks.append(_fail("tuning_store", f"Tuning store failed to open: {exc}"))
        else:
            if verified:
                checks.append(_pass("tuning_store", "Configured tuning store passed integrity checks."))
            else:
                checks.append(_fail("tuning_store", "Configured tuning store failed integrity checks."))
    else:
        checks.append(
            _warn(
                "tuning_store",
                "No persistent tuning store is configured; explicit review commands require --db.",
            )
        )

    backends_config = config.get("backends", {}) or {}
    enabled_names = [
        name
        for name, backend_config in backends_config.items()
        if isinstance(backend_config, dict) and backend_config.get("enabled")
    ]
    default_backend = harness.get("default_backend")
    if not enabled_names:
        checks.append(_fail("backends", "No model backend is enabled."))
    elif default_backend not in enabled_names:
        checks.append(_fail("backends", "The configured default backend is not enabled."))
    else:
        checks.append(
            _pass(
                "backends",
                f"Default backend {default_backend!r} is enabled; {len(enabled_names)} backend(s) configured.",
            )
        )

    cloud_enabled = sorted(name for name in enabled_names if name != "ollama")
    if cloud_enabled:
        checks.append(
            _warn(
                "cloud_backends",
                "Cloud backends are enabled; verify consent and data-routing policy before production use.",
            )
        )
    else:
        checks.append(_pass("cloud_backends", "No cloud backend is enabled.", critical=False))

    ollama: OllamaBackend | None = None
    if "ollama" in enabled_names:
        try:
            abstraction = BackendAbstraction(config)
            candidate = abstraction.get("ollama")
            if not isinstance(candidate, OllamaBackend):
                raise BackendError("configured Ollama backend has an unexpected implementation")
            ollama = candidate
            checks.append(
                _pass(
                    "ollama_endpoint",
                    f"Ollama endpoint is restricted to private transport at {ollama.base_url}.",
                )
            )
        except (BackendError, KeyError) as exc:
            checks.append(_fail("ollama_endpoint", f"Ollama configuration failed validation: {exc}"))
    else:
        checks.append(_warn("ollama_endpoint", "Ollama is not enabled.", critical=False))

    if live:
        if ollama is None:
            checks.append(_fail("ollama_live", "Live Ollama check requested but Ollama is unavailable."))
        elif ollama.health_check():
            checks.append(_pass("ollama_live", "Ollama responded to a prompt-free health check."))
        else:
            checks.append(_fail("ollama_live", "Ollama did not pass the prompt-free health check."))
    else:
        checks.append(
            _skip(
                "ollama_live",
                "Live Ollama check was not requested. Run `bella doctor --live` on the host.",
            )
        )

    ready = not any(check.critical and check.status == "fail" for check in checks)
    return DoctorReport(
        schema=DOCTOR_SCHEMA,
        package_version=_package_version(),
        ready=ready,
        live_checks_requested=live,
        checks=tuple(checks),
    )
