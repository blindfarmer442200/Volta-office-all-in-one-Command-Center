"""Typed records for the Mind Trace memory boundary.

The memory layer is intentionally data-only. A record can inform a model call,
but it can never grant authority to execute an external action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


MAX_MEMORY_CONTENT_CHARS = 8_000
MAX_MEMORY_SOURCE_CHARS = 1_000
MAX_TAGS = 32
MAX_TAG_CHARS = 80


class MemoryValidationError(ValueError):
    """Raised when a memory record is malformed or exceeds safety bounds."""


class MemoryStatus(str, Enum):
    TEMPORARY = "temporary"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class MemoryConfidence(str, Enum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    UNCLEAR = "unclear"
    DISPUTED = "disputed"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp and normalize naive values to UTC."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError("timestamp must be a non-empty ISO-8601 string")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MemoryValidationError(f"invalid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class MemoryRecord:
    """One human-governed memory item.

    ``content`` is untrusted reference data even when ``status`` is approved.
    Approval means the human accepted the fact for recall; it does not convert
    embedded text into executable instructions.
    """

    id: str
    content: str
    source: str
    status: MemoryStatus = MemoryStatus.TEMPORARY
    confidence: MemoryConfidence = MemoryConfidence.UNCLEAR
    tags: tuple[str, ...] = field(default_factory=tuple)
    private: bool = True
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    valid_until: str | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise MemoryValidationError("memory id must be a non-empty string")
        if len(self.id) > 200:
            raise MemoryValidationError("memory id is too long")
        if not isinstance(self.content, str) or not self.content.strip():
            raise MemoryValidationError("memory content must be a non-empty string")
        if len(self.content) > MAX_MEMORY_CONTENT_CHARS:
            raise MemoryValidationError("memory content exceeds the 8,000 character limit")
        if not isinstance(self.source, str) or not self.source.strip():
            raise MemoryValidationError("memory source must be a non-empty string")
        if len(self.source) > MAX_MEMORY_SOURCE_CHARS:
            raise MemoryValidationError("memory source is too long")

        try:
            status = self.status if isinstance(self.status, MemoryStatus) else MemoryStatus(self.status)
            confidence = (
                self.confidence
                if isinstance(self.confidence, MemoryConfidence)
                else MemoryConfidence(self.confidence)
            )
        except ValueError as exc:
            raise MemoryValidationError(str(exc)) from exc
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "confidence", confidence)

        if not isinstance(self.private, bool):
            raise MemoryValidationError("private must be a boolean")
        if not isinstance(self.tags, (list, tuple)):
            raise MemoryValidationError("tags must be a list or tuple")

        raw_tags = tuple(self.tags)
        if len(raw_tags) > MAX_TAGS:
            raise MemoryValidationError(f"memory may have at most {MAX_TAGS} tags")
        normalized_tags: list[str] = []
        for raw_tag in raw_tags:
            if not isinstance(raw_tag, str) or not raw_tag.strip():
                raise MemoryValidationError("tags must be non-empty strings")
            tag = raw_tag.strip()
            if len(tag) > MAX_TAG_CHARS:
                raise MemoryValidationError("tag is too long")
            normalized_tags.append(tag)
        object.__setattr__(self, "tags", tuple(normalized_tags))

        parse_timestamp(self.created_at)
        parse_timestamp(self.updated_at)
        parse_timestamp(self.valid_until)

        if self.superseded_by is not None:
            if not isinstance(self.superseded_by, str) or not self.superseded_by.strip():
                raise MemoryValidationError("superseded_by must be a non-empty id or null")
            if self.superseded_by == self.id:
                raise MemoryValidationError("a memory cannot supersede itself")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        if not isinstance(data, dict):
            raise MemoryValidationError("memory record must be a JSON object")
        allowed = {
            "id",
            "content",
            "source",
            "status",
            "confidence",
            "tags",
            "private",
            "created_at",
            "updated_at",
            "valid_until",
            "superseded_by",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise MemoryValidationError(f"unknown memory fields: {', '.join(unknown)}")
        raw_tags = data.get("tags", ())
        if not isinstance(raw_tags, (list, tuple)):
            raise MemoryValidationError("tags must be a JSON array")
        try:
            return cls(
                id=data["id"],
                content=data["content"],
                source=data["source"],
                status=data.get("status", MemoryStatus.TEMPORARY),
                confidence=data.get("confidence", MemoryConfidence.UNCLEAR),
                tags=tuple(raw_tags),
                private=data.get("private", True),
                created_at=data.get("created_at", _utc_now_iso()),
                updated_at=data.get("updated_at", _utc_now_iso()),
                valid_until=data.get("valid_until"),
                superseded_by=data.get("superseded_by"),
            )
        except KeyError as exc:
            raise MemoryValidationError(f"missing required memory field: {exc.args[0]}") from exc
