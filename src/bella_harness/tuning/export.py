"""Privacy-first, atomic tuning-data export for Bella."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Iterable

from bella_harness.tuning.models import ExportDisposition, ReviewedTuningExample, utc_now_iso
from bella_harness.tuning.redaction import redact_text
from bella_harness.tuning.store import SQLiteTuningStore, TuningStoreError


EXPORT_SCHEMA = "bella.tuning-export.v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _protect_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise TuningStoreError("refusing to export through a symbolic-link directory")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary = Path(temporary_name)
        _protect_file(temporary)
        os.replace(temporary, path)
        _protect_file(path)
    finally:
        if temporary_name:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink(missing_ok=True)


def _jsonl(records: Iterable[dict[str, Any]]) -> bytes:
    return (
        "".join(_canonical_json(record) + "\n" for record in records)
    ).encode("utf-8")


def _maybe_redact(value: str, *, redacted: bool) -> tuple[str, int]:
    if not redacted:
        return value, 0
    result = redact_text(value)
    return result.text, result.replacements


def _base_metadata(example: ReviewedTuningExample) -> dict[str, Any]:
    return {
        "interaction_id": example.interaction.id,
        "profile_id": example.interaction.profile_id,
        "source_model": example.interaction.source_model,
        "mode": example.interaction.mode,
        "risk_level": example.interaction.risk_level,
        "rating": example.feedback.rating.value,
        "disposition": example.disposition.value,
        "human_reviewed": True,
        "hidden_memory_included": False,
        "connector_credentials_included": False,
        "action_capabilities_included": False,
    }


class BellaTuningExporter:
    """Export verified local review data without training or uploading anything."""

    def __init__(self, store: SQLiteTuningStore):
        self.store = store

    def export(self, output_dir: str | Path, *, redacted: bool = True) -> dict[str, Any]:
        if not self.store.verify_integrity():
            raise TuningStoreError("refusing to export an unverified tuning store")

        destination = Path(output_dir).expanduser()
        destination.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            raise TuningStoreError("refusing to export into a symbolic-link directory")

        examples = self.store.list_reviewed_examples()
        sft_records: list[dict[str, Any]] = []
        preference_records: list[dict[str, Any]] = []
        evaluation_records: list[dict[str, Any]] = []
        regression_records: list[dict[str, Any]] = []
        replacements = 0

        for example in examples:
            prompt, count = _maybe_redact(example.interaction.prompt, redacted=redacted)
            replacements += count
            original, count = _maybe_redact(
                example.interaction.original_response,
                redacted=redacted,
            )
            replacements += count
            note, count = _maybe_redact(example.feedback.note, redacted=redacted)
            replacements += count
            metadata = _base_metadata(example)

            if example.disposition is ExportDisposition.SFT_CANDIDATE:
                sft_records.append(
                    {
                        "schema": "bella.sft.v1",
                        "messages": [
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": original},
                        ],
                        "metadata": metadata,
                    }
                )
                continue

            if example.disposition is ExportDisposition.PREFERENCE_CANDIDATE:
                assert example.correction is not None
                corrected, count = _maybe_redact(
                    example.correction.corrected_response,
                    redacted=redacted,
                )
                replacements += count
                rationale, count = _maybe_redact(
                    example.correction.rationale,
                    redacted=redacted,
                )
                replacements += count
                correction_metadata = {
                    **metadata,
                    "correction_id": example.correction.id,
                    "correction_version": example.correction.version,
                    "rationale": rationale,
                }
                sft_records.append(
                    {
                        "schema": "bella.sft.v1",
                        "messages": [
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": corrected},
                        ],
                        "metadata": correction_metadata,
                    }
                )
                preference_records.append(
                    {
                        "schema": "bella.preference.v1",
                        "prompt": prompt,
                        "chosen": corrected,
                        "rejected": original,
                        "metadata": correction_metadata,
                    }
                )
                regression_records.append(
                    {
                        "schema": "bella.regression-case.v1",
                        "id": f"human-{example.interaction.id}-v{example.correction.version}",
                        "prompt": prompt,
                        "mode": example.interaction.mode,
                        "risk_level": example.interaction.risk_level,
                        "chosen_reference": corrected,
                        "rejected_reference": original,
                        "rating": example.feedback.rating.value,
                        "human_review_required": True,
                        "automatic_exact_match_required": False,
                    }
                )
                continue

            evaluation_records.append(
                {
                    "schema": "bella.evaluation-only.v1",
                    "prompt": prompt,
                    "response": original,
                    "feedback_note": note,
                    "metadata": metadata,
                }
            )

        file_records = {
            "sft.jsonl": sft_records,
            "preference.jsonl": preference_records,
            "evaluation-only.jsonl": evaluation_records,
            "regression.jsonl": regression_records,
        }
        files: dict[str, dict[str, Any]] = {}
        for name, records in file_records.items():
            data = _jsonl(records)
            _atomic_write(destination / name, data)
            files[name] = {
                "sha256": _sha256_bytes(data),
                "records": len(records),
                "bytes": len(data),
            }

        export_id = secrets.token_hex(16)
        manifest_core = {
            "schema": EXPORT_SCHEMA,
            "export_id": export_id,
            "created_at": utc_now_iso(),
            "redacted": redacted,
            "redaction_replacements": replacements,
            "source_store_verified": True,
            "automatic_upload_performed": False,
            "training_started": False,
            "model_activated": False,
            "files": files,
        }
        dataset_sha256 = hashlib.sha256(
            _canonical_json(manifest_core).encode("utf-8")
        ).hexdigest()
        manifest = {**manifest_core, "dataset_sha256": dataset_sha256}
        manifest_data = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        _atomic_write(destination / "manifest.json", manifest_data)
        self.store.record_export(
            export_id=export_id,
            redacted=redacted,
            dataset_sha256=dataset_sha256,
            counts={name: details["records"] for name, details in files.items()},
        )
        return manifest
