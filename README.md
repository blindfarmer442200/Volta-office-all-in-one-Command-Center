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
good as that one model's training. bella-harness puts a fast, auditable,
zero-inference gate in front of the model:

- **Blocks** known attack patterns (prompt injection, jailbreaks, privilege
  escalation, data exfiltration, encoded/obfuscated payloads, translated
  injection attempts, and more) without ever calling an LLM.
- **Answers directly** for a slice of deterministic requests (greetings,
  arithmetic) with no model call at all.
- **Defers** everything else to an LLM backend, so the gate never becomes a
  bottleneck for legitimate requests it can't confidently classify.
- **Scans the model's output** on the way back, withholding responses that
  leak credentials or the system prompt — so the harness guards both the
  request *and* the reply, not just the input.

## Quickstart

```bash
pip install -r requirements.txt

# Requests the deterministic engine resolves on its own -- no backend needed
PYTHONPATH=src python -m bella_harness.cli ask "hello"          # -> greeting
PYTHONPATH=src python -m bella_harness.cli ask "2 + 2"          # -> 4

# A free-form question defers to an LLM backend, so start Ollama first
# (see Backends below); without a reachable backend it fails closed.
PYTHONPATH=src python -m bella_harness.cli ask "What's the capital of France?"

# Run the red-team suite (fully offline, no backend or API keys)
PYTHONPATH=src:. python -m bella_harness.cli redteam
```

## Backends

One interface (`BackendAbstraction`) over four backends, configured in
`config/default.yaml`:

| Backend    | Default model            | Notes                                    |
|------------|--------------------------|-------------------------------------------|
| Ollama     | `qwen3.5`                | Local-first, no API key required (default) |
| OpenAI     | `gpt-4o-mini`            | `OPENAI_API_KEY`                          |
| Anthropic  | `claude-3-5-sonnet-latest` | `ANTHROPIC_API_KEY`                     |
| OpenRouter | `meta-llama/llama-3.1-70b-instruct` | `OPENROUTER_API_KEY`           |

The default Ollama model is Qwen 3.5. Pull it locally with
`ollama pull qwen3.5` (or point `backends.ollama.model` at whichever Qwen 3.5
tag you have), then start the Ollama server before deferring any request to
it. Override without editing config via
`BELLA__BACKENDS__OLLAMA__MODEL=<tag>`.

API keys are **only** ever read from environment variables named by each
backend's `api_key_env` setting -- a literal key in a config file is a hard
error at load time.

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) -- how the deterministic engine, backend
  abstraction, and red-team suite fit together.
- [CONTRIBUTING.md](CONTRIBUTING.md) -- how to add a rule, backend, or probe.
- [CLAUDE.md](CLAUDE.md) -- handoff notes for Claude Code.
