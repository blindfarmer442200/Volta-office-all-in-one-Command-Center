"""Hardened public wrapper around the durable Bella tuning store."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from bella_harness.tuning.models import (
    FeedbackRating,
    TuningFeedback,
    TuningStoreError if False else TuningValidationError,
    validate_id,
)
from bella_harness.tuning.store import SQLiteTuningStore as _BaseSQLiteTuningStore
from bella_harness.tuning.store import TuningStoreError


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SQLiteTuningStore(_BaseSQLiteTuningStore):
    """Public tuning store with normalized validation and export audit support."""

    def add_feedback(
        self,
        *,
        interaction_id: str,
        rating: FeedbackRating | str,
        note: str = "",
        feedback_id: str | None = None,
        created_at: str | None = None,
    ) -> TuningFeedback:
        try:
            normalized = rating if isinstance(rating, FeedbackRating) else FeedbackRating(rating)
        except ValueError as exc:
            raise TuningValidationError(f"unsupported feedback rating: {rating!r}") from exc
        return super().add_feedback(
            interaction_id=interaction_id,
            rating=normalized,
            note=note,
            feedback_id=feedback_id,
            created_at=created_at,
        )

    def record_export(
        self,
        *,
        export_id: str,
        redacted: bool,
        dataset_sha256: str,
        counts: dict[str, int],
    ) -> None:
        validate_id("export id", export_id)
        if not isinstance(redacted, bool):
            raise TuningValidationError("redacted must be boolean")
        if not isinstance(dataset_sha256, str) or not _SHA256_RE.fullmatch(dataset_sha256):
            raise TuningValidationError("dataset_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(counts, dict) or not counts:
            raise TuningValidationError("export counts must be a non-empty mapping")
        normalized_counts: dict[str, int] = {}
        for name, count in counts.items():
            if not isinstance(name, str) or not name:
                raise TuningValidationError("export count names must be non-empty strings")
            if not isinstance(count, int) or count < 0:
                raise TuningValidationError("export counts must be non-negative integers")
            normalized_counts[name] = count
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                self._append_audit(
                    conn,
                    "dataset_exported",
                    export_id,
                    {
                        "redacted": redacted,
                        "dataset_sha256": dataset_sha256,
                        "counts": normalized_counts,
                        "automatic_upload_performed": False,
                        "training_started": False,
                        "model_activated": False,
                    },
                )
        except sqlite3.Error as exc:
            raise TuningStoreError(f"unable to audit tuning export: {exc}") from exc
