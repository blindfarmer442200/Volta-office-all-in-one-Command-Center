"""Click command registration for Bella production diagnostics."""

from __future__ import annotations

import json

import click

from bella_harness.config import ConfigError, load_config
from bella_harness.doctor import run_doctor


@click.command("doctor")
@click.option(
    "--live",
    is_flag=True,
    help="Also run a prompt-free live Ollama health check.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the full machine-readable doctor report.",
)
@click.pass_context
def doctor_command(ctx: click.Context, live: bool, as_json: bool) -> None:
    """Audit Bella's installed production configuration and local stores."""
    try:
        report = run_doctor(load_config(ctx.obj.get("config_path")), live=live)
    except (ConfigError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        click.echo(
            f"Bella production readiness: {'PASS' if report.ready else 'FAIL'} "
            f"({report.package_version})"
        )
        for check in report.checks:
            label = check.status.upper()
            critical = " critical" if check.critical else ""
            click.echo(f"[{label}{critical}] {check.name}: {check.message}")
    if not report.ready:
        raise click.exceptions.Exit(1)
