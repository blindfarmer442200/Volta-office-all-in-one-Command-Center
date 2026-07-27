"""Authenticated, local-first FastAPI application for Bella Harness."""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from typing import Mapping

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from bella_harness.config import load_config
from bella_harness.deterministic.engine import Action
from bella_harness.doctor import run_doctor
from bella_harness.harness import BellaHarness, HarnessResult
from bella_harness.operator import BellaMode
from bella_harness.service.models import (
    ChatRequest,
    ChatResponse,
    ChatTrace,
    ErrorResponse,
    LiveResponse,
    ReadyCheck,
    ReadyResponse,
    model_dump_compat,
)
from bella_harness.service.security import (
    AuthenticationError,
    BodyLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    ServiceAuthenticator,
    SlidingWindowRateLimiter,
)
from bella_harness.service.settings import (
    ServiceConfigurationError,
    ServiceSettings,
    resolve_service_token,
)


logger = logging.getLogger("bella_harness.service")
_ALLOWED_MODES = frozenset(mode.value for mode in BellaMode)


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else "unknown"


def _status_for_result(result: HarnessResult) -> int:
    if result.category in {"backend_unavailable", "memory_unavailable"}:
        return 503
    if result.category == "invalid_operator_mode":
        return 422
    if result.category in {"credential_leak", "private_key_leak", "system_prompt_leak"}:
        return 502
    return 200


def _chat_payload(result: HarnessResult, request_id: str, *, trace: bool) -> ChatResponse:
    trace_payload = None
    if trace:
        trace_payload = ChatTrace(
            memory_ids=list(result.memory_ids),
            memory_explanations=list(result.memory_explanations),
            excluded_unsafe_memory_ids=list(result.excluded_unsafe_memory_ids),
            operator_reasons=list(result.operator_reasons),
            operator_plan=list(result.operator_plan),
        )
    return ChatResponse(
        request_id=request_id,
        response=result.response,
        action=result.action.value,
        category=result.category,
        backend_used=result.backend_used,
        handled_deterministically=result.handled_deterministically,
        operator_profile_id=result.operator_profile_id,
        operator_mode=result.operator_mode,
        risk_level=result.risk_level,
        approval_required=result.approval_required,
        memory_count=len(result.memory_ids),
        external_action_performed=False,
        trace=trace_payload,
    )


def create_app(
    *,
    config: dict | None = None,
    config_path: str | None = None,
    token: str | None = None,
    environment: Mapping[str, str] | None = None,
    harness: BellaHarness | None = None,
) -> FastAPI:
    """Create a service that exposes health and ordinary chat only.

    No Action Gate, tuning-write, connector, file, calendar, payment, or device
    execution endpoint is registered.
    """
    selected_config = config if config is not None else load_config(config_path)
    settings = ServiceSettings.from_config(selected_config)
    if not settings.enabled:
        raise ServiceConfigurationError(
            "Bella HTTP service is disabled; set service.enabled=true explicitly"
        )
    service_token = token or resolve_service_token(
        settings.token_env,
        environment=os.environ if environment is None else environment,
    )
    # Explicit token arguments used by tests and embedding callers receive the
    # same strength validation as environment-sourced tokens.
    if token is not None:
        service_token = resolve_service_token(
            "BELLA_EXPLICIT_SERVICE_TOKEN",
            environment={"BELLA_EXPLICIT_SERVICE_TOKEN": token},
        )

    offline_report = run_doctor(selected_config, live=False)
    critical_failures = [
        check.name
        for check in offline_report.checks
        if check.critical and check.status == "fail"
    ]
    if critical_failures:
        raise ServiceConfigurationError(
            "service startup blocked by production doctor checks: "
            + ", ".join(sorted(critical_failures))
        )

    selected_harness = harness or BellaHarness(config=selected_config)
    authenticator = ServiceAuthenticator(service_token)
    limiter = SlidingWindowRateLimiter(
        requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    semaphore = asyncio.Semaphore(settings.max_concurrent_requests)
    executor = ThreadPoolExecutor(
        max_workers=settings.max_concurrent_requests,
        thread_name_prefix="bella-service",
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(
        title="Bella Harness Service",
        version=offline_report.package_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.config = selected_config
    app.state.settings = settings
    app.state.harness = selected_harness

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts))
    app.add_middleware(BodyLimitMiddleware, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    async def require_auth(
        request: Request,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> None:
        try:
            authenticator.authenticate(authorization)
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=401,
                detail="unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    async def require_chat_access(
        request: Request,
        _: None = Depends(require_auth),
    ) -> None:
        allowed, retry_after = await limiter.allow()
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="rate_limited",
                headers={"Retry-After": str(retry_after)},
            )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, _: RequestValidationError):
        payload = ErrorResponse(error="invalid_request", request_id=_request_id(request))
        return JSONResponse(status_code=422, content=model_dump_compat(payload))

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        retry_after = None
        if exc.headers and "Retry-After" in exc.headers:
            try:
                retry_after = int(exc.headers["Retry-After"])
            except ValueError:
                retry_after = None
        payload = ErrorResponse(
            error=str(exc.detail) if isinstance(exc.detail, str) else "request_failed",
            request_id=_request_id(request),
            retry_after_seconds=retry_after,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=model_dump_compat(payload),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logger.error(
            "unhandled_service_error request_id=%s type=%s",
            _request_id(request),
            type(exc).__name__,
        )
        payload = ErrorResponse(error="internal_error", request_id=_request_id(request))
        return JSONResponse(status_code=500, content=model_dump_compat(payload))

    @app.get("/health/live", response_model=LiveResponse)
    async def live() -> LiveResponse:
        return LiveResponse()

    @app.get("/health/ready", response_model=ReadyResponse)
    async def ready(_: None = Depends(require_auth)):
        report = await asyncio.to_thread(run_doctor, selected_config, live=True)
        response = ReadyResponse(
            ready=report.ready,
            package_version=report.package_version,
            checks=[
                ReadyCheck(name=check.name, status=check.status, critical=check.critical)
                for check in report.checks
            ],
        )
        return JSONResponse(
            status_code=200 if report.ready else 503,
            content=model_dump_compat(response),
        )

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(
        chat_request: ChatRequest,
        request: Request,
        _: None = Depends(require_chat_access),
    ):
        request_id = _request_id(request)
        if not chat_request.prompt.strip():
            raise HTTPException(status_code=422, detail="invalid_prompt")
        if len(chat_request.prompt) > settings.max_prompt_chars:
            raise HTTPException(status_code=413, detail="prompt_too_large")
        normalized_mode = chat_request.mode.strip().lower()
        if normalized_mode not in _ALLOWED_MODES:
            raise HTTPException(status_code=422, detail="invalid_mode")

        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=503, detail="service_busy") from exc

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            executor,
            partial(selected_harness.handle, chat_request.prompt, mode=normalized_mode),
        )
        release_on_exit = True
        try:
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(future),
                    timeout=settings.request_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                release_on_exit = False
                future.add_done_callback(lambda _: loop.call_soon_threadsafe(semaphore.release))
                raise HTTPException(status_code=504, detail="model_timeout") from exc
        finally:
            if release_on_exit:
                semaphore.release()

        payload = _chat_payload(result, request_id, trace=chat_request.trace)
        return JSONResponse(
            status_code=_status_for_result(result),
            content=model_dump_compat(payload),
        )

    return app
