"""Canonical encoding and fingerprints for exact Action Gate review."""

from __future__ import annotations

import hashlib
import json

from bella_harness.action_gate.models import ActionSpec


ACTION_SCHEMA = "bella.action.v1"


def canonical_action_dict(spec: ActionSpec) -> dict:
    return {
        "schema": ACTION_SCHEMA,
        "connector": spec.connector,
        "kind": spec.kind.value,
        "target": spec.target,
        "payload": spec.payload,
    }


def canonical_action_bytes(spec: ActionSpec) -> bytes:
    """Return deterministic UTF-8 JSON bytes with no ambiguous NaN values."""
    return json.dumps(
        canonical_action_dict(spec),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def action_fingerprint(spec: ActionSpec) -> str:
    return hashlib.sha256(canonical_action_bytes(spec)).hexdigest()
