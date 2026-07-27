"""Validated settings for Bella's authenticated HTTP service."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from typing import Mapping


_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_LOG_LEVELS = frozenset({"critical", "error", "warning", "info", "debug"})


class ServiceConfigurationError(ValueError):
    """Raised when the HTTP service would start with unsafe settings."""


def _bounded_int(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ServiceConfigurationError(f"service.{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ServiceConfigurationError(
            f"service.{name} must be between {minimum} and {maximum}"
        )
    return value


def _bounded_number(
    value: object,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ServiceConfigurationError(f"service.{name} must be numeric")
    normalized = float(value)
    if not minimum <= normalized <= maximum:
        raise ServiceConfigurationError(
            f"service.{name} must be between {minimum:g} and {maximum:g}"
        )
    return normalized


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validate_bind_host(host: object, allow_remote_bind: bool) -> str:
    if not isinstance(host, str) or not host.strip():
        raise ServiceConfigurationError("service.host must be a non-empty string")
    normalized = host.strip().lower()
    if len(normalized) > 253:
        raise ServiceConfigurationError("service.host is too long")
    if _is_loopback_host(normalized):
        return normalized
    try:
        ipaddress.ip_address(normalized)
    except ValueError as exc:
        raise ServiceConfigurationError(
            "service.host must be localhost or a literal IP address"
        ) from exc
    if not allow_remote_bind:
        raise ServiceConfigurationError(
            "non-loopback service binding requires service.allow_remote_bind=true"
        )
    return normalized


def _validate_trusted_hosts(value: object, *, remote: bool) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ServiceConfigurationError("service.trusted_hosts must be a list")
    if not 1 <= len(value) <= 32:
        raise ServiceConfigurationError("service.trusted_hosts must contain 1 to 32 hosts")
    hosts: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ServiceConfigurationError("trusted hosts must be non-empty strings")
        host = item.strip().lower()
        if host == "*" or "*" in host:
            raise ServiceConfigurationError("wildcard trusted hosts are not allowed")
        if len(host) > 253 or any(character.isspace() for character in host):
            raise ServiceConfigurationError("trusted host is malformed")
        hosts.append(host)
    unique = tuple(dict.fromkeys(hosts))
    if remote and all(_is_loopback_host(host) for host in unique):
        raise ServiceConfigurationError(
            "remote binding requires at least one explicit non-loopback trusted host"
        )
    return unique


def resolve_service_token(
    token_env: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if environment is None else environment
    token = source.get(token_env)
    if token is None:
        raise ServiceConfigurationError(
            f"service token environment variable {token_env!r} is not set"
        )
    if not isinstance(token, str) or not 32 <= len(token) <= 512:
        raise ServiceConfigurationError(
            "service token must contain between 32 and 512 characters"
        )
    if token != token.strip() or any(ord(character) < 33 or ord(character) == 127 for character in token):
        raise ServiceConfigurationError(
            "service token must not contain whitespace or control characters"
        )
    return token


@dataclass(frozen=True)
class ServiceSettings:
    enabled: bool
    host: str
    port: int
    allow_remote_bind: bool
    token_env: str
    max_body_bytes: int
    max_prompt_chars: int
    max_concurrent_requests: int
    request_timeout_seconds: float
    rate_limit_requests: int
    rate_limit_window_seconds: int
    auth_failure_limit_requests: int
    auth_failure_limit_window_seconds: int
    trusted_hosts: tuple[str, ...]
    log_level: str

    @property
    def remote_bind(self) -> bool:
        return not _is_loopback_host(self.host)

    @classmethod
    def from_config(
        cls,
        config: dict,
        *,
        host_override: str | None = None,
        port_override: int | None = None,
    ) -> "ServiceSettings":
        raw = config.get("service", {}) or {}
        if not isinstance(raw, dict):
            raise ServiceConfigurationError("service configuration must be a mapping")
        enabled = raw.get("enabled", False)
        allow_remote_bind = raw.get("allow_remote_bind", False)
        if not isinstance(enabled, bool):
            raise ServiceConfigurationError("service.enabled must be boolean")
        if not isinstance(allow_remote_bind, bool):
            raise ServiceConfigurationError("service.allow_remote_bind must be boolean")

        host = _validate_bind_host(
            host_override if host_override is not None else raw.get("host", "127.0.0.1"),
            allow_remote_bind,
        )
        port = _bounded_int(
            port_override if port_override is not None else raw.get("port", 8765),
            name="port",
            minimum=1024,
            maximum=65535,
        )
        token_env = raw.get("token_env", "BELLA_SERVICE_TOKEN")
        if not isinstance(token_env, str) or not _ENV_NAME_RE.fullmatch(token_env):
            raise ServiceConfigurationError(
                "service.token_env must name an uppercase environment variable"
            )
        log_level = raw.get("log_level", "info")
        if not isinstance(log_level, str) or log_level.lower() not in _LOG_LEVELS:
            raise ServiceConfigurationError(
                "service.log_level must be critical, error, warning, info, or debug"
            )

        return cls(
            enabled=enabled,
            host=host,
            port=port,
            allow_remote_bind=allow_remote_bind,
            token_env=token_env,
            max_body_bytes=_bounded_int(
                raw.get("max_body_bytes", 65_536),
                name="max_body_bytes",
                minimum=1_024,
                maximum=1_048_576,
            ),
            max_prompt_chars=_bounded_int(
                raw.get("max_prompt_chars", 32_000),
                name="max_prompt_chars",
                minimum=100,
                maximum=128_000,
            ),
            max_concurrent_requests=_bounded_int(
                raw.get("max_concurrent_requests", 4),
                name="max_concurrent_requests",
                minimum=1,
                maximum=64,
            ),
            request_timeout_seconds=_bounded_number(
                raw.get("request_timeout_seconds", 90),
                name="request_timeout_seconds",
                minimum=1,
                maximum=300,
            ),
            rate_limit_requests=_bounded_int(
                raw.get("rate_limit_requests", 60),
                name="rate_limit_requests",
                minimum=1,
                maximum=10_000,
            ),
            rate_limit_window_seconds=_bounded_int(
                raw.get("rate_limit_window_seconds", 60),
                name="rate_limit_window_seconds",
                minimum=1,
                maximum=3_600,
            ),
            auth_failure_limit_requests=_bounded_int(
                raw.get("auth_failure_limit_requests", 20),
                name="auth_failure_limit_requests",
                minimum=1,
                maximum=10_000,
            ),
            auth_failure_limit_window_seconds=_bounded_int(
                raw.get("auth_failure_limit_window_seconds", 60),
                name="auth_failure_limit_window_seconds",
                minimum=1,
                maximum=3_600,
            ),
            trusted_hosts=_validate_trusted_hosts(
                raw.get("trusted_hosts", ["localhost", "127.0.0.1", "::1"]),
                remote=not _is_loopback_host(host),
            ),
            log_level=log_level.lower(),
        )
