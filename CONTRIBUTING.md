# Contributing

## Setup

```bash
pip install -r requirements.txt
python -m pytest -q
PYTHONPATH=src:. python -m bella_harness.cli redteam
```

Both must pass before opening a PR; CI (`.github/workflows/redteam.yml`) runs
both on every push and PR.

## Adding a detection rule

1. Add a `Rule(category=..., pattern=..., description=...)` to
   `src/bella_harness/deterministic/rules.py`, and append it to
   `BLOCK_RULES`.
2. Add at least one probe exercising it in the relevant file under
   `redteam/probes/` (or a new file, registered in
   `redteam/probes/__init__.py`).
3. Run the red-team suite -- it must stay at 0 breaches and 0 false
   positives. If a new rule causes a false positive on an existing benign
   probe, narrow the pattern rather than removing the benign probe.

## Adding a backend

1. Create `src/bella_harness/backends/<name>_backend.py` implementing
   `Backend` (see `base.py`) -- `generate()` must raise `BackendError` (not a
   transport-specific exception) on failure so `BackendAbstraction`'s
   fallback works uniformly.
2. Register the class in `BACKEND_CLASSES` in
   `src/bella_harness/backends/__init__.py`.
3. Add its config block to `config/default.yaml` (`enabled: false` by
   default) and an `api_key_env` if it needs a key -- never a literal
   `api_key`.
4. Add a mocked-`httpx` test in `tests/test_backends.py`.

## Adding a red-team probe

Probes live in `redteam/probes/*.py` as `Probe(id, agent, technique, prompt,
expect, description="")` entries, aggregated by
`redteam/probes/__init__.py`. `expect="block"` for attacks, `expect="allow"`
for benign controls. Keep probe IDs unique and prefixed per file (`INJ-`,
`JB-`, `ESC-`, `EXF-`, `ENC-`, `ML-`, `ADV-`, `BEN-`).

## Style

No hard style requirements beyond what's already in the codebase: type hints
on public functions, dataclasses for structured returns, no comments beyond
non-obvious "why" notes.
