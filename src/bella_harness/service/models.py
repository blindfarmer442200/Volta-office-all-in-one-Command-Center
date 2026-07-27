"""Strict public request and response models for Bella's HTTP service."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    mode: str = "default"
    trace: bool = False


class ChatTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_ids: list[str] = Field(default_factory=list)
    memory_explanations: list[str] = Field(default_factory=list)
    excluded_unsafe_memory_ids: list[str] = Field(default_factory=list)
    operator_reasons: list[str] = Field(default_factory=list)
    operator_plan: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema: str = "bella.service-chat.v1"
    request_id: str
    response: str
    action: str
    category: str | None = None
    backend_used: str | None = None
    handled_deterministically: bool
    operator_profile_id: str | None = None
    operator_mode: str | None = None
    risk_level: str | None = None
    approval_required: bool = False
    memory_count: int = 0
    external_action_performed: bool = False
    trace: ChatTrace | None = None


class LiveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema: str = "bella.service-live.v1"
    status: str = "alive"


class ReadyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    critical: bool


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema: str = "bella.service-ready.v1"
    ready: bool
    package_version: str
    checks: list[ReadyCheck]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str
    request_id: str | None = None
    retry_after_seconds: int | None = None


def model_dump_compat(model: BaseModel) -> dict[str, Any]:
    """Keep serialization explicit across supported Pydantic versions."""
    return model.model_dump(exclude_none=True)
