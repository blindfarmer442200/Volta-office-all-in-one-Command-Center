"""Runnable CLI proof for the side-effect-free Action Gate."""

from __future__ import annotations

import json

from click.testing import CliRunner

from bella_harness.cli import main


PAYLOAD = json.dumps({"subject": "Invoice", "body": "Invoice 1042 is overdue."})


def _args(request_text: str, *, confirm: bool = False):
    args = [
        "sandbox-action",
        request_text,
        "--kind",
        "send_message",
        "--target",
        "customer@example.com",
        "--payload",
        PAYLOAD,
        "--mode",
        "business",
    ]
    if confirm:
        args.append("--confirm")
    return args


def test_cli_preview_outputs_exact_fingerprint_without_capability():
    result = CliRunner().invoke(main, _args("Send an email to the customer"))
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["preview"]["status"] == "preview"
    assert len(output["preview"]["fingerprint"]) == 64
    assert output["preview"]["connector"] == "mock_action_sandbox"
    assert output["execution"] is None
    assert "capability" not in result.output.lower()


def test_cli_confirm_executes_only_the_mock_sandbox():
    result = CliRunner().invoke(
        main,
        _args("Send an email to the customer", confirm=True),
    )
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["confirmed"] is True
    assert output["execution"]["simulated"] is True
    assert output["execution"]["sideEffectsPerformed"] is False
    assert "capability" not in result.output.lower()


def test_cli_draft_cannot_be_upgraded_to_send():
    result = CliRunner().invoke(main, _args("Draft an email to the customer", confirm=True))
    assert result.exit_code != 0
    assert "does not require approval" in result.output


def test_cli_rejects_non_object_payload():
    args = _args("Send an email to the customer")
    payload_index = args.index("--payload") + 1
    args[payload_index] = '["not", "an", "object"]'
    result = CliRunner().invoke(main, args)
    assert result.exit_code != 0
    assert "JSON object" in result.output
