"""Command-line entry point for bella-harness."""

from __future__ import annotations

import json
import sys

import click

from bella_harness.deterministic.engine import Action
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
