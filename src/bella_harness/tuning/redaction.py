"""Deterministic local redaction for Bella tuning exports.

This is a conservative safety boundary, not a claim to detect every possible
identifier. Redacted export is the default; exact export requires an explicit
CLI flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    text: str
    replacements: int


_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        "[EMAIL]",
    ),
    (
        re.compile(r"(?<!\d)(?:\+?1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}(?!\d)"),
        "[PHONE]",
    ),
    (
        re.compile(r"(?<!\d)\d{3}[ -]?\d{2}[ -]?\d{4}(?!\d)"),
        "[SSN]",
    ),
    (
        re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
        "[CARD_NUMBER]",
    ),
    (
        re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{12,}|sk-proj-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[A-Za-z0-9_-]{20,})\b"),
        "[API_KEY]",
    ),
    (
        re.compile(r"(?i)\b(?:bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
        "Bearer [TOKEN]",
    ),
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/@\s:]+):([^/@\s]+)@"),
        r"\1[CREDENTIALS]@",
    ),
)


def redact_text(value: str) -> RedactionResult:
    if not isinstance(value, str):
        raise TypeError("redaction input must be a string")
    redacted = value
    replacements = 0
    for pattern, replacement in _PATTERNS:
        redacted, count = pattern.subn(replacement, redacted)
        replacements += count
    return RedactionResult(text=redacted, replacements=replacements)
