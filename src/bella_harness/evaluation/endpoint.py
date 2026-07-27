"""Private-endpoint validation for live Ollama evaluation."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from bella_harness.evaluation.models import EvaluationError


def validate_private_ollama_endpoint(value: str) -> str:
    """Allow only localhost or literal private/loopback IP Ollama endpoints.

    DNS hostnames other than localhost are rejected to avoid DNS rebinding and
    accidental evaluation against public services. Credentials, query strings,
    and fragments are also rejected.
    """
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError("Ollama endpoint must be a non-empty URL")
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"}:
        raise EvaluationError("Ollama endpoint must use http or https")
    if parsed.username or parsed.password:
        raise EvaluationError("Ollama endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise EvaluationError("Ollama endpoint must not contain query or fragment data")
    if parsed.path not in {"", "/"}:
        raise EvaluationError("Ollama endpoint must not contain an API path")
    hostname = parsed.hostname
    if not hostname:
        raise EvaluationError("Ollama endpoint is missing a host")

    allowed = hostname.casefold() == "localhost"
    if not allowed:
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise EvaluationError(
                "Ollama endpoint must use localhost or a literal private IP address"
            ) from exc
        allowed = (address.is_private or address.is_loopback) and not (
            address.is_multicast or address.is_unspecified
        )
    if not allowed:
        raise EvaluationError("public Ollama endpoints are not allowed for Bella evaluation")

    port = parsed.port
    host_text = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    return f"{parsed.scheme}://{host_text}{f':{port}' if port is not None else ''}"
