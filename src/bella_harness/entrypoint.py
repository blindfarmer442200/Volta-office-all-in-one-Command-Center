"""Installed Bella CLI entrypoint with diagnostics and optional service command."""

from __future__ import annotations

from bella_harness.cli import main
from bella_harness.doctor_cli import doctor_command
from bella_harness.service_cli import serve_command


# Registration is explicit and idempotent for import-based test runners.
if "doctor" not in main.commands:
    main.add_command(doctor_command)
if "serve" not in main.commands:
    main.add_command(serve_command)


if __name__ == "__main__":
    main()
