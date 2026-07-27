# Bella Production Readiness

This document defines the production boundary for `bella-harness` 0.2.x.

## Current production scope

The harness is intended to be production-ready for these bounded functions:

- deterministic request blocking and direct answers;
- governed read-only Mind Trace memory recall;
- Bella identity, mode, risk, and approval policy;
- model output scanning;
- local/private Ollama response generation;
- all-or-nothing Bella model evaluation;
- explicit human correction and local tuning-data export;
- exact Action Gate preview and authorization in the side-effect-free mock sandbox.

It is **not** production-ready for real email, calendar, payment, file, account,
smart-home, or device-control execution. Those connectors do not exist in the
current production scope.

## Installation gate

Build and install the package rather than running an untracked source directory:

```bash
python -m pip install --upgrade pip build
python -m build
python -m venv .venv
. .venv/bin/activate
python -m pip install dist/*.whl
python -m pip check
```

Windows PowerShell activation:

```powershell
.venv\Scripts\Activate.ps1
```

The wheel contains Bella's default configuration. CI rejects a package that
cannot run deterministic commands or the production doctor after clean install.

## Host readiness gate

Run the offline checks first:

```bash
bella doctor
```

Then start Ollama and run the prompt-free live check:

```bash
bella doctor --live
```

Deployment is blocked when any critical doctor check fails. Warnings for an
unconfigured memory or tuning store are acceptable only when the deployment
intentionally runs without those features.

The doctor checks:

- packaged configuration availability;
- fail-closed behavior;
- output scanning;
- Bella Operator enablement;
- Action Gate lifetime bounds;
- all-or-nothing Ollama evaluation policy;
- disabled automatic capture, upload, training, and activation;
- configured Mind Trace store validity;
- configured tuning-store integrity and audit chain;
- default backend enablement;
- local/private Ollama endpoint enforcement;
- optional prompt-free Ollama health.

Doctor output reports safe status metadata only. It does not print prompt text,
private memory contents, tuning responses, credentials, or capabilities.

## Ollama network boundary

The Ollama adapter accepts only:

- `localhost`;
- literal loopback IP addresses;
- literal private or link-local IP addresses.

It rejects:

- public IP addresses;
- arbitrary DNS hostnames;
- credentials embedded in URLs;
- URL path prefixes, queries, and fragments;
- redirects;
- invalid localhost resolution;
- oversized prompts or responses;
- malformed JSON or UTF-8;
- missing response text;
- invalid model tags and temperatures.

Use a VPN or private network address when Ollama runs on another trusted host.
Do not expose Ollama directly to the public internet.

## Required release gates

Every release candidate must pass:

1. Python 3.10 unit tests.
2. Python 3.12 unit tests.
3. All 115 deterministic red-team probes.
4. Wheel and source-archive build.
5. Clean wheel installation in a new virtual environment.
6. `pip check` with no broken dependencies.
7. Installed `bella ask "hello"` smoke test.
8. Installed `bella doctor --json` with `ready=true` offline.
9. File and package-data synchronization tests.
10. Exact release commit and artifact hashes recorded.

Before deploying a selected local model, also require:

```bash
bella evaluate-bella --model <exact-model-tag> --report bella-evaluation-report.json
```

The exact model must pass all 18 mandatory scenarios. Passing does not activate
or authorize the model automatically.

## Memory deployment

Configure a Mind Trace JSONL file only after validating its ownership and backup
policy:

```bash
export BELLA__MEMORY__STORE_PATH=/secure/path/mind-trace.jsonl
bella doctor
```

The configured store must be a regular UTF-8 file under the size and record
limits. A malformed configured store blocks model use when `memory.fail_closed`
is enabled.

## Tuning deployment

Normal conversations are not captured. Configure the SQLite store only when the
operator intends to collect explicit reviews:

```bash
export BELLA__TUNING__STORE_PATH=/secure/path/bella-tuning.sqlite3
bella doctor
bella verify-tuning
```

Keep redacted export as the default. An exact export requires `--exact` and must
remain in a trusted local environment.

## Backup and recovery

Back up these files when used:

- Mind Trace JSONL store;
- Bella tuning SQLite database, including WAL/SHM files during live backup;
- generated evaluation reports;
- tuning export manifests and JSONL datasets;
- deployment configuration supplied outside the package.

Use SQLite's online backup mechanism or stop writes before copying a tuning
store. A raw copy made while WAL data is active may be incomplete.

Test restoration on a separate machine or directory. A backup that has never
been restored is not a verified backup.

## Operational monitoring

At minimum, monitor:

- process exit status;
- backend failure rate and timeout count;
- output-scan blocks;
- memory-store verification failures;
- doctor failures;
- model-evaluation reports;
- tuning-store integrity failures;
- Action Gate preview, authorization, expiration, revocation, and replay events.

Do not log raw prompts, memory packets, credentials, one-use capabilities, or
unredacted tuning data into general application logs.

## Rollback

Keep the last accepted package wheel, configuration, model tag, and evaluation
report. Roll back when:

- doctor becomes critical-fail;
- red-team or regression results worsen;
- the active model no longer passes 18/18;
- memory or tuning integrity fails;
- output scanning detects unexpected leakage;
- response quality materially regresses.

Model rollback does not bypass the Evaluation Gate. The restored model tag must
have its own matching accepted report.

## Remaining external validation

Repository CI cannot prove:

- physical Android or iPhone behavior;
- long-running Ollama stability on the deployment host;
- accessibility quality with a real screen reader and voice workflow;
- performance under the final hardware and network load;
- backup restoration on the operator's real storage;
- real connector safety, because real connectors are intentionally absent.

Complete those tests on the target host before calling that specific deployment
production-ready. The code package may pass its release gates while a particular
machine, model, network, or accessibility setup still fails deployment readiness.
