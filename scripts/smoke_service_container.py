#!/usr/bin/env python3
"""Build and smoke-test Bella's hardened authenticated service container."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


class SmokeError(RuntimeError):
    pass


def _run(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def _request(
    url: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
    timeout: float = 3.0,
) -> tuple[int, bytes]:
    data = None
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def smoke(*, image: str, name: str, port: int, log_path: Path) -> None:
    token = secrets.token_urlsafe(48)
    _run("docker", "build", "--pull=false", "-t", image, ".")
    inspected = _run(
        "docker",
        "inspect",
        "--format",
        "{{.Config.User}}",
        image,
        capture=True,
    ).stdout.strip()
    if inspected != "10001:10001":
        raise SmokeError(f"container user is {inspected!r}, expected '10001:10001'")

    _run(
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "host",
        "--read-only",
        "--tmpfs",
        "/tmp:size=64m,mode=1777",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "-e",
        f"BELLA_SERVICE_TOKEN={token}",
        "-e",
        f"BELLA__SERVICE__PORT={port}",
        image,
        capture=True,
    )

    base_url = f"http://127.0.0.1:{port}"
    try:
        for attempt in range(40):
            try:
                status, _ = _request(f"{base_url}/health/live")
                if status == 200:
                    break
            except OSError:
                pass
            if attempt == 39:
                raise SmokeError("Bella service did not become live")
            time.sleep(1)

        status, body = _request(
            f"{base_url}/v1/chat",
            token=token,
            payload={"prompt": "hello", "mode": "life"},
            timeout=10,
        )
        if status != 200:
            raise SmokeError(f"chat returned HTTP {status}")
        response = json.loads(body.decode("utf-8"))
        if response.get("schema") != "bella.service-chat.v1":
            raise SmokeError("chat response schema is invalid")
        if response.get("handled_deterministically") is not True:
            raise SmokeError("deterministic smoke request was not handled directly")
        if response.get("external_action_performed") is not False:
            raise SmokeError("service claimed an external action")
        if "trace" in response:
            raise SmokeError("service exposed trace data without explicit request")

        status, _ = _request(
            f"{base_url}/v1/actions",
            token=token,
            payload={},
        )
        if status != 404:
            raise SmokeError(f"unexpected action route status: {status}")
    finally:
        try:
            logs = _run("docker", "logs", name, capture=True)
            log_path.write_text(logs.stdout + logs.stderr, encoding="utf-8")
        except (OSError, subprocess.SubprocessError):
            pass
        subprocess.run(
            ["docker", "rm", "-f", name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="bella-harness-service:smoke")
    parser.add_argument("--name", default="bella-service-smoke")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--log", default="docker-service.log")
    args = parser.parse_args(argv)
    try:
        smoke(
            image=args.image,
            name=args.name,
            port=args.port,
            log_path=Path(args.log),
        )
    except (SmokeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"service container smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"container_smoke_passed": True, "image": args.image}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
