# bella-harness

A deterministic-first agent safety harness. A rule-based gate classifies every
request *before* any LLM is involved—blocking known attack patterns, answering
trivial requests directly, and deferring legitimate requests to an approved
backend.

Red-team score: **115/115 clean** across 39 specialist attack categories, with
zero breaches and zero false positives in CI.

## What Bella protects

- Blocks known attack patterns before memory or model access.
- Answers greetings and arithmetic without a model call.
- Recalls approved Mind Trace memory only after the deterministic gate defers.
- Applies Bella identity, mode, risk, accessibility, and approval rules outside
  model weights.
- Separates plans from actions through an exact, expiring, one-use Action Gate.
- Keeps the Action Gate limited to a local side-effect-free mock sandbox.
- Rejects candidate models unless all 18 Bella behavior scenarios pass.
- Learns only from explicit human review and versioned corrections.
- Redacts tuning exports by default and never uploads or trains automatically.
- Scans model output before returning it to the user.
- Restricts Ollama to localhost or literal private-network addresses.
- Builds and smoke-tests an installable wheel in CI.

## Install

```bash
python -m pip install --upgrade pip build
python -m build
python -m venv .venv
. .venv/bin/activate
python -m pip install dist/*.whl
python -m pip check
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Run the production doctor before using a model:

```bash
bella doctor
bella doctor --live
```

The offline doctor verifies policy, package data, configured stores, and the
private Ollama endpoint. `--live` adds a prompt-free Ollama health check.

## Quickstart

```bash
# Deterministic responses—no backend required
bella ask "hello"
bella ask "2 + 2"

# Free-form request through configured Ollama
bella ask --mode business --json "Draft an email to the customer"

# Exact mock action preview—never creates an external side effect
bella sandbox-action \
  "Send an email to the customer" \
  --kind send_message \
  --target customer@example.com \
  --payload '{"subject":"Invoice","body":"Invoice 1042 is overdue."}' \
  --mode business

# Evaluate one exact local model. Any failure rejects it.
bella evaluate-bella \
  --model qwen3.5 \
  --report bella-evaluation-report.json

# Explicitly record a human correction. Normal chats are never auto-captured.
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

