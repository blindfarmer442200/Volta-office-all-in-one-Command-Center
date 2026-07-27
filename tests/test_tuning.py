"""Durable Bella correction, redaction, export, and audit regression tests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from bella_harness.tuning import (
    BellaTuningExporter,
    ExportDisposition,
    FeedbackRating,
    SQLiteTuningStore,
    TuningFeedback,
    TuningStoreError,
    TuningValidationError,
    redact_text,
)


def _record(
    store: SQLiteTuningStore,
    interaction_id: str,
    *,
    prompt: str = "Help me answer this.",
    response: str = "Original answer.",
    rating: FeedbackRating = FeedbackRating.MISSED_POINT,
    corrected: str | None = "Corrected answer.",
):
    interaction = store.record_interaction(
        interaction_id=interaction_id,
        prompt=prompt,
        original_response=response,
        mode="business",
        risk_level="low",
        profile_id="bella-core-v1",
        source_model="qwen3.5",
    )
    feedback = store.add_feedback(
        interaction_id=interaction.id,
        rating=rating,
        note="Human review note.",
    )
    correction = None
    if corrected is not None:
        correction = store.add_correction(
            interaction_id=interaction.id,
            corrected_response=corrected,
            rationale="Use the exact human replacement.",
        )
    return interaction, feedback, correction


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_store_is_idempotent_and_preserves_versioned_corrections(tmp_path):
    database = tmp_path / "bella-tuning.sqlite3"
    store = SQLiteTuningStore(database)
    interaction, _, first = _record(store, "interaction-1", corrected="First correction.")

    retried = store.record_interaction(
        interaction_id=interaction.id,
        prompt=interaction.prompt,
        original_response=interaction.original_response,
        mode=interaction.mode,
        risk_level=interaction.risk_level,
        profile_id=interaction.profile_id,
        source_model=interaction.source_model,
    )
    assert retried.created_at == interaction.created_at

    second = store.add_correction(
        interaction_id=interaction.id,
        corrected_response="Second correction.",
        rationale="Improved human replacement.",
    )
    assert first is not None
    assert first.version == 1
    assert second.version == 2

    examples = store.list_reviewed_examples()
    assert len(examples) == 1
    assert examples[0].correction is not None
    assert examples[0].correction.id == second.id
    assert examples[0].disposition is ExportDisposition.PREFERENCE_CANDIDATE

    with sqlite3.connect(database) as conn:
        rows = conn.execute(
            "SELECT version, active FROM tuning_corrections ORDER BY version"
        ).fetchall()
    assert rows == [(1, 0), (2, 1)]
    assert store.verify_integrity()


def test_interaction_id_cannot_be_reused_for_different_content(tmp_path):
    store = SQLiteTuningStore(tmp_path / "tuning.sqlite3")
    _record(store, "same-id")
    with pytest.raises(TuningStoreError, match="different immutable content"):
        store.record_interaction(
            interaction_id="same-id",
            prompt="Different prompt.",
            original_response="Original answer.",
            mode="business",
            risk_level="low",
            profile_id="bella-core-v1",
            source_model="qwen3.5",
        )


def test_correction_requires_latest_negative_human_feedback(tmp_path):
    store = SQLiteTuningStore(tmp_path / "tuning.sqlite3")
    interaction = store.record_interaction(
        interaction_id="needs-rating",
        prompt="Prompt",
        original_response="Response",
        mode="default",
        risk_level="low",
        profile_id="bella-core-v1",
        source_model="qwen3.5",
    )
    with pytest.raises(TuningStoreError, match="feedback rating is required"):
        store.add_correction(
            interaction_id=interaction.id,
            corrected_response="Replacement",
        )

    store.add_feedback(interaction_id=interaction.id, rating=FeedbackRating.GOOD)
    with pytest.raises(TuningStoreError, match="positively rated"):
        store.add_correction(
            interaction_id=interaction.id,
            corrected_response="Replacement",
        )


def test_invalid_rating_uses_tuning_validation_error(tmp_path):
    store = SQLiteTuningStore(tmp_path / "tuning.sqlite3")
    store.record_interaction(
        interaction_id="bad-rating",
        prompt="Prompt",
        original_response="Response",
        mode="default",
        risk_level="low",
        profile_id="bella-core-v1",
        source_model="qwen3.5",
    )
    with pytest.raises(TuningValidationError, match="unsupported feedback rating"):
        store.add_feedback(interaction_id="bad-rating", rating="excellent")


def test_nonhuman_feedback_is_rejected():
    with pytest.raises(TuningValidationError, match="human reviewed"):
        TuningFeedback(
            id="feedback",
            interaction_id="interaction",
            rating=FeedbackRating.GOOD,
            note="",
            created_at="2026-07-27T12:00:00+00:00",
            reviewed_by_human=False,
        )


def test_audit_or_content_tampering_is_detected(tmp_path):
    database = tmp_path / "tuning.sqlite3"
    store = SQLiteTuningStore(database)
    _record(store, "tamper-test")
    assert store.verify_integrity()

    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE tuning_interactions SET original_response = 'tampered' WHERE id = 'tamper-test'"
        )
    assert not store.verify_integrity()


def test_redaction_covers_common_sensitive_patterns():
    source = (
        "Email me at person@example.com or call (601) 555-1212. "
        "SSN 123-45-6789, card 4111 1111 1111 1111, key sk-abcdefghijklmnop, "
        "and https://user:password@example.com/private."
    )
    result = redact_text(source)
    assert result.replacements >= 6
    assert "person@example.com" not in result.text
    assert "601" not in result.text
    assert "123-45-6789" not in result.text
    assert "4111 1111" not in result.text
    assert "sk-abcdefghijklmnop" not in result.text
    assert "user:password" not in result.text


def test_redacted_export_splits_sft_preference_evaluation_and_regression(tmp_path):
    store = SQLiteTuningStore(tmp_path / "tuning.sqlite3")
    _record(
        store,
        "good-1",
        prompt="Email person@example.com a summary.",
        response="Here is a safe reviewed summary.",
        rating=FeedbackRating.GOOD,
        corrected=None,
    )
    _record(
        store,
        "corrected-1",
        prompt="Call (601) 555-1212 about the invoice.",
        response="I already called using sk-abcdefghijklmnop.",
        rating=FeedbackRating.UNSAFE_OVERREACH,
        corrected="I cannot place the call. I can draft a call script for review.",
    )
    _record(
        store,
        "evaluation-1",
        prompt="Help with this request.",
        response="An answer that needs correction later.",
        rating=FeedbackRating.TOO_VAGUE,
        corrected=None,
    )

    output = tmp_path / "export"
    manifest = BellaTuningExporter(store).export(output)

    sft = _read_jsonl(output / "sft.jsonl")
    preference = _read_jsonl(output / "preference.jsonl")
    evaluation = _read_jsonl(output / "evaluation-only.jsonl")
    regression = _read_jsonl(output / "regression.jsonl")
    assert len(sft) == 2
    assert len(preference) == 1
    assert len(evaluation) == 1
    assert len(regression) == 1
    assert manifest["redacted"] is True
    assert manifest["redaction_replacements"] >= 3

    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in output.glob("*.jsonl")
    )
    assert "person@example.com" not in combined
    assert "601" not in combined
    assert "sk-abcdefghijklmnop" not in combined
    assert '"hidden_memory_included":false' in combined
    assert '"action_capabilities_included":false' in combined

    for name, details in manifest["files"].items():
        data = (output / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == details["sha256"]
        assert len(data) == details["bytes"]
    assert store.verify_integrity()


def test_exact_export_requires_explicit_argument_and_retains_reviewed_text(tmp_path):
    store = SQLiteTuningStore(tmp_path / "tuning.sqlite3")
    _record(
        store,
        "exact-1",
        prompt="Email person@example.com.",
        response="Draft for person@example.com.",
        rating=FeedbackRating.GOOD,
        corrected=None,
    )
    output = tmp_path / "exact"
    manifest = BellaTuningExporter(store).export(output, redacted=False)
    assert manifest["redacted"] is False
    assert "person@example.com" in (output / "sft.jsonl").read_text(encoding="utf-8")
    assert manifest["automatic_upload_performed"] is False
    assert manifest["training_started"] is False
    assert manifest["model_activated"] is False
