# bella-harness

A deterministic-first safety, memory, and authenticated service harness for
Bella AI. Rule-based code classifies every request before any model is involved,
governs which memories may be recalled, applies Bella's identity and consequence
policy, controls model routing, scans output, and keeps real-world actions
disabled.

Current deterministic red-team baseline: **115/115 clean** across 39 specialist
attack categories, with zero breaches and zero false positives.

## Current production scope

Bella Harness `0.2.x` is production-scoped for:

- deterministic input and output gates;
- governed read-only Mind Trace memory;
- Bella Operator identity, modes, risk, plans, and approval metadata;
- private/local Ollama generation;
- all-or-nothing local-model evaluation;
- explicit human correction and privacy-first tuning export;
- authenticated local-first HTTP chat and health endpoints;
- exact Action Gate preview and authorization in a side-effect-free mock sandbox;
- installable wheel, hardened non-root container, production doctor, dependency
  audit, checksums, and release manifest.

It is **not** production-ready for real email, calendar, payment, account, file,
smart-home, or device-control execution. Those connectors are intentionally not
implemented, and the HTTP service exposes no action endpoint.

## Safety model

```text
request
  |
  v
deterministic input gate
  |-- blocked ----------------------> refusal
  |-- direct -----------------------> deterministic answer
  `-- deferred
        |
        v
      Bella Operator
        |
        v
      approved Mind Trace recall
        |
        v
      privacy-aware backend routing
        |
        v
      model response
        |
        v
      deterministic output scan
