"""Deterministic request-risk classification for Bella."""

from __future__ import annotations

import re

from bella_harness.operator.models import BellaMode, OperatorDecision, RiskLevel, parse_mode


_CRITICAL_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "money movement or purchase",
        re.compile(
            r"\b(transfer|wire|send|move|pay|purchase|buy|refund|charge)\b"
            r".{0,40}\b(money|funds?|payment|bank|card|crypto|invoice|dollars?|\$)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "credential or secret change",
        re.compile(
            r"\b(change|reset|reveal|share|send|use|enter|rotate|disable)\b"
            r".{0,40}\b(password|passcode|api[ _-]?key|token|credential|secret|2fa|mfa)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "destructive data or account action",
        re.compile(
            r"\b(delete|erase|wipe|destroy|purge|remove)\b"
            r".{0,40}\b(account|database|data|files?|folders?|records?|memory|backups?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "medication change",
        re.compile(
            r"\b(stop|start|change|increase|decrease|double|skip|replace)\b"
            r".{0,40}\b(medication|medicine|dose|dosage|pill|prescription)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "safety-sensitive physical control",
        re.compile(
            r"\b(unlock|disable|open|start|turn\s+on)\b"
            r".{0,40}\b(door|alarm|oven|stove|vehicle|car|garage|weapon)\b",
            re.IGNORECASE,
        ),
    ),
)

_HIGH_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "external communication",
        re.compile(
            r"\b(send|email|message|text|call|forward|post|publish|submit)\b"
            r".{0,50}\b(customer|client|person|them|him|her|team|boss|employee|public|social|form|application|email|message|text)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "calendar or reservation change",
        re.compile(
            r"\b(schedule|book|cancel|reschedule|invite|accept|decline)\b"
            r".{0,40}\b(meeting|appointment|reservation|event|calendar|invite)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "external file, account, or record change",
        re.compile(
            r"\b(create|edit|update|move|rename|upload|replace|archive)\b"
            r".{0,40}\b(file|folder|account|record|database|calendar|event|customer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "legal or business commitment",
        re.compile(
            r"\b(sign|accept|agree|commit|approve|reject)\b"
            r".{0,40}\b(contract|agreement|terms|offer|deal|settlement|proposal)\b",
            re.IGNORECASE,
        ),
    ),
)

_MEDIUM_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "health, legal, or financial guidance",
        re.compile(
            r"\b(medical|health|medicine|medication|legal|law|lawsuit|court|tax|investment|financial|insurance)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "draft or preview of a consequential action",
        re.compile(
            r"\b(draft|prepare|preview|propose|review)\b"
            r".{0,50}\b(email|message|contract|agreement|payment|calendar|filing|application|record)\b",
            re.IGNORECASE,
        ),
    ),
)


def classify_request(request_text: str, mode: str | BellaMode = BellaMode.DEFAULT) -> OperatorDecision:
    """Classify consequence risk without granting or denying permission."""
    selected_mode = parse_mode(mode)
    text = request_text if isinstance(request_text, str) else str(request_text)

    for reason, pattern in _CRITICAL_RULES:
        if pattern.search(text):
            return OperatorDecision(
                mode=selected_mode,
                risk_level=RiskLevel.CRITICAL,
                approval_required=True,
                reasons=(reason,),
                plan=(
                    "Prepare a non-executing preview with the exact target and payload.",
                    "Show the consequence, uncertainty, and rollback limits.",
                    "Require explicit current approval before any connector call.",
                    "Report execution only after a verified tool result.",
                ),
            )

    for reason, pattern in _HIGH_RULES:
        if pattern.search(text):
            return OperatorDecision(
                mode=selected_mode,
                risk_level=RiskLevel.HIGH,
                approval_required=True,
                reasons=(reason,),
                plan=(
                    "Prepare the exact draft or change preview without executing it.",
                    "Show the target, payload, and expected consequence.",
                    "Require explicit current approval before any connector call.",
                    "Report execution only after a verified tool result.",
                ),
            )

    for reason, pattern in _MEDIUM_RULES:
        if pattern.search(text):
            return OperatorDecision(
                mode=selected_mode,
                risk_level=RiskLevel.MEDIUM,
                approval_required=False,
                reasons=(reason,),
                plan=(
                    "Explain the recommendation, uncertainty, and what should be reviewed by the human.",
                ),
            )

    return OperatorDecision(
        mode=selected_mode,
        risk_level=RiskLevel.LOW,
        approval_required=False,
        reasons=("no consequential action pattern detected",),
    )
