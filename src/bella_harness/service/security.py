"""Authentication, limiting, headers, and safe request logging for Bella service."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from collections import deque
from typing import Deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
logger = logging.getLogger("bella_harness.service")


class AuthenticationError(ValueError):
    """Raised when a bearer token is absent or invalid."""


class ServiceAuthenticator:
    """Store only a token digest and compare presented tokens in constant time."""

    def __init__(self, token: str):
        self._expected_sha256 = hashlib.sha256(token.encode("utf-8")).digest()

    def authenticate(self, authorization: str | None) -> None:
        if not isinstance(authorization, str):
            raise AuthenticationError("missing bearer token")
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            raise AuthenticationError("invalid bearer token")
        candidate = authorization[len(prefix):]
        if not candidate or len(candidate) > 512:
            raise AuthenticationError("invalid bearer token")
        candidate_sha256 = hashlib.sha256(candidate.encode("utf-8")).digest()
        if not hmac.compare_digest(self._expected_sha256, candidate_sha256):
            raise AuthenticationError("invalid bearer token")


class SlidingWindowRateLimiter:
    """Per-process authenticated request limiter with bounded state."""

    def __init__(self, *, requests: int, window_seconds: int):
        self.requests = requests
        self.window_seconds = float(window_seconds)
        self._events: Deque[float] = deque(maxlen=requests)
        self._lock = asyncio.Lock()

    async def allow(self) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            while self._events and self._events[0] <= cutoff:
                self._events.popleft()
            if len(self._events) >= self.requests:
                retry_after = max(1, int(self.window_seconds - (now - self._events[0])))
                return False, retry_after
            self._events.append(now)
            return True, 0


class RequestBodyTooLarge(RuntimeError):
    pass


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _request_id(scope: Scope) -> str:
    state = scope.setdefault("state", {})
    existing = state.get("request_id")
    if isinstance(existing, str):
        return existing
    supplied = _header(scope, b"x-request-id")
    value = supplied if supplied and _REQUEST_ID_RE.fullmatch(supplied) else uuid.uuid4().hex
    state["request_id"] = value
    return value


async def _json_response(
    send: Send,
    *,
    status: int,
    payload: dict,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    response_headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    if headers:
        response_headers.extend(headers)
    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})


class RequestContextMiddleware:
    """Attach a safe request ID and log metadata without request or response bodies."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _request_id(scope)
        started = time.monotonic()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            elapsed_ms = round((time.monotonic() - started) * 1000, 2)
            logger.info(
                "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%s",
                request_id,
                scope.get("method", ""),
                scope.get("path", ""),
                status_code,
                elapsed_ms,
            )


class BodyLimitMiddleware:
    """Reject declared or streamed HTTP bodies above the configured byte limit."""

    def __init__(self, app: ASGIApp, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _request_id(scope)
        declared = _header(scope, b"content-length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError:
                await _json_response(
                    send,
                    status=400,
                    payload={"error": "invalid_content_length", "request_id": request_id},
                )
                return
            if declared_size < 0 or declared_size > self.max_body_bytes:
                await _json_response(
                    send,
                    status=413,
                    payload={"error": "request_too_large", "request_id": request_id},
                )
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await _json_response(
                send,
                status=413,
                payload={"error": "request_too_large", "request_id": request_id},
            )


class SecurityHeadersMiddleware:
    """Add restrictive headers to every service response."""

    _HEADERS = (
        (b"cache-control", b"no-store"),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    )

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                headers.extend((key, value) for key, value in self._HEADERS if key not in existing)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
