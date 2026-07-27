"""Durable SQLite store for Bella's human-reviewed tuning history."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from bella_harness.tuning.models import (
    ExportDisposition,
    FeedbackRating,
    ReviewedTuningExample,
    TuningCorrection,
    TuningError,
    TuningFeedback,
    TuningInteraction,
    TuningValidationError,
    sha256_text,
    utc_now_iso,
    validate_id,
)


SCHEMA_VERSION = 1
MAX_DATABASE_BYTES = 512 * 1024 * 1024


class TuningStoreError(TuningError):
    """Raised when the tuning database is unavailable, corrupt, or inconsistent."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class SQLiteTuningStore:
    """Transactional local store with immutable feedback and versioned corrections."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        if str(self.path) == ":memory:":
            raise TuningStoreError("persistent tuning storage cannot use ':memory:'")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _check_size(self) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size > MAX_DATABASE_BYTES:
                raise TuningStoreError("tuning database exceeds the 512 MiB safety limit")
        except OSError as exc:
            raise TuningStoreError(f"unable to inspect tuning database: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        self._check_size()
        try:
            conn = sqlite3.connect(str(self.path), timeout=15)
        except sqlite3.Error as exc:
            raise TuningStoreError(f"unable to open tuning database: {exc}") from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    def _initialize(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = FULL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS tuning_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS tuning_interactions (
                        id TEXT PRIMARY KEY,
                        prompt TEXT NOT NULL,
                        original_response TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        profile_id TEXT NOT NULL,
                        source_model TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        prompt_sha256 TEXT NOT NULL,
                        original_response_sha256 TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS tuning_feedback (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        id TEXT NOT NULL UNIQUE,
                        interaction_id TEXT NOT NULL REFERENCES tuning_interactions(id),
                        rating TEXT NOT NULL CHECK (rating IN (
                            'good', 'too_soft', 'too_harsh', 'too_long',
                            'too_vague', 'missed_point', 'wrong_memory',
                            'unsafe_overreach'
                        )),
                        note TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        reviewed_by_human INTEGER NOT NULL CHECK (reviewed_by_human = 1)
                    );

                    CREATE TABLE IF NOT EXISTS tuning_corrections (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        id TEXT NOT NULL UNIQUE,
                        interaction_id TEXT NOT NULL REFERENCES tuning_interactions(id),
                        version INTEGER NOT NULL CHECK (version >= 1),
                        corrected_response TEXT NOT NULL,
                        rationale TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        active INTEGER NOT NULL CHECK (active IN (0, 1)),
                        reviewed_by_human INTEGER NOT NULL CHECK (reviewed_by_human = 1),
                        corrected_response_sha256 TEXT NOT NULL,
                        UNIQUE (interaction_id, version)
                    );

                    CREATE UNIQUE INDEX IF NOT EXISTS ux_tuning_active_correction
                    ON tuning_corrections(interaction_id)
                    WHERE active = 1;

                    CREATE TABLE IF NOT EXISTS tuning_audit (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        record_id TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        event_hash TEXT NOT NULL UNIQUE,
                        details_json TEXT NOT NULL
                    );
                    """
                )
                row = conn.execute(
                    "SELECT value FROM tuning_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO tuning_meta(key, value) VALUES('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
                elif row["value"] != str(SCHEMA_VERSION):
                    raise TuningStoreError(
                        f"unsupported tuning schema version {row['value']!r}; "
                        f"expected {SCHEMA_VERSION}"
                    )
        except sqlite3.Error as exc:
            raise TuningStoreError(f"unable to initialize tuning database: {exc}") from exc
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            # Windows and some mounted filesystems may not support POSIX modes.
            pass

    @staticmethod
    def _row_to_interaction(row: sqlite3.Row) -> TuningInteraction:
        return TuningInteraction(
            id=row["id"],
            prompt=row["prompt"],
            original_response=row["original_response"],
            mode=row["mode"],
            risk_level=row["risk_level"],
            profile_id=row["profile_id"],
            source_model=row["source_model"],
            created_at=row["created_at"],
            prompt_sha256=row["prompt_sha256"],
            original_response_sha256=row["original_response_sha256"],
        )

    @staticmethod
    def _row_to_feedback(row: sqlite3.Row) -> TuningFeedback:
        return TuningFeedback(
            id=row["id"],
            interaction_id=row["interaction_id"],
            rating=FeedbackRating(row["rating"]),
            note=row["note"],
            created_at=row["created_at"],
            reviewed_by_human=bool(row["reviewed_by_human"]),
        )

    @staticmethod
    def _row_to_correction(row: sqlite3.Row) -> TuningCorrection:
        return TuningCorrection(
            id=row["id"],
            interaction_id=row["interaction_id"],
            version=int(row["version"]),
            corrected_response=row["corrected_response"],
            rationale=row["rationale"],
            created_at=row["created_at"],
            active=bool(row["active"]),
            reviewed_by_human=bool(row["reviewed_by_human"]),
            corrected_response_sha256=row["corrected_response_sha256"],
        )

    def _append_audit(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        record_id: str,
        details: dict[str, Any],
    ) -> None:
        validate_id("audit record id", record_id)
        previous = conn.execute(
            "SELECT event_hash FROM tuning_audit ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else "0" * 64
        next_row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS value FROM tuning_audit"
        ).fetchone()
        sequence = int(next_row["value"])
        occurred_at = utc_now_iso()
        details_json = _canonical_json(details)
        material = _canonical_json(
            {
                "sequence": sequence,
                "event_type": event_type,
                "record_id": record_id,
                "occurred_at": occurred_at,
                "previous_hash": previous_hash,
                "details": details,
            }
        )
        event_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO tuning_audit(
                sequence, event_type, record_id, occurred_at,
                previous_hash, event_hash, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sequence,
                event_type,
                record_id,
                occurred_at,
                previous_hash,
                event_hash,
                details_json,
            ),
        )

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
        interaction = TuningInteraction(
            id=interaction_id,
            prompt=prompt,
            original_response=original_response,
            mode=mode,
            risk_level=risk_level,
            profile_id=profile_id,
            source_model=source_model,
            created_at=created_at or utc_now_iso(),
            prompt_sha256=sha256_text(prompt),
            original_response_sha256=sha256_text(original_response),
        )
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT * FROM tuning_interactions WHERE id = ?", (interaction.id,)
                ).fetchone()
                if existing is not None:
                    stored = self._row_to_interaction(existing)
                    if stored != interaction:
                        raise TuningStoreError(
                            "interaction id already exists with different immutable content"
                        )
                    return stored
                conn.execute(
                    """
                    INSERT INTO tuning_interactions(
                        id, prompt, original_response, mode, risk_level,
                        profile_id, source_model, created_at, prompt_sha256,
                        original_response_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        interaction.id,
                        interaction.prompt,
                        interaction.original_response,
                        interaction.mode,
                        interaction.risk_level,
                        interaction.profile_id,
                        interaction.source_model,
                        interaction.created_at,
                        interaction.prompt_sha256,
                        interaction.original_response_sha256,
                    ),
                )
                self._append_audit(
                    conn,
                    "interaction_recorded",
                    interaction.id,
                    {
                        "prompt_sha256": interaction.prompt_sha256,
                        "original_response_sha256": interaction.original_response_sha256,
                        "mode": interaction.mode,
                        "risk_level": interaction.risk_level,
                        "profile_id": interaction.profile_id,
                        "source_model": interaction.source_model,
                        "hidden_memory_stored": False,
                    },
                )
            return interaction
        except sqlite3.Error as exc:
            raise TuningStoreError(f"unable to record tuning interaction: {exc}") from exc

    def add_feedback(
        self,
        *,
        interaction_id: str,
        rating: FeedbackRating | str,
        note: str = "",
        feedback_id: str | None = None,
        created_at: str | None = None,
    ) -> TuningFeedback:
        feedback = TuningFeedback(
            id=feedback_id or secrets.token_hex(16),
            interaction_id=interaction_id,
            rating=rating if isinstance(rating, FeedbackRating) else FeedbackRating(rating),
            note=note,
            created_at=created_at or utc_now_iso(),
            reviewed_by_human=True,
        )
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute(
                    "SELECT 1 FROM tuning_interactions WHERE id = ?", (interaction_id,)
                ).fetchone() is None:
                    raise TuningStoreError("cannot rate an unknown tuning interaction")
                conn.execute(
                    """
                    INSERT INTO tuning_feedback(
                        id, interaction_id, rating, note, created_at, reviewed_by_human
                    ) VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (
                        feedback.id,
                        feedback.interaction_id,
                        feedback.rating.value,
                        feedback.note,
                        feedback.created_at,
                    ),
                )
                self._append_audit(
                    conn,
                    "feedback_recorded",
                    feedback.id,
                    {
                        "interaction_id": interaction_id,
                        "rating": feedback.rating.value,
                        "reviewed_by_human": True,
                    },
                )
            return feedback
        except ValueError as exc:
            raise TuningValidationError(f"unsupported feedback rating: {rating!r}") from exc
        except sqlite3.Error as exc:
            raise TuningStoreError(f"unable to record tuning feedback: {exc}") from exc

    def add_correction(
        self,
        *,
        interaction_id: str,
        corrected_response: str,
        rationale: str = "",
        correction_id: str | None = None,
        created_at: str | None = None,
    ) -> TuningCorrection:
        validate_id("interaction id", interaction_id)
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute(
                    "SELECT 1 FROM tuning_interactions WHERE id = ?", (interaction_id,)
                ).fetchone() is None:
                    raise TuningStoreError("cannot correct an unknown tuning interaction")
                prior = conn.execute(
                    """
                    SELECT * FROM tuning_corrections
                    WHERE interaction_id = ? AND active = 1
                    """,
                    (interaction_id,),
                ).fetchone()
                version_row = conn.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1 AS value
                    FROM tuning_corrections WHERE interaction_id = ?
                    """,
                    (interaction_id,),
                ).fetchone()
                version = int(version_row["value"])
                correction = TuningCorrection(
                    id=correction_id or secrets.token_hex(16),
                    interaction_id=interaction_id,
                    version=version,
                    corrected_response=corrected_response,
                    rationale=rationale,
                    created_at=created_at or utc_now_iso(),
                    active=True,
                    reviewed_by_human=True,
                )
                if prior is not None:
                    conn.execute(
                        "UPDATE tuning_corrections SET active = 0 WHERE id = ?",
                        (prior["id"],),
                    )
                conn.execute(
                    """
                    INSERT INTO tuning_corrections(
                        id, interaction_id, version, corrected_response, rationale,
                        created_at, active, reviewed_by_human,
                        corrected_response_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?)
                    """,
                    (
                        correction.id,
                        correction.interaction_id,
                        correction.version,
                        correction.corrected_response,
                        correction.rationale,
                        correction.created_at,
                        correction.corrected_response_sha256,
                    ),
                )
                self._append_audit(
                    conn,
                    "correction_recorded",
                    correction.id,
                    {
                        "interaction_id": interaction_id,
                        "version": version,
                        "corrected_response_sha256": correction.corrected_response_sha256,
                        "superseded_correction_id": prior["id"] if prior else None,
                        "reviewed_by_human": True,
                    },
                )
            return correction
        except sqlite3.Error as exc:
            raise TuningStoreError(f"unable to record tuning correction: {exc}") from exc

    def list_reviewed_examples(self) -> tuple[ReviewedTuningExample, ...]:
        """Return one export decision per interaction using latest feedback."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        i.*,
                        f.id AS feedback_id,
                        f.rating AS feedback_rating,
                        f.note AS feedback_note,
                        f.created_at AS feedback_created_at,
                        f.reviewed_by_human AS feedback_human,
                        c.id AS correction_id,
                        c.version AS correction_version,
                        c.corrected_response,
                        c.rationale AS correction_rationale,
                        c.created_at AS correction_created_at,
                        c.active AS correction_active,
                        c.reviewed_by_human AS correction_human,
                        c.corrected_response_sha256
                    FROM tuning_interactions i
                    JOIN tuning_feedback f ON f.sequence = (
                        SELECT MAX(f2.sequence) FROM tuning_feedback f2
                        WHERE f2.interaction_id = i.id
                    )
                    LEFT JOIN tuning_corrections c
                        ON c.interaction_id = i.id AND c.active = 1
                    ORDER BY i.created_at, i.id
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise TuningStoreError(f"unable to read tuning examples: {exc}") from exc

        examples: list[ReviewedTuningExample] = []
        for row in rows:
            interaction = self._row_to_interaction(row)
            feedback = TuningFeedback(
                id=row["feedback_id"],
                interaction_id=interaction.id,
                rating=FeedbackRating(row["feedback_rating"]),
                note=row["feedback_note"],
                created_at=row["feedback_created_at"],
                reviewed_by_human=bool(row["feedback_human"]),
            )
            correction = None
            if row["correction_id"] is not None:
                correction = TuningCorrection(
                    id=row["correction_id"],
                    interaction_id=interaction.id,
                    version=int(row["correction_version"]),
                    corrected_response=row["corrected_response"],
                    rationale=row["correction_rationale"],
                    created_at=row["correction_created_at"],
                    active=bool(row["correction_active"]),
                    reviewed_by_human=bool(row["correction_human"]),
                    corrected_response_sha256=row["corrected_response_sha256"],
                )
            if feedback.rating.is_positive:
                disposition = ExportDisposition.SFT_CANDIDATE
            elif correction is not None:
                disposition = ExportDisposition.PREFERENCE_CANDIDATE
            else:
                disposition = ExportDisposition.EVALUATION_ONLY
            examples.append(
                ReviewedTuningExample(
                    interaction=interaction,
                    feedback=feedback,
                    correction=correction,
                    disposition=disposition,
                )
            )
        return tuple(examples)

    def verify_integrity(self) -> bool:
        """Verify SQLite integrity, content hashes, active correction uniqueness, and audit chain."""
        try:
            with self._connect() as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    return False
                duplicate_active = conn.execute(
                    """
                    SELECT interaction_id FROM tuning_corrections
                    WHERE active = 1 GROUP BY interaction_id HAVING COUNT(*) > 1
                    """
                ).fetchone()
                if duplicate_active is not None:
                    return False
                for row in conn.execute("SELECT * FROM tuning_interactions"):
                    if row["prompt_sha256"] != sha256_text(row["prompt"]):
                        return False
                    if row["original_response_sha256"] != sha256_text(row["original_response"]):
                        return False
                for row in conn.execute("SELECT * FROM tuning_corrections"):
                    if row["corrected_response_sha256"] != sha256_text(row["corrected_response"]):
                        return False

                previous_hash = "0" * 64
                expected_sequence = 1
                for row in conn.execute("SELECT * FROM tuning_audit ORDER BY sequence"):
                    if row["sequence"] != expected_sequence:
                        return False
                    if not hmac.compare_digest(row["previous_hash"], previous_hash):
                        return False
                    try:
                        details = json.loads(row["details_json"])
                    except json.JSONDecodeError:
                        return False
                    material = _canonical_json(
                        {
                            "sequence": row["sequence"],
                            "event_type": row["event_type"],
                            "record_id": row["record_id"],
                            "occurred_at": row["occurred_at"],
                            "previous_hash": row["previous_hash"],
                            "details": details,
                        }
                    )
                    expected_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
                    if not hmac.compare_digest(expected_hash, row["event_hash"]):
                        return False
                    previous_hash = row["event_hash"]
                    expected_sequence += 1
                return True
        except (sqlite3.Error, TuningValidationError, TuningStoreError):
            return False
