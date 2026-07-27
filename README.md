# bella-harness

A deterministic-first agent safety harness. A rule-based gate classifies
every request *before* any LLM is involved -- blocking known attack patterns,
answering trivial requests directly, and deferring legitimate requests to a
configured backend.

Red team score: **115/115 clean** across 39 specialist attack categories,
zero breaches, zero false positives, verified deterministically in CI on
every PR (no live model required).

## Why deterministic-first

bella-harness puts fast, auditable, zero-inference boundaries around the model:

- **Blocks** known attack patterns before memory or model access.
- **Answers directly** for greetings and arithmetic with no model call.
- **Recalls approved memory only after the gate defers**, so blocked requests
  never touch Mind Trace and memory remains evidence, not authority.
- **Applies Bella Operator outside the model**, giving every backend the same
  identity, mode, risk, accessibility, uncertainty, and approval rules.
- **Separates plans from actions** through an exact, expiring, one-use Action
  Gate limited to a local side-effect-free sandbox.
- **Rejects unproven candidate models** through an Ollama-only, all-or-nothing
  18-scenario Bella Evaluation Gate.
- **Defers** legitimate response generation to the configured LLM backend.
- **Scans model output** and withholds leaked credentials or system-prompt
  canaries before the response reaches the user.

## Quickstart

```bash
pip install -r requirements.txt

# Deterministic responses -- no backend required
PYTHONPATH=src python -m bella_harness.cli ask "hello"
PYTHONPATH=src python -m bella_harness.cli ask "2 + 2"

# Free-form requests use Ollama or another configured backend
PYTHONPATH=src python -m bella_harness.cli ask \
  --mode business \
  --json \
  "Draft an email to the customer"

# Exact action preview -- local mock only, no side effects
PYTHONPATH=src python -m bella_harness.cli sandbox-action \
  "Send an email to the customer" \
  --kind send_message \
  --target customer@example.com \
  --payload '{"subject":"Invoice","body":"Invoice 1042 is overdue."}' \
  --mode business

# Evaluate one pinned local Ollama model. Exit code is nonzero unless all 18 pass.
PYTHONPATH=src python -m bella_harness.cli evaluate-bella \
  --model qwen3.5 \
  --report bella-evaluation-report.json

# Run the red-team suite fully offline
PYTHONPATH=src:. python -m bella_harness.cli redteam
```

## Mind Trace memory

Mind Trace is the bounded, human-governed memory seam inside the harness. It is
reached only after the deterministic input gate returns `DEFER_TO_LLM`.
Blocked requests and direct deterministic answers never read memory.

The first integration is deliberately read-only:

- only approved, current, non-superseded records can reach a model;
- private records are excluded in Customer mode;
- instruction-like memory is rejected by the deterministic gate;
- memory is labeled as untrusted JSON data, never instructions;
- memory cannot authorize external actions;
- malformed configured stores fail closed by default;
- irrelevant or empty recall leaves the original request unchanged.

See [docs/MIND_TRACE_MEMORY.md](docs/MIND_TRACE_MEMORY.md).

## Bella Operator

Bella Operator is the model-independent assistant layer inside the harness. It
provides:

- the fixed `bella-core-v1` identity;
- Default, Life, Home, Business, Technical, Care, Developer, Customer, and
  Quiet modes;
- deterministic Low, Medium, High, and Critical consequence classification;
- visible plans for consequential requests;
- explicit current-approval requirements for High and Critical requests;
- accessibility and uncertainty rules;
- hard rules that plans and memories are not execution authority;
- a hard rule that completed-action claims require verified tool results.

Operator metadata is returned by `bella ask --json`. See
[docs/BELLA_OPERATOR.md](docs/BELLA_OPERATOR.md).

## Bella Action Gate

Action Gate is a separate API from ordinary chat responses. It binds an exact
connector, kind, target, and JSON payload to a SHA-256 fingerprint, then requires
explicit confirmation before issuing a short-lived one-use capability.

Current guarantees:

- only `mock_action_sandbox` is accepted;
- previews expire in at most 15 minutes;
- authorizations expire in at most 5 minutes;
- only a capability hash is retained;
- changed payloads and replayed capabilities fail closed;
- High requests cannot authorize Critical action kinds;
- an append-only hash chain records preview, authorization, expiration,
  revocation, and mock execution;
- every successful execution records `simulated=true` and
  `sideEffectsPerformed=false`.

The CLI proof can preview or, with `--confirm`, consume the capability inside
the mock sandbox. It never displays the raw capability and cannot contact an
outside service. See [docs/ACTION_GATE.md](docs/ACTION_GATE.md).

## Bella Evaluation Gate

The Evaluation Gate tests one exact local Ollama model against 18 mandatory,
synthetic behavior scenarios before the model may be considered a Bella
candidate. The suite covers:

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

The model must return a strict JSON response contract. The gate uses Bella's
real operator envelope, sends no personal memory or real credentials, never
falls back to cloud, never activates a model automatically, and never grants
permissions. A score of 17/18 still fails. The resulting JSON report is bound
to its model, profile, results, counts, acceptance state, and SHA-256 digest.

See [docs/BELLA_EVALUATION_GATE.md](docs/BELLA_EVALUATION_GATE.md).

## Backends

One interface (`BackendAbstraction`) covers four backends configured in
`config/default.yaml`:

| Backend | Default model | Notes |
|---|---|---|
| Ollama | `qwen3.5` | Local-first, no API key required |
| OpenAI | `gpt-4o-mini` | `OPENAI_API_KEY` |
| Anthropic | `claude-3-5-sonnet-latest` | `ANTHROPIC_API_KEY` |
| OpenRouter | `meta-llama/llama-3.1-70b-instruct` | `OPENROUTER_API_KEY` |

The default Ollama model is Qwen 3.5. Pull it locally with
`ollama pull qwen3.5`, start Ollama, or override the tag with
`BELLA__BACKENDS__OLLAMA__MODEL=<tag>`.

API keys are only read from environment variables named by each backend's
`api_key_env` setting. A literal secret in configuration is a hard error.

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) -- complete request, action, and model
  acceptance flows.
- [docs/MIND_TRACE_MEMORY.md](docs/MIND_TRACE_MEMORY.md) -- approved-memory
  format and security invariants.
- [docs/BELLA_OPERATOR.md](docs/BELLA_OPERATOR.md) -- identity, modes, risk,
  approval, and completion-claim rules.
- [docs/ACTION_GATE.md](docs/ACTION_GATE.md) -- exact preview, authorization,
  replay protection, sandbox execution, and future connector requirements.
- [docs/BELLA_EVALUATION_GATE.md](docs/BELLA_EVALUATION_GATE.md) -- mandatory
  behavior scenarios, report integrity, and local model acceptance.
- [CONTRIBUTING.md](CONTRIBUTING.md) -- adding a rule, backend, or probe.
- [CLAUDE.md](CLAUDE.md) -- handoff notes for Claude Code.
