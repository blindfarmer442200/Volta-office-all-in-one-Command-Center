"""Installed command for Bella's authenticated HTTP service."""

from __future__ import annotations

import copy

import click

from bella_harness.config import ConfigError, load_config
from bella_harness.service.settings import ServiceConfigurationError, ServiceSettings


@click.command("serve")
@click.option("--host", default=None, help="Override the configured bind host.")
@click.option("--port", type=int, default=None, help="Override the configured TCP port.")
@click.option(
    "--log-level",
    type=click.Choice(["critical", "error", "warning", "info", "debug"]),
    default=None,
)
@click.pass_context
def serve_command(
    ctx: click.Context,
    host: str | None,
    port: int | None,
    log_level: str | None,
) -> None:
    """Run Bella's authenticated chat and health service."""
    try:
        config = copy.deepcopy(load_config(ctx.obj.get("config_path")))
        service_config = config.setdefault("service", {})
        if host is not None:
            service_config["host"] = host
        if port is not None:
            service_config["port"] = port
        if log_level is not None:
            service_config["log_level"] = log_level
        settings = ServiceSettings.from_config(config)
        if not settings.enabled:
            raise ServiceConfigurationError(
                "Bella HTTP service is disabled; set BELLA__SERVICE__ENABLED=true"
            )
        try:
            import uvicorn
            from bella_harness.service.app import create_app
        except ImportError as exc:
            raise click.ClickException(
                "service dependencies are missing; install bella-harness[service]"
            ) from exc

        app = create_app(config=config)
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
            access_log=False,
            proxy_headers=False,
            server_header=False,
            date_header=False,
        )
    except (ConfigError, ServiceConfigurationError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
