# Changelog

All notable changes to `bella-harness` are documented here.

## [Unreleased]

No unreleased changes.

## [0.2.0] - 2026-07-27

### Added

- Governed Mind Trace memory inside `BellaHarness`, with approved/current recall,
  Customer-mode privacy, superseded-memory exclusion, prompt-injection screening,
  and bounded context.
- Bella Operator with fixed `bella-core-v1` identity, nine operating modes,
  deterministic consequence risk, visible plans, approval metadata,
  accessibility rules, and false-completion prevention.
- Mock-only Action Gate with canonical payload hashing, expiring previews,
  one-use capabilities, replay rejection, mutation rejection, and hash-chained
  audit events.
- Ollama-only 18-scenario Bella Evaluation Gate with all-or-nothing acceptance,
  strict JSON responses, temperature-zero execution, report hashing, and no
  personal memory or tools.
- Durable human correction and tuning loop using SQLite, immutable feedback,
  versioned corrections, redacted-by-default SFT/preference/evaluation/regression
  exports, atomic files, and audit-chain verification.
- Installable `bella-harness` wheel, packaged default configuration,
  `python -m bella_harness`, and installed `bella` CLI.
- `bella doctor` and `bella doctor --live` production-readiness checks.
- Private Ollama transport enforcement, redirect rejection, strict JSON/UTF-8,
  and prompt/response/output limits.
- Explicit cloud-egress consent through `harness.allow_cloud_fallback`, disabled
  by default.
- Production runbook, cloud-egress policy, security policy, release manifest,
  SHA-256 checksums, dependency audit, distribution metadata validation, and
  clean-wheel smoke testing.

### Security

- Blocked input never reaches memory or a model.
- Memory remains untrusted evidence and cannot grant authority.
- Ordinary responses cannot execute actions.
- Real email, calendar, payment, file, account, smart-home, and device connectors
  remain unavailable.
- An Ollama failure cannot silently route prompts or memory to a cloud provider.
- Normal conversations are not automatically captured for tuning.
- Tuning exports remain local and redacted by default.

### Verification

- Python 3.10 and Python 3.12 CI.
- At least 207 unit tests required for release.
- 115/115 deterministic red-team probes required for release.
- Dependency vulnerability audit.
- Wheel and source-archive build.
- `twine check` distribution validation.
- Clean virtual-environment installation and `pip check`.
- Installed deterministic command and production doctor smoke tests.
- Release artifact manifest and SHA-256 verification.

### Known boundaries

- A real Ollama model still must pass the 18-scenario Evaluation Gate on the
  deployment host.
- Physical Android/iPhone behavior has not been validated by repository CI.
- Final screen-reader, voice, host-load, network, and backup-restoration tests
  remain deployment-specific.
- Action Gate remains a side-effect-free local sandbox only.

[Unreleased]: https://github.com/blindfarmer442200/Volta-office-all-in-one-Command-Center/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/blindfarmer442200/Volta-office-all-in-one-Command-Center/releases/tag/v0.2.0
