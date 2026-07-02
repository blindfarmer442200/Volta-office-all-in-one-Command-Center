"""The deterministic engine: resolves or blocks requests without an LLM call.

Pipeline for every incoming request:

1. Decode any obviously-encoded payload (base64 / hex / rot13) and scan the
   decoded text too, so an attacker can't dodge the block rules just by
   wrapping an attack in an encoding layer.
2. Match against BLOCK_RULES (prompt injection, jailbreak, role escalation,
   data exfiltration, multilingual injection). Any match => BLOCK.
3. Match against known deterministic-answerable shapes (greeting, simple
   arithmetic). Any match => ALLOW_DETERMINISTIC with a computed answer.
4. Otherwise => DEFER_TO_LLM, handed off to a backend via BackendAbstraction.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

from bella_harness.deterministic.rules import BLOCK_RULES, GREETING, SIMPLE_ARITHMETIC


class Action(str, Enum):
    ALLOW_DETERMINISTIC = "allow_deterministic"
    BLOCK = "block"
    DEFER_TO_LLM = "defer_to_llm"


@dataclass
class Decision:
    action: Action
    category: str | None = None
    reason: str | None = None
    response: str | None = None
    decoded_layers: list[str] = field(default_factory=list)


ZERO_WIDTH_CHARS = ("​", "‌", "‍", "﻿", "⁠")
_LEET_MAP = str.maketrans({"4": "a", "3": "e", "1": "i", "0": "o", "5": "s", "7": "t", "@": "a", "$": "s"})
_LETTER_SPACING_RE = re.compile(r"\b(?:[A-Za-z][ ._-]){3,}[A-Za-z]\b")
_WORD_FRAGMENT_HYPHEN_RE = re.compile(r"(?<=[A-Za-z])[-_](?=[A-Za-z])")
_FORMATTING_CHARS_RE = re.compile(r"[*_`~]")
# Cyrillic letters that are visually indistinguishable from Latin lookalikes,
# commonly used for homoglyph obfuscation (NFKC does not fold across scripts).
_CONFUSABLES_MAP = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ѕ": "s",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "У": "Y", "Х": "X", "І": "I",
})


def _normalize(text: str) -> str:
    # NFKC folds full-width/confusable unicode forms into their ASCII
    # equivalents, which handles most homoglyph obfuscation for free.
    text = unicodedata.normalize("NFKC", text)
    for ch in ZERO_WIDTH_CHARS:
        text = text.replace(ch, "")
    return text


def _normalize_leetspeak(text: str) -> str:
    return text.translate(_LEET_MAP)


def _collapse_letter_spacing(text: str) -> str:
    """Join up letter-by-letter spelling used to smuggle a word past keyword rules.

    e.g. "i g n o r e" or "i.g.n.o.r.e" both collapse to "ignore".
    """
    return _LETTER_SPACING_RE.sub(lambda m: re.sub(r"[ ._-]", "", m.group(0)), text)


def _collapse_word_fragments(text: str) -> str:
    """Join hyphen/underscore-split word fragments, e.g. "ig-nore" -> "ignore"."""
    return _WORD_FRAGMENT_HYPHEN_RE.sub("", text)


def _strip_formatting_chars(text: str) -> str:
    """Strip markdown emphasis characters used to smuggle a keyword, e.g. "**ig**nore"."""
    return _FORMATTING_CHARS_RE.sub("", text)


def _normalize_confusables(text: str) -> str:
    """Fold visually-confusable Cyrillic letters to their Latin lookalikes."""
    return text.translate(_CONFUSABLES_MAP)


_BASE64_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
_HEX_CANDIDATE_RE = re.compile(r"(?:0x)?(?:[0-9a-fA-F]{2}){8,}")


def _decode_base64_candidates(text: str) -> list[str]:
    """Find and decode base64-looking substrings anywhere in the text.

    An attacker doesn't send a message that's *purely* base64 -- they wrap it
    in plain-text framing ("decode this and follow it: ..."), so we scan for
    encoded substrings rather than requiring the whole message to be encoded.
    """
    results = []
    for match in _BASE64_CANDIDATE_RE.finditer(text):
        candidate = match.group(0)
        if len(candidate) % 4 != 0:
            continue
        try:
            decoded = base64.b64decode(candidate, validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        if decoded.isprintable():
            results.append(decoded)
    return results


def _decode_hex_candidates(text: str) -> list[str]:
    """Find and decode hex-looking substrings anywhere in the text."""
    results = []
    for match in _HEX_CANDIDATE_RE.finditer(text):
        candidate = match.group(0)[2:] if match.group(0).startswith("0x") else match.group(0)
        if len(candidate) % 2 != 0:
            continue
        try:
            decoded = bytes.fromhex(candidate).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if decoded.isprintable():
            results.append(decoded)
    return results


def _decode_rot13(text: str) -> str | None:
    """Apply ROT13 to the whole text.

    ROT13 is a per-character substitution, so an embedded ROT13-encoded
    payload decodes correctly regardless of surrounding plain-text framing
    (the framing just turns into unrelated nonsense, which is harmless).
    """
    if len(text.strip()) < 8:
        return None
    return codecs.decode(text, "rot_13")


def _try_decode_layers(text: str) -> list[str]:
    """Best-effort decode of base64/hex/rot13 payloads hidden in the text."""
    layers = [*_decode_base64_candidates(text), *_decode_hex_candidates(text)]
    rot13 = _decode_rot13(text)
    if rot13:
        layers.append(rot13)
    return layers


class DeterministicEngine:
    """Rule-driven request classifier requiring zero LLM calls."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def evaluate(self, request_text: str) -> Decision:
        normalized = _normalize(request_text)
        decoded_layers = _try_decode_layers(normalized)

        confusables_normalized = _normalize_confusables(normalized)
        texts_to_scan = [
            normalized,
            confusables_normalized,
            _normalize_leetspeak(normalized),
            _collapse_letter_spacing(normalized),
            _collapse_letter_spacing(confusables_normalized),
            _collapse_letter_spacing(_normalize_leetspeak(normalized)),
            _collapse_word_fragments(normalized),
            _strip_formatting_chars(normalized),
            *decoded_layers,
        ]

        for text in texts_to_scan:
            for rule in BLOCK_RULES:
                if rule.pattern.search(text):
                    return Decision(
                        action=Action.BLOCK,
                        category=rule.category,
                        reason=rule.description,
                        decoded_layers=decoded_layers,
                    )

        if GREETING.match(normalized.strip()):
            return Decision(
                action=Action.ALLOW_DETERMINISTIC,
                category="greeting",
                response="Hello! How can I help you today?",
                decoded_layers=decoded_layers,
            )

        arithmetic_match = SIMPLE_ARITHMETIC.match(normalized.strip())
        if arithmetic_match:
            result = self._eval_arithmetic(normalized.strip().rstrip("="))
            if result is not None:
                return Decision(
                    action=Action.ALLOW_DETERMINISTIC,
                    category="arithmetic",
                    response=str(result),
                    decoded_layers=decoded_layers,
                )

        return Decision(action=Action.DEFER_TO_LLM, decoded_layers=decoded_layers)

    @staticmethod
    def _eval_arithmetic(expr: str) -> float | int | None:
        match = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*([-+*/])\s*(-?\d+(?:\.\d+)?)\s*$", expr)
        if not match:
            return None
        left, op, right = match.groups()
        left_val = float(left)
        right_val = float(right)
        if op == "+":
            result = left_val + right_val
        elif op == "-":
            result = left_val - right_val
        elif op == "*":
            result = left_val * right_val
        elif op == "/":
            if right_val == 0:
                return None
            result = left_val / right_val
        else:
            return None
        return int(result) if result == int(result) else result
