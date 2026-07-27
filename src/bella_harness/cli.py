"""Command-line entry point for bella-harness."""

from __future__ import annotations

import json
import sys

import click

from bella_harness.action_gate import (
    ActionGateError,
    ActionKind,
    ActionSpec,
    ActionValidationError,
)
from bella_harness.backends import BackendAbstraction, BackendError
from bella_harness.config import load_config
from bella_harness.deterministic.engine import Action
from bella_harness.evaluation import BellaEvaluationGate, EvaluationError
from bella_harness.harness import BellaHarness
from bella_harness.operator import BellaMode


@click.group()
@click.option("--config", "config_path", default=None, help="Path to a YAML config file.")
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    """bella-harness: deterministic-first agent safety harness."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


@main.command()
@click.argument("prompt")
@click.option(
    "--mode",
    type=click.Choice([mode.value for mode in BellaMode], case_sensitive=False),
    default=BellaMode.DEFAULT.value,
    show_default=True,
    help="Bella operating mode.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit result as JSON.")
@click.pass_context
def ask(ctx: click.Context, prompt: str, mode: str, as_json: bool) -> None:
    """Send a single prompt through the harness and print the result."""
    harness = BellaHarness(config_path=ctx.obj.get("config_path"))
    result = harness.handle(prompt, mode=mode)

    if as_json:
        click.echo(json.dumps({
            "action": result.action.value,
            "category": result.category,
            "backend_used": result.backend_used,
            "handled_deterministically": result.handled_deterministically,
            "memory_ids": list(result.memory_ids),
            "memory_explanations": list(result.memory_explanations),
            "excluded_unsafe_memory_ids": list(result.excluded_unsafe_memory_ids),
            "operator_profile_id": result.operator_profile_id,
            "operator_mode": result.operator_mode,
            "risk_level": result.risk_level,
            "approval_required": result.approval_required,
            "operator_reasons": list(result.operator_reasons),
            "operator_plan": list(result.operator_plan),
            "response": result.response,
        }))
    else:
        click.echo(result.response)

    if result.action == Action.BLOCK:
        sys.exit(1)


@main.command("sandbox-action")
@click.argument("request_text")
@click.option(
    "--kind",
    type=click.Choice([kind.value for kind in ActionKind], case_sensitive=False),
    required=True,
    help="Exact mock action kind.",
)
@click.option("--target", required=True, help="Exact reviewed target.")
@click.option(
    "--payload",
    "payload_json",
    required=True,
    help="Exact JSON object payload.",
)
@click.option(
    "--mode",
    type=click.Choice([mode.value for mode in BellaMode], case_sensitive=False),
    default=BellaMode.DEFAULT.value,
    show_default=True,
    help="Bella operating mode.",
)
@click.option(
    "--confirm",
    is_flag=True,
    help=(
        "Explicitly confirm and consume the one-use capability in the local mock "
        "sandbox. This is not biometric identity proof and cannot create side effects."
    ),
)
@click.pass_context
def sandbox_action(
    ctx: click.Context,
    request_text: str,
    kind: str,
    target: str,
    payload_json: str,
    mode: str,
    confirm: bool,
) -> None:
    """Preview or simulate one exact action with zero external side effects."""
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(
            f"payload must be valid JSON: {exc.msg}",
            param_hint="--payload",
        ) from exc
    if not isinstance(payload, dict):
        raise click.BadParameter(
            "payload must decode to a JSON object",
            param_hint="--payload",
        )

    try:
        spec = ActionSpec(kind=kind, target=target, payload=payload)
        harness = BellaHarness(config_path=ctx.obj.get("config_path"))
        preview = harness.prepare_action(request_text, spec, mode=mode)
        output = {
            "schema": "bella.action-demo.v1",
            "preview": {
                "id": preview.id,
                "status": preview.status.value,
                "connector": preview.spec.connector,
                "kind": preview.spec.kind.value,
                "target": preview.spec.target,
                "payload": preview.spec.payload,
                "fingerprint": preview.fingerprint,
                "risk_level": preview.risk_level.value,
                "expires_at": preview.expires_at,
                "summary": preview.summary,
            },
            "confirmed": False,
            "execution": None,
        }
        if confirm:
            authorization = harness.authorize_action(
                preview.id,
                preview.fingerprint,
                owner_confirmed=True,
            )
            execution = harness.execute_sandbox_action(
                preview.id,
                spec,
                preview.fingerprint,
                authorization.capability,
            )
            output["confirmed"] = True
            output["authorization_expires_at"] = authorization.expires_at
            output["execution"] = {
                "status": "simulated",
                "executed_at": execution.executed_at,
                "simulated": execution.simulated,
                "sideEffectsPerformed": execution.side_effects_performed,
                "result": execution.result,
            }
        click.echo(json.dumps(output, ensure_ascii=False, sort_keys=True))
    except (ActionGateError, ActionValidationError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("evaluate-bella")
@click.option(
    "--backend",
    type=click.Choice(["ollama"], case_sensitive=False),
    default="ollama",
    show_default=True,
    help="Pinned local backend. Cloud fallback is intentionally unavailable.",
)
@click.option(
    "--model",
    default=None,
    help="Exact Ollama model tag. Defaults to backends.ollama.model in config.",
)
@click.option(
    "--report",
    "report_path",
    default="bella-evaluation-report.json",
    show_default=True,
    help="Path for the hashed JSON evaluation report.",
)
@click.pass_context
def evaluate_bella(
    ctx: click.Context,
    backend: str,
    model: str | None,
    report_path: str,
) -> None:
    """Run all mandatory synthetic behavior scenarios against one Ollama model."""
    try:
        config = load_config(ctx.obj.get("config_path"))
        evaluation_config = config.get("evaluation", {}) or {}
        if not evaluation_config.get("enabled", True):
            raise EvaluationError("Bella evaluation is disabled in configuration")
        configured_backend = evaluation_config.get("backend", "ollama")
        if configured_backend != "ollama" or backend.lower() != "ollama":
            raise EvaluationError("Bella evaluation must remain pinned to local Ollama")

        backends = BackendAbstraction(config)
        try:
            selected_backend = backends.get("ollama")
        except KeyError as exc:
            raise EvaluationError("the Ollama backend is not enabled in configuration") from exc

        selected_model = model or evaluation_config.get("model") or selected_backend.model
        gate = BellaEvaluationGate(
            selected_backend,
            backend_name="ollama",
            model=selected_model,
        )
        report = gate.run()
        gate.write_report(report, report_path)
        click.echo(
            f"{report.passed_count}/{report.total} mandatory scenarios passed; "
            f"accepted={str(report.accepted).lower()}; model={report.model}; "
            f"report={report_path}; sha256={report.report_sha256}"
        )
        if not report.accepted:
            sys.exit(1)
    except (EvaluationError, BackendError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.option("--probes-dir", default=None, help="Directory containing probe modules.")
@click.option("--report", "report_path", default=None, help="Path to write the JSON report.")
@click.pass_context
def redteam(ctx: click.Context, probes_dir: str | None, report_path: str | None) -> None:
    """Run the red-team probe suite against the harness."""
    from redteam.runner import run_suite

    harness = BellaHarness(config_path=ctx.obj.get("config_path"))
    result = run_suite(harness, probes_dir=probes_dir, report_path=report_path)

    click.echo(f"{result.passed}/{result.total} probes clean "
               f"({result.breaches} breaches, {result.false_positives} false positives)")

    if result.breaches or result.false_positives:
        sys.exit(1)


if __name__ == "__main__":
    main()
