# Bella Production Readiness

This document defines the production boundary for `bella-harness` 0.2.x.

## Current production scope

The harness is intended to be production-ready for these bounded functions:

- deterministic request blocking and direct answers;
- governed read-only Mind Trace memory recall;
- Bella identity, mode, risk, and approval policy;
- model output scanning;
- local/private Ollama response generation;
- all-or-nothing Bella model evaluation;
- explicit human correction and local tuning-data export;
- authenticated local-first HTTP chat and health endpoints;
- exact Action Gate preview and authorization in the side-effect-free mock
  sandbox.

It is **not** production-ready for real email, calendar, payment, file, account,
smart-home, or device-control execution. Those connectors do not exist in the
current production scope, and the HTTP service exposes no action route.

## Installation gate

Build and install the package rather than running an untracked source directory:

```bash
python -m pip install --upgrade pip build
python -m build
python -m venv .venv
. .venv/bin/activate
python -m pip install 'bella-harness[service] @ file:///absolute/path/to/dist/bella_harness-0.2.0-py3-none-any.whl'
python -m pip check
```

Windows PowerShell activation:

```powershell
.venv\Scripts\Activate.ps1
```

The wheel contains Bella's default configuration. CI rejects a package that
cannot run deterministic commands, import the service dependencies, or run the
production doctor after clean install.

## Host readiness gate

Run the offline checks first:

```bash
bella doctor
```

Then start Ollama and run the prompt-free live check:

```bash
bella doctor --live
```

Deployment is blocked when any critical doctor check fails. Warnings for an
unconfigured memory or tuning store are acceptable only when the deployment
intentionally runs without those features. A disabled HTTP service is reported
as a noncritical skip.

When the service is enabled, doctor additionally verifies:

- loopback or explicitly approved remote binding;
- explicit trusted hosts without wildcards;
- strong environment-sourced bearer token;
- bounded request, prompt, concurrency, timeout, request-rate, and failed-auth
  limits.

Doctor output reports safe status metadata only. It does not print prompt text,
private memory contents, tuning responses, tokens, credentials, or capabilities.

## Ollama network boundary

The Ollama adapter accepts only:

- `localhost`;
- literal loopback IP addresses;
- literal private or link-local IP addresses.

It rejects public IPs, arbitrary DNS hosts, embedded credentials, URL prefixes,
queries, fragments, redirects, invalid localhost resolution, oversized prompts
or responses, malformed JSON/UTF-8, missing response text, and invalid model tags
or temperatures.

Use a VPN or private address when Ollama runs on another trusted host. Do not
expose Ollama directly to the public internet.

## Authenticated service gate

Install the service extra, generate a token, and enable the loopback service:

```bash
export BELLA_SERVICE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export BELLA__SERVICE__ENABLED=true
bella doctor
bella serve
```

Acceptance checks:

1. `/health/live` returns minimal unauthenticated liveness.
2. `/health/ready` rejects missing/invalid tokens and succeeds with the token.
3. `/v1/chat` rejects missing/invalid tokens.
4. A deterministic `hello` response succeeds.
5. `external_action_performed` is always false.
6. Trace metadata is absent unless explicitly requested.
7. `/v1/actions`, API docs, and OpenAPI return 404.
8. Trusted Host validation rejects an unapproved Host.
9. Repeated failed authentication is rate limited without blocking a valid token.
10. Request bodies, prompts, authenticated requests, concurrency, and timeouts
    are bounded.
11. Logs contain request metadata but not prompt, response, memory, or token
    contents.

For internet-facing access, keep Bella on loopback and terminate HTTPS in Caddy.
Do not publish port 8765 directly. See `docs/SERVICE_DEPLOYMENT.md`.

## Required release gates

Every release candidate must pass:

