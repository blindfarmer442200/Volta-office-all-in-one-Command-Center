"""Service-aware extension of Bella's production doctor."""

from __future__ import annotations

from typing import Mapping

from bella_harness.doctor import DoctorCheck, DoctorReport, run_doctor
from bella_harness.service.settings import (
    ServiceConfigurationError,
    ServiceSettings,
    resolve_service_token,
)


def run_service_doctor(
    config: dict,
    *,
    live: bool = False,
    token_override: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> DoctorReport:
    """Run core checks and append service binding/authentication validation."""
    base = run_doctor(config, live=live)
    checks = list(base.checks)
    raw = config.get("service", {}) or {}
    enabled = isinstance(raw, dict) and raw.get("enabled", False) is True
    if not enabled:
        checks.append(
            DoctorCheck(
                name="http_service",
                status="skip",
                critical=False,
                message="Authenticated HTTP service is disabled.",
            )
        )
    else:
        try:
            settings = ServiceSettings.from_config(config)
            if token_override is None:
                resolve_service_token(settings.token_env, environment=environment)
            else:
                resolve_service_token(
                    "BELLA_EXPLICIT_SERVICE_TOKEN",
                    environment={"BELLA_EXPLICIT_SERVICE_TOKEN": token_override},
                )
            checks.append(
                DoctorCheck(
                    name="http_service",
                    status="pass",
                    critical=True,
                    message=(
                        "Authenticated HTTP service configuration is valid; "
                        f"bind={settings.host}:{settings.port}; "
                        f"remote_bind={str(settings.remote_bind).lower()}."
                    ),
                )
            )
        except ServiceConfigurationError as exc:
            checks.append(
                DoctorCheck(
                    name="http_service",
                    status="fail",
                    critical=True,
                    message=f"HTTP service configuration failed validation: {exc}",
                )
            )

    ready = not any(check.critical and check.status == "fail" for check in checks)
    return DoctorReport(
        schema=base.schema,
        package_version=base.package_version,
        ready=ready,
        live_checks_requested=base.live_checks_requested,
        checks=tuple(checks),
    )
