# bella-harness

A deterministic-first agent safety harness. A rule-based gate classifies
every request *before* any LLM is involved -- blocking known attack patterns
outright, answering trivial requests directly, and deferring everything else
to a configured LLM backend.

Red team score: **115/115 clean** across 39 specialist attack categories,
zero breaches, zero false positives, verified deterministically in CI on
every PR (no live model required).

## Why deterministic-first

Relying solely on an LLM's own alignment training to refuse attacks means
every request pays the latency/cost of a model call, and safety is only as
good as that one model's training. bella-harness puts fast, auditable,
zero-inference boundaries around the model:

- **Blocks** known attack patterns before any memory or model access.
- **Answers directly** for greetings and arithmetic with no model call.
- **Recalls approved memory only after the gate defers**, so blocked requests
  never touch Mind Trace and memory remains evidence, not authority.
- **Applies Bella Operator outside the model**, giving every backend the same
  identity, mode, risk, accessibility, uncertainty, and approval rules.
- **Defers** legitimate requests to the configured LLM backend.
- **Scans the model's output** and withholds leaked credentials or system-prompt
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
- memory cannot authorize email, deletion, payment, publishing, scheduling,
  account changes, device control, or any other external action;
- malformed configured stores fail closed by default;
- irrelevant or empty recall leaves the original request unchanged.

With `memory.store_path: null` the harness uses an empty store. See
[docs/MIND_TRACE_MEMORY.md](docs/MIND_TRACE_MEMORY.md).

## Bella Operator

Bella Operator is the model-independent assistant layer inside the harness.
The shipped configuration enables it before backend generation and after the
input gate has deferred the request.

It provides:

- the fixed `bella-core-v1` identity;
- Default, Life, Home, Business, Technical, Care, Developer, Customer, and
  Quiet modes;
- deterministic Low, Medium, High, and Critical consequence classification;
- visible plans for consequential requests;
- explicit current-approval requirements for High and Critical requests;
- accessibility and uncertainty rules;
- a hard rule that plans and memories are not execution authority;
- a hard rule that completed-action claims require verified tool results.

Operator metadata is returned by `bella ask --json`, including the active mode,
risk level, approval requirement, reasons, and visible plan. See
[docs/BELLA_OPERATOR.md](docs/BELLA_OPERATOR.md).

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

- [ARCHITECTURE.md](ARCHITECTURE.md) -- complete request flow and boundaries.
- [docs/MIND_TRACE_MEMORY.md](docs/MIND_TRACE_MEMORY.md) -- approved-memory
  format and security invariants.
- [docs/BELLA_OPERATOR.md](docs/BELLA_OPERATOR.md) -- identity, modes, risk,
  approval, and completion-claim rules.
- [CONTRIBUTING.md](CONTRIBUTING.md) -- adding a rule, backend, or probe.
- [CLAUDE.md](CLAUDE.md) -- handoff notes for Claude Code.