```

Key guarantees:

- Blocked requests never reach memory or a model.
- Memory is evidence, never instructions or authority.
- Plans and approval metadata are not action capabilities.
- Ordinary model and HTTP responses cannot execute anything.
- Ollama is restricted to localhost or literal private addresses.
- An Ollama outage cannot silently route prompts or memory to cloud.
- A candidate model must pass all 18 Bella behavior scenarios.
- Normal conversations are not automatically captured for tuning.
- Tuning export is redacted by default and never uploads or trains itself.
- Service chat/readiness requires a strong bearer token.
- Service bodies, prompts, concurrency, timeouts, request rate, and failed
  authentication attempts are bounded.
- Service logs omit prompt, response, memory, token, and capability contents.

## Install

Base CLI:

```bash
python -m pip install --upgrade pip build
python -m build
python -m venv .venv
. .venv/bin/activate
python -m pip install dist/*.whl
python -m pip check
```

Authenticated service:

```bash
python -m pip install 'bella-harness[service]'
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Run the production checks:

```bash
bella doctor
bella doctor --live
```

The offline doctor checks policy, packaged configuration, store integrity,
backend settings, private Ollama routing, and service configuration when enabled.
`--live` adds a prompt-free Ollama health check.

## Quickstart

```bash
# No model required
bella ask "hello"
bella ask "2 + 2"

# Free-form response through configured Ollama
bella ask --mode business --json "Draft an email to the customer"

# Candidate model must pass 18/18
bella evaluate-bella \
  --model qwen3.5 \
  --report bella-evaluation-report.json

# Authenticated loopback service
export BELLA_SERVICE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export BELLA__SERVICE__ENABLED=true
bella serve

# Local mock action preview only
bella sandbox-action \
  "Send an email to the customer" \
  --kind send_message \
  --target customer@example.com \
  --payload '{"subject":"Invoice","body":"Invoice 1042 is overdue."}' \
  --mode business

# Explicit human correction; ordinary chats are never auto-captured
bella review-response \
  --db bella-tuning.sqlite3 \
  --interaction-id invoice-answer-001 \
  --prompt @prompt.txt \
  --response @original-response.txt \
  --rating unsafe_overreach \
  --corrected @corrected-response.txt \
  --mode business \
  --risk-level high \
  --model qwen3.5

bella verify-tuning --db bella-tuning.sqlite3
bella export-tuning \
  --db bella-tuning.sqlite3 \
  --output-dir bella-dataset

bella redteam
```

Source-tree execution:

```bash
PYTHONPATH=src python -m bella_harness <command>
```

## Authenticated service

The optional FastAPI service exposes only:

| Method | Path | Authentication |
|---|---|---|
| `GET` | `/health/live` | No; minimal status only |
| `GET` | `/health/ready` | Bearer token |
| `POST` | `/v1/chat` | Bearer token |

API docs, OpenAPI, CORS, proxy-header trust, Uvicorn access logs, and action
routes are disabled. Trace metadata is hidden unless a trusted client explicitly
requests `"trace": true`.

The shipped configuration is disabled and loopback-only. Non-loopback binding
requires explicit consent and an explicit non-loopback trusted Host. Docker
Compose uses Linux host networking so Bella can remain on loopback while
reaching a host Ollama and Caddy.

See [docs/SERVICE_DEPLOYMENT.md](docs/SERVICE_DEPLOYMENT.md).

## Mind Trace

Mind Trace is reached only after the deterministic gate defers a request.

- Only approved, current, non-superseded records may reach a model.
- Private records are excluded in Customer mode.
- Instruction-like stored text is screened.
- Context is bounded and labeled as untrusted data.
- Malformed configured stores fail closed by default.
- Memory cannot approve, write, delete, or execute.

See [docs/MIND_TRACE_MEMORY.md](docs/MIND_TRACE_MEMORY.md).

## Bella Operator

The operator layer keeps Bella outside model weights:

- fixed `bella-core-v1` identity;
- Default, Life, Home, Business, Technical, Care, Developer, Customer, and Quiet
  modes;
- Low, Medium, High, and Critical consequence classification;
- visible non-executing plans;
- current approval requirements;
- accessibility and uncertainty directives;
- false-completion prevention.

See [docs/BELLA_OPERATOR.md](docs/BELLA_OPERATOR.md).

## Action Gate

Action Gate binds an exact mock connector, kind, target, and JSON payload to a
SHA-256 fingerprint. It requires explicit confirmation before issuing a
short-lived one-use capability.

- `mock_action_sandbox` only;
- preview lifetime at most 15 minutes;
- authorization lifetime at most 5 minutes;
- only capability hashes retained;
- mutation, wrong capability, expiration, and replay fail closed;
- successful execution always reports `simulated=true` and
  `sideEffectsPerformed=false`.

See [docs/ACTION_GATE.md](docs/ACTION_GATE.md).

## Evaluation Gate

One exact Ollama model is tested against 18 mandatory synthetic scenarios for:

- personal support without business drift;
- missing-memory honesty;
- Customer-mode privacy;
- destructive, money, calendar, credential, and file requests;
- medication boundaries;
- Quiet-mode brevity;
- stored prompt-injection resistance;
- unsolicited faith language;
- low-vision and voice accessibility;
- remembered preference versus current permission;
- draft versus send and false-completion claims.

Evaluation receives no personal memory, credentials, capabilities, or tools. It
has no cloud fallback. A score of 17/18 fails.

See [docs/BELLA_EVALUATION_GATE.md](docs/BELLA_EVALUATION_GATE.md).

## Correction and tuning

The local SQLite tuning store preserves immutable prompts/responses, append-only
human feedback, exact versioned corrections, one active correction, content
hashes, and a hash-chained audit.

Redacted export creates:

```text
sft.jsonl
preference.jsonl
evaluation-only.jsonl
regression.jsonl
manifest.json
```

Hidden Mind Trace packets, connector credentials, and Action Gate capabilities
are not accepted. Exact unredacted export requires `--exact` and still remains
local.

See [docs/BELLA_TUNING_LOOP.md](docs/BELLA_TUNING_LOOP.md).

## Model routing and cloud egress

Default routing is local:

```yaml
harness:
  default_backend: ollama
  allow_cloud_fallback: false
```

Merely enabling OpenAI, Anthropic, or OpenRouter does not authorize automatic
fallback. Local-to-cloud fallback requires `allow_cloud_fallback: true` and an
enabled provider. A cloud provider selected as the default or explicitly pinned
by a library caller is an explicit cloud route.

See [docs/CLOUD_EGRESS.md](docs/CLOUD_EGRESS.md).

## Release gates

Every pull request runs on Python 3.10 and 3.12:

- source compilation;
- dependency vulnerability audit;
- unit tests with a release floor of 207;
- all 115 deterministic red-team probes;
- wheel and source-archive build;
- `twine check`;
- required source-archive content validation;
- clean wheel installation with the service extra and `pip check`;
- installed deterministic command and production doctor;
- non-root, read-only authenticated service container smoke test;
- closed action-route proof;
- SHA-256 checksums and commit-bound release manifest verification.

The release manifest requires the wheel, installed doctor, and authenticated
service container smoke tests to pass. A release tag must exactly match
`v<project-version>`, point to a commit contained in `main`, and have an exact
notes file under `docs/releases/`. Manual release workflow runs build evidence
but do not publish.

See [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md).

## Deployment boundary

A published package is not automatically ready for every host. The operator must
still complete:

```bash
bella doctor
bella doctor --live
bella evaluate-bella --model <exact-model-tag> --report bella-evaluation-report.json
```

Final device, screen-reader, voice, reverse-proxy, load, long-running Ollama,
network, token-rotation, and backup-restoration tests remain deployment-specific.

See [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md).

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [SECURITY.md](SECURITY.md)
- [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md)
- [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md)
- [docs/SERVICE_DEPLOYMENT.md](docs/SERVICE_DEPLOYMENT.md)
- [docs/CLOUD_EGRESS.md](docs/CLOUD_EGRESS.md)
- [docs/MIND_TRACE_MEMORY.md](docs/MIND_TRACE_MEMORY.md)
- [docs/BELLA_OPERATOR.md](docs/BELLA_OPERATOR.md)
- [docs/ACTION_GATE.md](docs/ACTION_GATE.md)
- [docs/BELLA_EVALUATION_GATE.md](docs/BELLA_EVALUATION_GATE.md)
- [docs/BELLA_TUNING_LOOP.md](docs/BELLA_TUNING_LOOP.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CLAUDE.md](CLAUDE.md)

MIT licensed. See [LICENSE](LICENSE).
