# CLAUDE.md

Handoff notes for working on bella-harness in this repo.

## Commands

```bash
pip install -r requirements.txt
python -m pytest -q                                          # unit tests
PYTHONPATH=src:. python -m bella_harness.cli redteam          # red-team suite
PYTHONPATH=src python -m bella_harness.cli ask "<prompt>"     # single request
```

`src/` is a src-layout package (`bella_harness`); `redteam/` is a sibling
top-level package at the repo root, not under `src/`. Both need to be on
`PYTHONPATH` when running the CLI directly outside pytest (pytest picks up
`pythonpath = ["src"]` from `pyproject.toml` and finds `redteam/` via cwd
automatically).

## Invariant to protect

The red-team suite (115 probes, 39 specialist agents,
`redteam/runner.py::run_suite`) must always finish at **0 breaches, 0 false
positives**. It scores against `BellaHarness.deterministic_engine` directly
(no live model needed) specifically so this is checkable in CI with no
secrets. If you touch `deterministic/rules.py` or `deterministic/engine.py`,
rerun it before committing:

```bash
PYTHONPATH=src:. python -m bella_harness.cli redteam
```

A regression here means either a rule got too narrow (breach) or too broad
(false positive on a benign probe) -- both are real bugs, not test
flakiness.

## Layout

```
src/bella_harness/
  config.py              YAML + env var config loader
  deterministic/
    rules.py             regex Rule definitions, BLOCK_RULES list
    engine.py            normalization/decoding pipeline + DeterministicEngine
  backends/
    base.py              Backend ABC, BackendError, BackendResponse
    ollama_backend.py, openai_backend.py, anthropic_backend.py, openrouter_backend.py
    __init__.py           BackendAbstraction (build + fallback)
  harness.py              BellaHarness orchestrator
  cli.py                  click CLI (ask, redteam)
redteam/
  probes/                 Probe definitions, one file per theme
  runner.py               run_suite() scoring logic
tests/                    pytest, mocks httpx for backend tests
config/default.yaml       default config (no secrets)
```

## Known scope boundary

The deterministic engine is a mechanical/regex layer (keyword matching,
encoding detection, unicode normalization). It is not designed to catch
fully semantic multi-step attacks with no shared substring across the
message -- that's intentionally left to the LLM backend's own alignment
training. See "Known limitation" in ARCHITECTURE.md before trying to make
the regex engine "smarter" at semantic understanding; that's the wrong
layer for it.
