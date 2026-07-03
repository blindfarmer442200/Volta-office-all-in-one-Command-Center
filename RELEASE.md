# Release checkpoints

## Definition of "green"

A commit is **green** — a known-good baseline safe to build on — when all of
the following hold:

- **74/74 unit tests pass** (`python -m pytest -q`)
- **Red-team suite is 115/115 clean:** 0 breaches, 0 false positives
- **39 specialist agents covered** by the red-team probes
- **CI is green on Python 3.10 and 3.12**
- **Unit tests, red-team suite, and artifact upload all pass in CI**
- **Clean-clone install works** (fresh clone + `pip install -r requirements.txt`)
- **Config loads with no secrets in any file** (API keys only via `api_key_env`)
- **Env override works** (`BELLA__SECTION__KEY=value`, e.g. `BELLA__BACKENDS__OLLAMA__MODEL`)
- **Severity breakdown holds:** 67 critical / 28 high / 5 medium blocked attack probes

Reproduce locally:

```bash
pip install -r requirements.txt
python -m pytest -q                                   # 74 passed
PYTHONPATH=src:. python -m bella_harness.cli redteam  # 115/115 probes clean
```

---

## v0.1.0 — first known-good baseline

The first bella-harness release: a clean, green baseline meeting every
criterion above.

**Code baseline:** the harness (PR #1) plus the hardening pass (PR #2), whose
merge commit is `9ff1e97`. The `v0.1.0` tag is placed on the `main` commit that
also includes this `RELEASE.md` (PR #3), so the release checkpoint carries its
own definition of green.

**Why `v0.1.0` and not `v1.0.0`:** this is a strong, known-good baseline but
still the *first* harness release. `v1.0.0` is reserved for when the harness's
public API is stable, backend behavior is proven against real backends (not
just mocked), and the integration story is established. We are deliberately not
overselling this as a mature public release.

### What's in it

- **Deterministic engine:** 11 rule families (prompt injection, jailbreak, role
  escalation, data exfiltration, multilingual injection, structural injection,
  persona hijack, authority impersonation, system-prompt leak,
  prompt-leak-via-translation, trust escalation), with obfuscation
  preprocessing (NFKC + zero-width stripping, homoglyph folding, leetspeak,
  letter-spacing, word-fragment splitting, markdown-emphasis stripping, and
  base64/hex/ROT13 payload decoding).
- **BackendAbstraction:** unified interface over Ollama (default, `qwen3.5`),
  OpenAI, Anthropic, and OpenRouter, with default-first ordering, automatic
  fallback, and fail-closed behavior.
- **Config:** YAML plus `BELLA__…` env overrides; literal secrets in config
  files are rejected at load time.
- **Red-team suite:** 115 probes across 39 specialist agents, scored offline
  against the deterministic engine.
- **CI:** unit tests + red-team suite on every push/PR across Python 3.10 and
  3.12, with the red-team report uploaded as an artifact.
- **Hardening:** severity labels per rule family, a committed regression
  snapshot with a drift test, adversarially-benign false-positive tests, and
  expanded backend / fail-closed / secret-rejection coverage.
