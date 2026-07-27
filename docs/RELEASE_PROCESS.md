# Bella Harness Release Process

Releases are evidence-driven. A version number or Git tag does not override a
failed safety, privacy, package, or compatibility gate.

## 1. Prepare the release branch

- Merge only reviewed changes into `main`.
- Update `pyproject.toml` under `[project].version`.
- Update `CHANGELOG.md`.
- Add `docs/releases/v<version>.md`.
- Confirm repository and packaged `default.yaml` files are identical.
- Do not enable real connectors as part of a release-only change.

## 2. Pull-request gates

The normal CI workflow must pass on Python 3.10 and 3.12:

- source compilation;
- dependency audit with `pip-audit`;
- full unit suite;
- 115/115 deterministic red-team probes;
- wheel and source-archive build;
- `twine check`;
- clean wheel installation;
- `pip check`;
- installed deterministic command;
- installed production doctor;
- release manifest generation and verification.

The manifest refuses:

- fewer than 207 passing unit tests;
- fewer than 115 passing red-team probes;
- a failed dependency audit, distribution check, or wheel smoke test;
- a doctor report that is not ready;
- a doctor package version that differs from `pyproject.toml`;
- missing, extra, empty, or version-mismatched distribution files;
- invalid commit SHA metadata.

## 3. Verify the deployment-independent package

On `main`, run or confirm the CI artifact contains:

```text
dist/
├── bella_harness-<version>-py3-none-any.whl
└── bella_harness-<version>.tar.gz

SHA256SUMS
release-manifest.json
redteam-report.json
bella-doctor.json
```

The exact source-archive filename may use the normalized hyphen form generated
by the packaging backend.

## 4. Create the tag

The release workflow accepts only a canonical tag matching the project version:

```text
vMAJOR.MINOR.PATCH
```

For version `0.2.0`, the only accepted tag is `v0.2.0`.

The tag must point to a commit contained in `main`. A tag for an unmerged branch,
a mismatched version, or a release without `docs/releases/<tag>.md` fails before
publication.

## 5. Tag-driven publication

Pushing the tag starts `.github/workflows/release.yml`.

The workflow:

1. tests Python 3.10 and 3.12;
2. repeats the complete release build under Python 3.12;
3. confirms the tagged commit belongs to `main`;
4. verifies tag/version equality;
5. runs dependency audit, unit tests, and red team;
6. builds and checks distributions;
7. installs the wheel in a clean environment;
8. runs the installed production doctor;
9. generates and verifies checksums and release manifest;
10. uploads workflow evidence;
11. publishes a GitHub release with the verified assets and exact notes file.

A manual workflow run performs the build and uploads evidence but does not
publish a GitHub release.

## 6. Verify the published assets

After publication:

- confirm the release tag and displayed version match;
- download the wheel, source archive, `SHA256SUMS`, and manifest;
- verify the artifact hashes;
- confirm the manifest commit equals the tagged commit;
- install the wheel in a new environment;
- run `bella doctor`;
- archive the release evidence.

Do not publish to PyPI from this workflow. A future PyPI release requires a
separate trusted-publishing design, package-name confirmation, and explicit
operator approval.

## 7. Host deployment gates

A published package is not automatically ready for every machine. On the target
host:

```bash
bella doctor
bella doctor --live
bella evaluate-bella --model <exact-tag> --report bella-evaluation-report.json
```

Then complete:

- screen-reader and voice workflow testing;
- response-time and load testing;
- memory/tuning backup and restoration;
- network privacy verification;
- long-running Ollama stability;
- rollback rehearsal.

Real connectors remain blocked until their own authenticated, durable,
idempotent, rollback-capable integration gates exist.

## 8. Rollback

Retain the previous accepted wheel, source archive, model tag, configuration,
evaluation report, checksums, and manifest.

If a release regresses:

- stop deployment;
- restore the previous accepted package and model;
- rerun `bella doctor` and the exact model evaluation;
- open a focused fix branch;
- do not move or overwrite the existing release tag;
- publish a new patch version after all gates pass.
