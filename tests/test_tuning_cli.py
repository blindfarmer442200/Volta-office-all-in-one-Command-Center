"""End-to-end CLI tests for explicit Bella review and tuning export."""

from __future__ import annotations

import json

from click.testing import CliRunner

from bella_harness.cli import main


def test_normal_ask_never_creates_configured_tuning_store(tmp_path):
    database = tmp_path / "should-not-exist.sqlite3"
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["ask", "hello"],
        env={"BELLA__TUNING__STORE_PATH": str(database)},
    )
    assert result.exit_code == 0, result.output
    assert "Hello" in result.output
    assert not database.exists()


def test_review_verify_and_redacted_export_commands(tmp_path):
    database = tmp_path / "bella-tuning.sqlite3"
    prompt_file = tmp_path / "prompt.txt"
    response_file = tmp_path / "response.txt"
    corrected_file = tmp_path / "corrected.txt"
    prompt_file.write_text("Email person@example.com about invoice 1042.", encoding="utf-8")
    response_file.write_text("I sent it to person@example.com.", encoding="utf-8")
    corrected_file.write_text(
        "I have not sent it. Here is a draft for your review.", encoding="utf-8"
    )

    runner = CliRunner()
    review = runner.invoke(
        main,
        [
            "review-response",
            "--db",
            str(database),
            "--interaction-id",
            "cli-review-1",
            "--prompt",
            f"@{prompt_file}",
            "--response",
            f"@{response_file}",
            "--rating",
            "unsafe_overreach",
            "--corrected",
            f"@{corrected_file}",
            "--note",
            "Bella falsely claimed execution.",
            "--mode",
            "business",
            "--risk-level",
            "high",
            "--model",
            "qwen3.5",
        ],
    )
    assert review.exit_code == 0, review.output
    review_payload = json.loads(review.output)
    assert review_payload["store_verified"] is True
    assert review_payload["correction_version"] == 1
    assert review_payload["conversation_auto_saved"] is False
    assert "person@example.com" not in review.output

    verify = runner.invoke(main, ["verify-tuning", "--db", str(database)])
    assert verify.exit_code == 0, verify.output
    assert json.loads(verify.output)["verified"] is True

    output_dir = tmp_path / "dataset"
    export = runner.invoke(
        main,
        ["export-tuning", "--db", str(database), "--output-dir", str(output_dir)],
    )
    assert export.exit_code == 0, export.output
    export_payload = json.loads(export.output)
    assert export_payload["redacted"] is True
    assert export_payload["automatic_upload_performed"] is False
    assert export_payload["training_started"] is False
    assert export_payload["model_activated"] is False
    assert "person@example.com" not in (output_dir / "sft.jsonl").read_text(
        encoding="utf-8"
    )
    assert (output_dir / "preference.jsonl").exists()
    assert (output_dir / "regression.jsonl").exists()
    assert (output_dir / "manifest.json").exists()


def test_good_review_cannot_include_a_replacement(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "review-response",
            "--db",
            str(tmp_path / "tuning.sqlite3"),
            "--interaction-id",
            "good-with-replacement",
            "--prompt",
            "Prompt",
            "--response",
            "Response",
            "--rating",
            "good",
            "--corrected",
            "Replacement",
            "--model",
            "qwen3.5",
        ],
    )
    assert result.exit_code != 0
    assert "good response must not include a replacement" in result.output


def test_review_command_requires_database_when_config_has_none():
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "review-response",
            "--interaction-id",
            "missing-db",
            "--prompt",
            "Prompt",
            "--response",
            "Response",
            "--rating",
            "good",
            "--model",
            "qwen3.5",
        ],
    )
    assert result.exit_code != 0
    assert "pass --db or set tuning.store_path" in result.output
