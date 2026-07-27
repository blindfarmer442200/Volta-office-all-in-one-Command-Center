"""Hardened public wrapper around the durable Bella tuning store."""

from __future__ import annotations

import re
import sqlite3

from bella_harness.tuning.models import (
    FeedbackRating,
    TuningCorrection,
    TuningFeedback,
    TuningInteraction,
    TuningValidationError,
    sha256_text,
    validate_id,
)
from bella_harness.tuning.store import SQLiteTuningStore as _BaseSQLiteTuningStore
from bella_harness.tuning.store import TuningStoreError


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SQLiteTuningStore(_BaseSQLiteTuningStore):
    """Public tuning store with normalized validation and export audit support."""

    def record_interaction(
        self,
        *,
        interaction_id: str,
        prompt: str,
        original_response: str,
        mode: str,
        risk_level: str,
        profile_id: str,
        source_model: str,
        created_at: str | None = None,
    ) -> TuningInteraction:
        """Record once; exact retries return the original immutable row."""
        validate_id("interaction id", interaction_id)
        try:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT * FROM tuning_interactions WHERE id = ?", (interaction_id,)
                ).fetchone()
                if existing is not None:
                    stored = self._row_to_interaction(existing)
                    matches = (
                        stored.prompt_sha256 == sha256_text(prompt)
                        and stored.original_response_sha256 == sha256_text(original_response)
                        and stored.mode == mode
                        and stored.risk_level == risk_level
                        and stored.profile_id == profile_id
                        and stored.source_model == source_model
                    )
                    if not matches:
                        raise TuningStoreError(
                            "interaction id already exists with different immutable content"
                        )
                    return stored
        except sqlite3.Error as exc:
            raise TuningStoreError(f"unable to inspect tuning interaction: {exc}") from exc
        return super().record_interaction(
            interaction_id=interaction_id,
            prompt=prompt,
            original_response=original_response,
            mode=mode,
            risk_level=risk_level,
            profile_id=profile_id,
            source_model=source_model,
            created_at=created_at,
        )

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

    def add_correction(
        self,
        *,
        interaction_id: str,
        corrected_response: str,
        rationale: str = "",
        correction_id: str | None = None,
        created_at: str | None = None,
    ) -> TuningCorrection:
        """Require the latest human feedback to be negative before correction."""
        validate_id("interaction id", interaction_id)
        try:
            with self._connect() as conn:
                latest = conn.execute(
                    """
                    SELECT rating FROM tuning_feedback
                    WHERE interaction_id = ? ORDER BY sequence DESC LIMIT 1
                    """,
                    (interaction_id,),
                ).fetchone()
                if latest is None:
                    raise TuningStoreError(
                        "a human feedback rating is required before adding a correction"
                    )
                if FeedbackRating(latest["rating"]).is_positive:
                    raise TuningStoreError("a positively rated response cannot receive a correction")
        except sqlite3.Error as exc:
            raise TuningStoreError(f"unable to inspect tuning feedback: {exc}") from exc
        return super().add_correction(
            interaction_id=interaction_id,
            corrected_response=corrected_response,
            rationale=rationale,
            correction_id=correction_id,
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
