"""Click commands for live Bella host acceptance and evidence verification."""

from __future__ import annotations

import json

import click

from bella_harness.config import ConfigError, load_config
from bella_harness.deployment import (
    DeploymentAcceptanceError,
    run_deployment_acceptance,
    verify_deployment_report,
)
from bella_harness.service.settings import (
    ServiceConfigurationError,
    ServiceSettings,
    resolve_service_token,
)


@click.command("accept-deployment")
@click.option(
    "--service-url",
    default=None,
    help="Private Bella service root URL. Defaults to configured host and port.",
)
@click.option(
    "--model",
    default=None,
    help="Exact live Ollama model tag. Defaults to evaluation/backend configuration.",
)
@click.option(
    "--container",
    "container_name",
    default=None,
    help="Optional running Docker container name to inspect for hardening.",
)
@click.option(
    "--evaluation-report",
    default="bella-evaluation-report.json",
    show_default=True,
    help="Path for the live 18-scenario evaluation evidence.",
)
@click.option(
    "--report",
    "deployment_report",
    default="bella-deployment-acceptance.json",
    show_default=True,
    help="Path for the hashed deployment acceptance report.",
)
@click.pass_context
def accept_deployment_command(
    ctx: click.Context,
    service_url: str | None,
    model: str | None,
    container_name: str | None,
    evaluation_report: str,
    deployment_report: str,
) -> None:
    """Require live doctor, 18/18 model, authenticated API, and closed actions."""
    try:
        config = load_config(ctx.obj.get("config_path"))
        settings = ServiceSettings.from_config(config)
        token = resolve_service_token(settings.token_env)
        selected_url = service_url or f"http://{settings.host}:{settings.port}"
        report = run_deployment_acceptance(
            config,
            service_token=token,
            service_url=selected_url,
            model=model,
            evaluation_report_path=evaluation_report,
            deployment_report_path=deployment_report,
            container_name=container_name,
        )
        click.echo(
            json.dumps(
                {
                    "schema": report.schema,
                    "accepted": report.accepted,
                    "package_version": report.package_version,
                    "model": report.model,
                    "service_url": report.service_url,
                    "checks_passed": sum(
                        1 for check in report.checks if check.status == "pass"
                    ),
                    "checks_failed": sum(
                        1 for check in report.checks if check.status == "fail"
                    ),
                    "checks_skipped": sum(
                        1 for check in report.checks if check.status == "skip"
                    ),
                    "evaluation_report": evaluation_report,
                    "deployment_report": deployment_report,
                    "report_sha256": report.report_sha256,
                    "model_activated": False,
                    "external_action_performed": False,
                },
                sort_keys=True,
            )
        )
        if not report.accepted:
            raise click.exceptions.Exit(1)
    except (
        ConfigError,
        DeploymentAcceptanceError,
        ServiceConfigurationError,
        OSError,
        ValueError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc


@click.command("verify-deployment")
@click.option(
    "--report",
    "deployment_report",
    default="bella-deployment-acceptance.json",
    show_default=True,
)
def verify_deployment_command(deployment_report: str) -> None:
    """Verify the deployment acceptance report hash and critical-check state."""
    verified = verify_deployment_report(deployment_report)
    click.echo(json.dumps({"verified": verified}, sort_keys=True))
    if not verified:
        raise click.exceptions.Exit(1)