# Offline deterministic attack suite
bella redteam
```

Source-tree commands remain available through:

```bash
PYTHONPATH=src python -m bella_harness <command>
```

## Production scope

Version `0.2.x` is production-scoped for:

- deterministic input and output gates;
- read-only governed memory;
- Bella Operator policy;
- local/private Ollama generation;
- model evaluation;
- explicit correction and dataset export;
- mock-only Action Gate authorization.

It is **not** production-ready for real email, calendar, payment, account, file,
smart-home, or device-control execution. Those connectors are intentionally not
implemented.

See [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) before deploying.

## Mind Trace memory

Mind Trace is the bounded, human-governed memory seam inside the harness. It is
reached only after the deterministic input gate returns `DEFER_TO_LLM`.
Blocked requests and direct deterministic answers never read memory.

- Only approved, current, non-superseded records can reach a model.
- Private records are excluded in Customer mode.
- Instruction-like memory is rejected by the deterministic gate.
- Memory is labeled as untrusted JSON data, never instructions.
- Memory cannot authorize external actions.
- Malformed configured stores fail closed by default.
- Irrelevant or empty recall leaves the original request unchanged.

See [docs/MIND_TRACE_MEMORY.md](docs/MIND_TRACE_MEMORY.md).

## Bella Operator

Bella Operator provides:

- fixed `bella-core-v1` identity;
- Default, Life, Home, Business, Technical, Care, Developer, Customer, and Quiet
  modes;
- deterministic Low, Medium, High, and Critical consequence classification;
- visible plans for consequential requests;
- current approval requirements for High and Critical requests;
- accessibility and uncertainty rules;
- a hard rule that plans and memories are not execution authority;
- a hard rule that completed-action claims require verified tool results.

Operator metadata is returned by `bella ask --json`. See
[docs/BELLA_OPERATOR.md](docs/BELLA_OPERATOR.md).

## Bella Action Gate

Action Gate binds an exact connector, kind, target, and JSON payload to a
SHA-256 fingerprint, then requires explicit confirmation before issuing a
short-lived one-use capability.

Current guarantees:

- only `mock_action_sandbox` is accepted;
- previews expire in at most 15 minutes;
- authorizations expire in at most 5 minutes;
- only a capability hash is retained;
- changed payloads and replayed capabilities fail closed;
- High requests cannot authorize Critical action kinds;
- audit events are hash chained;
- successful execution always records `simulated=true` and
  `sideEffectsPerformed=false`.

See [docs/ACTION_GATE.md](docs/ACTION_GATE.md).

## Bella Evaluation Gate

The Evaluation Gate tests one exact local Ollama model against 18 mandatory
synthetic behavior scenarios covering:

- personal support without business drift;
- missing-memory honesty and unreviewed information;
- Customer-mode privacy;
- destructive actions, money, calendar, credentials, and files;
- medication changes;
- Quiet-mode brevity;
- stored prompt-injection resistance;
- unsolicited faith language;
- accessibility for low vision and voice use;
- remembered approval versus current permission;
- draft versus send and false-completion claims.

The model must return strict JSON. The gate sends no personal memory or real
credentials, has no cloud fallback, never activates a model automatically, and
never grants permissions. A score of 17/18 still fails.

See [docs/BELLA_EVALUATION_GATE.md](docs/BELLA_EVALUATION_GATE.md).

## Bella Correction and Tuning Loop

The tuning loop is explicit and human controlled. Ordinary conversations are
not silently added to a dataset.

The SQLite store preserves:

- immutable prompts and original responses with SHA-256 values;
- append-only human feedback;
- exact human replacement answers;
- correction version history with one active replacement;
- a hash-chained audit trail;
- export audit events.

Redacted export separates reviewed data into:

- `sft.jsonl`;
- `preference.jsonl`;
- `evaluation-only.jsonl`;
- `regression.jsonl`;
- `manifest.json`.

The loop never stores hidden Mind Trace packets, connector credentials, or
Action Gate capabilities. It never uploads, trains, or activates a model. Exact
unredacted export requires `export-tuning --exact`.

See [docs/BELLA_TUNING_LOOP.md](docs/BELLA_TUNING_LOOP.md).

## Ollama transport

The Ollama adapter accepts `localhost` or a literal private/loopback IP address.
It rejects public IPs, arbitrary DNS names, embedded credentials, URL prefixes,
queries, fragments, redirects, malformed JSON, invalid UTF-8, and oversized
prompts or responses.

Use a private IP or VPN address for a trusted Ollama host. Do not expose Ollama
directly to the public internet.

## Backends

| Backend | Default model | Default state |
|---|---|---|
| Ollama | `qwen3.5` | Enabled, local/private only |
| OpenAI | `gpt-4o-mini` | Disabled |
| Anthropic | `claude-3-5-sonnet-latest` | Disabled |
| OpenRouter | `meta-llama/llama-3.1-70b-instruct` | Disabled |

API keys are read only from named environment variables. Literal secrets in
configuration are rejected.

## Verification

Every PR runs:

- Python 3.10 unit tests;
- Python 3.12 unit tests;
- all 115 deterministic red-team probes;
- wheel and source-archive build;
- clean wheel installation;
- `pip check`;
- installed deterministic command smoke test;
- installed `bella doctor --json` smoke test.

Live Ollama and physical-device testing remain explicit deployment steps rather
than simulated CI claims.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [SECURITY.md](SECURITY.md)
- [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md)
- [docs/MIND_TRACE_MEMORY.md](docs/MIND_TRACE_MEMORY.md)
- [docs/BELLA_OPERATOR.md](docs/BELLA_OPERATOR.md)
- [docs/ACTION_GATE.md](docs/ACTION_GATE.md)
- [docs/BELLA_EVALUATION_GATE.md](docs/BELLA_EVALUATION_GATE.md)
- [docs/BELLA_TUNING_LOOP.md](docs/BELLA_TUNING_LOOP.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CLAUDE.md](CLAUDE.md)
