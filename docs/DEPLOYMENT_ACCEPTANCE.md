# Bella Live Deployment Acceptance

Repository CI proves the package, deterministic gates, service contracts, and
hardened container. It cannot prove that a particular host, Ollama model,
network, reverse proxy, token, or running container is ready.

`bella accept-deployment` closes that gap with one fail-closed host acceptance
command and two hashed evidence files.

## Prerequisites

Before running acceptance:

1. Install the exact accepted Bella wheel with the `service` extra.
2. Start Ollama on localhost or a literal private IP.
3. Pull the exact model tag to evaluate.
4. Start Bella's authenticated service.
5. Set the service token in the environment named by `service.token_env`.
6. Optionally start the hardened Docker container when container inspection is
   part of this deployment.

Example:

```bash
export BELLA_SERVICE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export BELLA__SERVICE__ENABLED=true
bella serve
```

Run the acceptance command from another terminal:

```bash
bella accept-deployment \
  --service-url http://127.0.0.1:8765 \
  --model qwen3.5:exact-tag \
  --container bella-service \
  --evaluation-report bella-evaluation-report.json \
  --report bella-deployment-acceptance.json
```

The command exits successfully only when every critical requested gate passes.
It never activates a model and never performs an external action.

## Required live gates

The acceptance engine verifies:

- the service URL is localhost or a literal private address;
- the live service-aware production doctor passes;
- the exact Ollama model passes all 18 mandatory Bella scenarios;
- the evaluation report is written and hashed;
- unauthenticated liveness is valid and minimal;
- a wrong bearer token is rejected;
- authenticated prompt-free readiness succeeds;
- authenticated deterministic `hello` succeeds;
- deterministic chat reports `external_action_performed=false`;
- trace metadata is absent unless requested;
- `/v1/actions` returns 404;
- when `--container` is supplied, Docker reports:
  - running state;
  - UID/GID `10001:10001`;
  - read-only root filesystem;
  - all capabilities dropped;
  - `no-new-privileges` enabled.

A model result of 17/18 is rejection. A reachable action route is rejection. A
wrong token that is accepted is rejection. A public or arbitrary DNS service URL
is rejected before network traffic.

## Evidence files

The command writes:

```text
bella-evaluation-report.json
bella-deployment-acceptance.json
```

The deployment report contains:

- package version reported by the installed production doctor;
- exact private service URL;
- exact model tag;
- timestamp;
- every check and bounded non-secret evidence;
- evaluation report SHA-256;
- overall acceptance state;
- deployment report SHA-256.

It does not contain the bearer token, prompt bodies, private memory contents,
Action Gate capabilities, or connector credentials.

Verify the report later:

```bash
bella verify-deployment --report bella-deployment-acceptance.json
```

Verification rejects:

- changed report bytes;
- malformed schemas or checks;
- invalid status or critical fields;
- acceptance claims inconsistent with critical checks;
- missing or malformed evaluation hashes on accepted reports.

## Container inspection is optional but explicit

When `--container` is omitted, the report records a noncritical skip. This is
appropriate for a direct virtual-environment deployment.

When `--container` is supplied, container hardening becomes a critical gate. A
weak or unavailable container causes deployment rejection.

The command invokes `docker inspect` without a shell. The container name is
bounded and may not contain whitespace.

## Operational use

Run acceptance:

- before first production use;
- after changing Bella package version;
- after changing Ollama model tag or Modelfile;
- after changing service binding, token, trusted hosts, Caddy, or networking;
- after restoring memory or tuning data;
- after host OS, Docker, Python, FastAPI, Uvicorn, or Ollama upgrades;
- after a security incident;
- before declaring rollback complete.

Archive both reports with the release wheel, source archive, checksums, release
manifest, deployment configuration, and backup-restoration evidence.

## Remaining human and device gates

A passing deployment report still does not prove:

- final screen-reader and voice quality;
- physical Android or iPhone behavior;
- Caddy/TLS/domain correctness when acceptance targets loopback directly;
- sustained performance under the real workload;
- long-running Ollama stability;
- successful token rotation with every client;
- successful backup restoration on the actual storage;
- safety of real connectors, because real connectors remain absent.

Those deployment-specific checks must be completed and recorded separately.
