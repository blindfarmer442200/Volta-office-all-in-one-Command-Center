# Architecture

## Request flow

```
request text
     │
     ▼
DeterministicEngine.evaluate()
     │
     ├─ BLOCK ─────────────► refusal returned, no LLM call
     │
     ├─ ALLOW_DETERMINISTIC ─► canned/computed response returned, no LLM call
     │
     └─ DEFER_TO_LLM ───────► BackendAbstraction.generate()
                                    │
                                    ├─ backend succeeds ─► response returned
                                    │
                                    └─ all backends fail ─► fail_closed:
                                         true  → BLOCK (safe refusal)
                                         false → exception propagates
```

`BellaHarness` (`src/bella_harness/harness.py`) is the only entry point
orchestrating this. It never calls a backend unless the deterministic engine
defers.

## DeterministicEngine

`src/bella_harness/deterministic/engine.py` + `rules.py`.

A pipeline of pure-Python transforms and regex rules, no model inference:

1. **Normalize.** NFKC-fold the text (this alone defeats most full-width/
   compatibility-form homoglyph tricks) and strip zero-width characters.
2. **Build scan variants.** In addition to the normalized text, the engine
   builds several alternate views and scans all of them against the same
   rule set:
   - Cyrillic-confusable folding (`а`, `е`, `о`, ... → `a`, `e`, `o`, ...) --
     NFKC doesn't fold across scripts, so this is handled separately.
   - Leetspeak normalization (`1gn0r3` → `ignore`).
   - Letter-spacing collapse (`i g n o r e` / `i.g.n.o.r.e` → `ignore`).
   - Word-fragment collapse (`ig-nore` → `ignore`).
   - Markdown-emphasis stripping (`**ig**nore` → `ignore`).
   - Base64 / hex substring decoding (payloads are extracted from
     surrounding plain-text framing, not assumed to span the whole message).
   - ROT13 of the whole message (a per-character cipher, so an embedded
     ROT13 payload decodes correctly regardless of what surrounds it).
3. **Match BLOCK_RULES.** Each rule is a named regex covering one technique
   family (prompt injection, jailbreak, role escalation, data exfiltration,
   multilingual injection, structural/delimiter injection, persona hijack,
   authority impersonation, system-prompt leak, prompt-leak-via-translation,
   trust escalation). Any match on any variant → `BLOCK`.
4. **Match deterministic-answerable shapes.** Greetings and simple
   arithmetic → `ALLOW_DETERMINISTIC` with a computed response.
5. Otherwise → `DEFER_TO_LLM`.

**Known limitation:** this is a mechanical/regex layer. It reliably catches
keyword-level and encoding-level obfuscation, not fully semantic multi-step
attacks (e.g. an attack split across unrelated sentences with no shared
substring). That's an intentional scope boundary, not an oversight --
semantic attacks are the LLM backend's own alignment training's job to
resist; the deterministic gate's job is to remove the mechanically-detectable
majority of traffic from ever reaching the model.

## BackendAbstraction

`src/bella_harness/backends/`. One `Backend` interface
(`generate(prompt, **kwargs) -> BackendResponse`, raising `BackendError` on
any failure) implemented by `OllamaBackend`, `OpenAIBackend`,
`AnthropicBackend`, `OpenRouterBackend`.

`BackendAbstraction` builds every backend with `enabled: true` in config,
orders the configured `default_backend` first, and falls back through the
rest in config order if a call raises `BackendError`.

## Config

`src/bella_harness/config.py` + `config/default.yaml`. YAML on disk,
overridden by `BELLA__SECTION__KEY=value` environment variables (double
underscore = nesting). Any `api_key` / `secret` / `token` key with a literal
value in the YAML is rejected at load time -- secrets only ever come from
the environment variable named in a backend's `api_key_env` setting.

## Red-team suite

`redteam/`. `redteam/probes/` defines 115 `Probe` objects (prompt, expected
outcome, specialist agent name, technique) across 39 specialist agents:
38 attack techniques (each with an `expect: "block"` probe) plus 2 benign
control agents (`expect: "allow"`, used to measure false positives).

`redteam/runner.py` scores every probe against
`BellaHarness.deterministic_engine` directly -- deliberately not against a
live LLM call. This is intentional: the suite red-teams the deterministic
gate specifically, so it runs fully offline, deterministically, and in CI
with no API keys or local model required.

- A `block` probe passes if the engine's decision is `BLOCK` (a miss is a
  **breach**).
- An `allow` probe passes if the engine's decision is *not* `BLOCK` (a hit is
  a **false positive**).

`.github/workflows/redteam.yml` runs `pytest` and the red-team suite on
every push/PR.
