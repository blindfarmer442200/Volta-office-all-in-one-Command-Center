"""Deterministic approved-memory filtering and ranking."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from bella_harness.memory.models import MemoryConfidence, MemoryRecord, MemoryStatus, parse_timestamp
from bella_harness.memory.store import MemoryStore


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}")
_STOP_WORDS = frozenset(
    {
        "a", "about", "an", "and", "are", "as", "at", "be", "been", "but", "by",
        "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
        "how", "i", "if", "in", "is", "it", "me", "my", "of", "on", "or", "our",
        "should", "that", "the", "their", "them", "there", "this", "to", "was", "we",
        "were", "what", "when", "where", "which", "who", "why", "will", "with", "would",
        "you", "your", "decision", "information", "memory", "meeting", "note", "project",
        "remember",
    }
)
_CONFIDENCE_BONUS = {
    MemoryConfidence.CONFIRMED: 4,
    MemoryConfidence.LIKELY: 2,
    MemoryConfidence.UNCLEAR: 0,
    MemoryConfidence.DISPUTED: -3,
}


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(_normalize(text))
        if token not in _STOP_WORDS and len(token) >= 2
    }


@dataclass(frozen=True)
class RecallHit:
    record: MemoryRecord
    score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RecallResult:
    hits: tuple[RecallHit, ...]
    excluded_unsafe_ids: tuple[str, ...] = ()

    @property
    def memory_ids(self) -> tuple[str, ...]:
        return tuple(hit.record.id for hit in self.hits)


class MemoryRecallEngine:
    """Filter first, then rank. No LLM is used in recall."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        max_results: int = 5,
        min_score: int = 10,
        is_safe_for_context: Callable[[str], bool] | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        if not 1 <= int(max_results) <= 20:
            raise ValueError("max_results must be between 1 and 20")
        if not 1 <= int(min_score) <= 100:
            raise ValueError("min_score must be between 1 and 100")
        self.store = store
        self.max_results = int(max_results)
        self.min_score = int(min_score)
        self.is_safe_for_context = is_safe_for_context or (lambda _text: True)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def recall(self, query: str, *, mode: str = "default") -> RecallResult:
        query_tokens = _tokens(query)
        if not query_tokens:
            return RecallResult(())

        now = self._now().astimezone(timezone.utc)
        hits: list[RecallHit] = []
        unsafe_ids: list[str] = []
        for record in self.store.list_records():
            if record.status is not MemoryStatus.APPROVED:
                continue
            if record.superseded_by:
                continue
            valid_until = parse_timestamp(record.valid_until)
            if valid_until is not None and valid_until <= now:
                continue
            if mode.lower() == "customer" and record.private:
                continue
            if not self.is_safe_for_context(record.content):
                unsafe_ids.append(record.id)
                continue

            content_tokens = _tokens(record.content)
            tag_tokens = _tokens(" ".join(record.tags))
            content_overlap = sorted(query_tokens & content_tokens)
            tag_overlap = sorted(query_tokens & tag_tokens)
            if not content_overlap and not tag_overlap:
                continue

            score = len(content_overlap) * 10 + len(tag_overlap) * 7
            score += _CONFIDENCE_BONUS[record.confidence]
            reasons: list[str] = []
            if content_overlap:
                reasons.append("content matched: " + ", ".join(content_overlap[:8]))
            if tag_overlap:
                reasons.append("tags matched: " + ", ".join(tag_overlap[:8]))
            reasons.append(f"confidence: {record.confidence.value}")

            if score >= self.min_score:
                hits.append(RecallHit(record=record, score=score, reasons=tuple(reasons)))

        hits.sort(key=lambda hit: (-hit.score, hit.record.id))
        return RecallResult(
            hits=tuple(hits[: self.max_results]),
            excluded_unsafe_ids=tuple(sorted(unsafe_ids)),
        )
