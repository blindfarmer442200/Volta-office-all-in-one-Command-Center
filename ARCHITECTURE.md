# Architecture

## Request flow

```text
request text
     │
     ▼
DeterministicEngine.evaluate()
     │
     ├─ BLOCK ───────────────────────► refusal returned; memory and LLM untouched
     │
     ├─ ALLOW_DETERMINISTIC ─────────► canned/computed response; memory untouched
     │
     └─ DEFER_TO_LLM
             │
             ▼
       Mind Trace recall
             │
             ├─ unavailable + fail_closed ─► BLOCK
             │
             ├─ no relevant approved memory ─► original request unchanged
             │
             └─ approved/current/safe memory ─► bounded JSON context envelope
                                                     │
                                                     ▼
                                      BackendAbstraction.generate()
                                                     │
                                                     ├─ backend succeeds ─► scan_output()
                                                     │        ├─ clean → response returned
                                                     │        └─ leak  → BLOCK
                                                     │
                                                     └─ all backends fail ─► fail_closed:
                                                          true  → BLOCK
                                                          false → exception propagates
```

`BellaHarness` (`src/bella_harness/harness.py`) remains the only entry point.
It never reads memory or calls a backend unless the deterministic engine defers.

## Mind Trace memory boundary

`src/bella_harness/memory/` provides a read-only, deterministic memory seam:

- `models.py` validates bounded records, statuses, confidence, timestamps,
  privacy, tags, and supersession references.
- `store.py` provides an empty store, an in-memory test/embedding store, and a
  strict JSONL reader with file-size, record-count, duplicate-ID, UTF-8, and
  schema checks.
- `recall.py` filters before ranking. Only approved, current,
  non-superseded records are eligible. Customer mode excludes private records.
- `context.py` creates a bounded JSON envelope that explicitly labels memory as
  untrusted reference data and states that memory never grants action authority.
- `service.py` is the facade used by `BellaHarness`.

Memory content is checked by the same deterministic input engine before it can
enter a model prompt. Instruction-like or attack-like records are excluded and
surfaced through `excluded_unsafe_memory_ids`. A configured store that cannot
be verified fails closed by default. If fail-open is explicitly selected, the
harness sends the original request with no partial memory.

This layer does not approve, edit, delete, or autonomously write memories. It
also does not authorize connectors or external actions. Those are separate
future capabilities with separate permission gates.

## Output scanning

The harness guards the reply as well as the request. When a deferred request
comes back from a backend, `DeterministicEngine.scan_output()` re-checks the
response and the harness withholds it (returning a safe message) if it contains
a leaked credential/private key or the configured system-prompt canary. This is
deliberately narrow — concrete exfiltration, not a general "is this harmful"
judgement, which remains the model's own alignment job. Controlled by
`harness.output_scanning` in config (`enabled`, `canary`); on by default.

## DeterministicEngine

`src/bella_harness/deterministic/engine.py` + `rules.py`.

A pipeline of pure-Python transforms and regex rules, no model inference:

1. **Normalize.** NFKC-fold the text and strip zero-width characters.
2. **Build scan variants.** In addition to the normalized text, the engine
   builds several alternate views and scans all of them against the same
   rule set:
   - Cyrillic-confusable folding (`а`, `е`, `о`, ... → `a`, `e`, `o`, ...).
   - Leetspeak normalization (`1gn0r3` → `ignore`).
   - Letter-spacing collapse (`i g n o r e` / `i.g.n.o.r.e` → `ignore`).
   - Word-fragment collapse (`ig-nore` → `ignore`).
   - Markdown-emphasis stripping (`**ig**nore` → `ignore`).
   - Base64 / hex substring decoding.
   - ROT13 of the whole message.
3. **Match BLOCK_RULES.** Each rule is a named regex covering one technique
   family. Any match on any variant → `BLOCK`.
4. **Match deterministic-answerable shapes.** Greetings and simple arithmetic
   → `ALLOW_DETERMINISTIC` with a computed response.
5. Otherwise → `DEFER_TO_LLM`.

**Known limitation:** this is a mechanical/regex layer. It reliably catches
keyword-level and encoding-level obfuscation, not fully semantic multi-step
attacks. That remains an intentional scope boundary.

## BackendAbstraction

`src/bella_harness/backends/`. One `Backend` interface
(`generate(prompt, **kwargs) -> BackendResponse`, raising `BackendError` on
failure) is implemented by `OllamaBackend`, `OpenAIBackend`,
`AnthropicBackend`, and `OpenRouterBackend`.

`BackendAbstraction` builds every backend with `enabled: true` in config,
orders the configured `default_backend` first, and falls back through the
rest in config order if a call raises `BackendError`.

## Config

`src/bella_harness/config.py` + `config/default.yaml`. YAML on disk is
overridden by `BELLA__SECTION__KEY=value` environment variables. Literal
secrets are rejected; credentials come only from named environment variables.

The `memory` section controls the read-only Mind Trace seam. A null
`store_path` uses an empty store and preserves existing behavior.

## Red-team suite

`redteam/`. `redteam/probes/` defines 115 `Probe` objects across 39 specialist
agents. The runner scores the deterministic engine directly, so the suite runs
offline with no API keys or local model required.

- A `block` probe passes if the engine's decision is `BLOCK`.
- An `allow` probe passes if the engine's decision is not `BLOCK`.

`.github/workflows/redteam.yml` runs `pytest` and the red-team suite on every
push and pull request.