1. Python 3.10 unit tests.
2. Python 3.12 unit tests.
3. All 115 deterministic red-team probes.
4. Dependency vulnerability audit.
5. Wheel and source-archive build.
6. Distribution metadata and source-content validation.
7. Clean wheel installation with the service extra.
8. `pip check` with no broken dependencies.
9. Installed `bella ask "hello"` smoke test.
10. Installed `bella doctor --json` with `ready=true` offline.
11. Non-root, read-only container build and authenticated service smoke test.
12. Proof that the service exposes no action route.
13. Package/default-config synchronization tests.
14. Exact release commit, artifact hashes, and release manifest verification.

Before deploying a selected local model, also require:

```bash
bella evaluate-bella --model <exact-model-tag> --report bella-evaluation-report.json
```

The exact model must pass all 18 mandatory scenarios. Passing does not activate
or authorize the model automatically.

## Container deployment

The provided image must run as UID/GID `10001:10001`. Production Compose adds:

- read-only root filesystem;
- `/tmp` tmpfs;
- all capabilities dropped;
- `no-new-privileges`;
- Linux host networking;
- required bearer-token environment value;
- loopback Bella and Ollama endpoints;
- no published service port.

Container CI uses the same constraints and verifies authenticated deterministic
chat plus a closed action route. A passing container smoke test does not prove
host firewall, Caddy, TLS, Docker daemon, or base-image provenance.

## Memory deployment

Configure a Mind Trace JSONL file only after validating ownership and backup:

```bash
export BELLA__MEMORY__STORE_PATH=/secure/path/mind-trace.jsonl
bella doctor
```

The store must be a regular UTF-8 file under size/record limits. A malformed
configured store blocks model use when `memory.fail_closed` is enabled.

## Tuning deployment

Normal conversations are not captured. Configure SQLite only when the operator
intends to collect explicit reviews:

```bash
export BELLA__TUNING__STORE_PATH=/secure/path/bella-tuning.sqlite3
bella doctor
bella verify-tuning
```

Keep redacted export as the default. Exact export requires `--exact` and must
remain in a trusted local environment.

## Backup and recovery

Back up when used:

- Mind Trace JSONL store;
- Bella tuning SQLite database, including WAL/SHM files during live backup;
- evaluation reports;
- tuning export manifests and datasets;
- external deployment configuration;
- Caddy configuration and service secret references;
- release wheel, source archive, checksums, and manifest.

Use SQLite's online backup mechanism or stop writes before copying. Test
restoration separately. A backup never restored is not a verified backup.

## Operational monitoring

At minimum monitor:

- process/container exit and restart count;
- liveness and authenticated readiness;
- HTTP 401, 403, 429, 502, 503, and 504 rates;
- backend failures and timeouts;
- output-scan blocks;
- memory/tuning integrity failures;
- doctor and model-evaluation reports;
- Action Gate preview/authorization/replay events;
- token rotation and certificate expiry;
- host disk, memory, CPU, and Ollama queue pressure.

Do not log raw prompts, responses, memory packets, bearer tokens, credentials,
one-use capabilities, or unredacted tuning data.

## Rollback

Keep the previous accepted wheel, container build reference, configuration,
model tag, evaluation report, checksums, and release manifest. Roll back when:

- doctor becomes critical-fail;
- red-team, service, container, or regression results worsen;
- the selected model no longer passes 18/18;
- memory/tuning integrity fails;
- authentication, Host validation, or rate limiting regresses;
- output scanning detects unexpected leakage;
- response quality materially regresses.

A restored model still requires its matching accepted evaluation report.

## Remaining external validation

Repository CI cannot prove:

- physical Android or iPhone behavior;
- long-running Ollama/service stability on the deployment host;
- final screen-reader and voice quality;
- Caddy/TLS/domain behavior;
- performance under final hardware and network load;
- token rotation with real clients;
- backup restoration on the operator's storage;
- real connector safety, because real connectors remain absent.

Complete those tests on the target host before calling that deployment
production-ready. The package may pass release gates while a specific machine,
model, reverse proxy, network, accessibility setup, or backup plan still fails.
