"""Network boundaries for local/private model backends."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


class PrivateEndpointError(ValueError):
    """Raised when a local backend endpoint could expose data to a public host."""


def _allowed_private_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Some Python/ipaddress versions classify IPv6 ::1 as reserved. Loopback is
    # still safe and must be accepted before the broader reserved-address block.
    if address.is_loopback:
        return True
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        return False
    return address.is_private or address.is_link_local


def normalize_private_http_base_url(value: str) -> str:
    """Validate and normalize an HTTP(S) loopback or literal private-IP root URL.

    Hostnames other than ``localhost`` are rejected to avoid DNS rebinding and
    accidental public egress. A path prefix, query, fragment, or embedded
    credential is also rejected because Ollama is expected at the API root.
    """
    if not isinstance(value, str) or not value.strip():
        raise PrivateEndpointError("backend base_url must be a non-empty string")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"}:
        raise PrivateEndpointError("backend base_url must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise PrivateEndpointError("backend base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise PrivateEndpointError("backend base_url must not contain a query or fragment")
    if parsed.path not in {"", "/"}:
        raise PrivateEndpointError("backend base_url must point to the API root")
    host = parsed.hostname
    if not host:
        raise PrivateEndpointError("backend base_url must include a host")

    normalized_host = host.lower()
    if normalized_host != "localhost":
        try:
            address = ipaddress.ip_address(normalized_host)
        except ValueError as exc:
            raise PrivateEndpointError(
                "backend host must be localhost or a literal private IP address"
            ) from exc
        if not _allowed_private_ip(address):
            raise PrivateEndpointError("backend IP address is not loopback or private")

    try:
        port = parsed.port
    except ValueError as exc:
        raise PrivateEndpointError("backend base_url contains an invalid port") from exc
    host_for_url = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    netloc = host_for_url if port is None else f"{host_for_url}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))


def assert_private_resolution(host: str) -> None:
    """Resolve localhost and fail if any result is not loopback.

    Literal IP addresses are already validated without DNS. Other hostnames are
    rejected by :func:`normalize_private_http_base_url`.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not _allowed_private_ip(address):
            raise PrivateEndpointError("backend IP address is not loopback or private")
        return
    if host.lower() != "localhost":
        raise PrivateEndpointError("only localhost may use DNS resolution")
    try:
        results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise PrivateEndpointError(f"unable to resolve localhost: {exc}") from exc
    resolved = {item[4][0] for item in results if item[4]}
    if not resolved:
        raise PrivateEndpointError("localhost did not resolve to an address")
    for raw in resolved:
        try:
            candidate = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise PrivateEndpointError("localhost resolved to an invalid address") from exc
        if not candidate.is_loopback:
            raise PrivateEndpointError("localhost resolved outside the loopback interface")
