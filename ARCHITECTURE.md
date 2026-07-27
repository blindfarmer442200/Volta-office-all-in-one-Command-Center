# Architecture

Bella Harness is deterministic-first. Models generate language, but deterministic
code owns input blocking, memory eligibility, identity policy, consequence risk,
action authorization, output scanning, evaluation, tuning history, network
egress, and release acceptance.

## Response flow

```text
request text
     |
     v
DeterministicEngine.evaluate()
     |
     |-- BLOCK ----------------------> refusal; operator, memory, model untouched
     |-- ALLOW_DETERMINISTIC --------> direct answer; operator, memory untouched
     `-- DEFER_TO_LLM
             |
             v
       BellaOperator.decide()
         - validate mode
         - classify consequence risk
         - set approval metadata
         - create visible non-executing plan
             |
             v
       Mind Trace recall
         - approved/current only
         - Customer-mode privacy
         - unsafe memory excluded
             |
             v
       bella.operator.v1 envelope
         - fixed identity and mode rules
         - risk and approval metadata
         - memory is evidence, not authority
         - plan is not execution
             |
             v
       BackendAbstraction.generate()
         - default route first
         - local-to-cloud fallback blocked unless explicitly enabled
             |
             v
       DeterministicEngine.scan_output()
```

`BellaHarness.handle()` never executes actions and never writes tuning data. It
returns a response plus visible memory and operator metadata. Human review is a
separate explicit workflow.

## Cloud-egress boundary

Bella supports Ollama, OpenAI, Anthropic, and OpenRouter, but enabling a cloud
backend does not authorize automatic transmission.

With the shipped configuration:

```yaml
harness:
  default_backend: ollama
  allow_cloud_fallback: false
```

an unpinned request uses eligible local backends only. If Ollama fails, the
request fails closed rather than sending the full prompt or approved memory to a
cloud provider.

Automatic local-to-cloud fallback requires a second explicit consent setting:

```yaml
harness:
  allow_cloud_fallback: true
```

A library caller may explicitly pin a specifically enabled cloud backend. A
cloud backend configured as the default is also an explicit cloud route. Pinned
backend failures do not cascade.

Ollama itself accepts only `localhost` or a literal loopback/private IP address.
Public IPs, arbitrary DNS hosts, embedded credentials, path prefixes, queries,
fragments, redirects, malformed JSON, invalid UTF-8, and oversized prompts or
responses fail closed.

See `docs/CLOUD_EGRESS.md`.

## Action flow

Consequential operations use a separate API from ordinary responses:

```text
BellaHarness.prepare_action(request, exact ActionSpec)
     |
     v
DeterministicEngine.evaluate()
     |-- BLOCK ----------------------> no preview
     |-- ALLOW_DETERMINISTIC --------> cannot become an action
     `-- DEFER_TO_LLM
             |
             v
       BellaOperator.decide()
         - High or Critical
         - approval_required=true
         - risk meets action-kind floor
             |
             v
       ActionGate.prepare()
         - mock_action_sandbox only
         - canonical JSON
         - SHA-256 fingerprint
         - exact target and payload
         - bounded preview lifetime
             |
             v
       explicit owner confirmation
             |
             v
       ActionGate.authorize()
         - reviewed fingerprint required
         - random short-lived one-use capability
         - only capability hash retained
             |
             v
       ActionGate.execute_sandbox()
         - fingerprint rechecked
         - changed payload rejected
         - capability consumed before result
         - simulated=true
         - sideEffectsPerformed=false
```

The response path cannot call Action Gate. Action Gate cannot call a real
connector in the current production scope. `owner_confirmed=true` is an API
assertion, not biometric identity proof.

## Model acceptance flow

Candidate models use a third independent path:

```text
18 fixed synthetic scenarios
     |
     v
BellaOperator.decide()
     |
     v
bella.operator.v1 envelope
     |
     v
one pinned Ollama model
  - temperature 0
  - no cloud fallback
  - no tools
  - no personal memory
     |
     v
strict bella.evaluation-response.v1 JSON
     |
     v
deterministic scenario checks
     |
     |-- any failure ----------------> rejected; nonzero exit
     `-- 18/18 pass -----------------> hashed acceptance report
```

Passing records that the exact model tag met the current suite. It never
activates the model or grants memory, connector, or action authority.

## Human correction and tuning flow

```text
human selects one visible completed interaction
     |
     v
review-response
  - stable interaction id
  - visible prompt and original response
  - controlled human rating
  - optional exact human replacement
  - no hidden Mind Trace packet
  - no credential or capability capture
     |
     v
SQLiteTuningStore
  - immutable content hashes
  - append-only feedback
  - versioned corrections
  - one active correction
  - hash-chained audit
     |
     v
verify-tuning
  - SQLite integrity
  - content hashes
  - correction uniqueness
  - audit sequence and links
     |
     v
export-tuning
  - redacted by default
  - atomic local files
  - file SHA-256 values
  - dataset digest
     |
     +--> sft.jsonl
     +--> preference.jsonl
     +--> evaluation-only.jsonl
     +--> regression.jsonl
     `--> manifest.json
```

Export never uploads data, starts training, or activates a model. Human-derived
regression records are review references, not forced exact-string tests.

## Component boundaries

### Deterministic engine

`src/bella_harness/deterministic/` normalizes Unicode and scans confusables,
leetspeak, spacing, fragments, Markdown, Base64, hex, and ROT13 variants before
applying blocking and direct-answer rules.

### Bella Operator

`src/bella_harness/operator/` owns:

- `bella-core-v1` identity;
- nine operating modes;
- Low, Medium, High, and Critical consequence levels;
- visible plans and current approval metadata;
- accessibility and uncertainty directives;
- the rule that memory and plans are not execution authority;
- the rule that completed-action claims require verified tool results.

### Mind Trace

`src/bella_harness/memory/` provides bounded, read-only recall:

- strict records and JSONL validation;
- approved/current filtering;
- superseded and expired exclusion;
- Customer-mode private-memory exclusion;
- stored prompt-injection screening;
- bounded JSON context.

Memory does not approve, write, delete, or execute.

### Action Gate

`src/bella_harness/action_gate/` owns canonical action fingerprints, previews,
one-use authorization, expiry, revocation, replay protection, risk floors, and a
hash-chained audit. Only `mock_action_sandbox` is accepted.

### Evaluation Gate

`src/bella_harness/evaluation/` owns the fixed scenario catalog, strict candidate
response contract, deterministic checks, all-or-nothing acceptance, and hashed
reports. Evaluation is pinned to Ollama with no memory, tools, or fallback.

### Tuning loop

`src/bella_harness/tuning/` owns bounded interactions, ratings, corrections,
SQLite history, deterministic redaction, atomic JSONL exports, and audit-chain
verification. Normal `bella ask` requests never create tuning records.

### Production doctor

`src/bella_harness/doctor.py` checks packaged configuration, fail-closed policy,
output scanning, Operator, Action Gate bounds, Evaluation Gate policy, disabled
automatic tuning, configured store integrity, backend configuration, private
Ollama transport, and optional prompt-free live Ollama health.

Doctor output contains status metadata, not prompt text, private memory,
corrections, credentials, or capabilities.

## Configuration

`config/default.yaml` and the byte-identical packaged `default.yaml` support
`BELLA__SECTION__KEY=value` environment overrides and reject literal secrets.

- `harness` controls default routing, cloud-fallback consent, fail-closed policy,
  and output scanning.
- `memory` controls Mind Trace storage and recall bounds.
- `operator` enables the model-independent Bella layer.
- `action_gate` controls mock preview and authorization lifetimes.
- `evaluation` pins local Ollama acceptance and candidate model tag.
- `tuning` controls explicit local review storage; automatic capture, upload,
  training, and activation remain false.
- `backends` configures enabled providers and transport bounds.

## Release-evidence flow

```text
source commit
     |
     v
Python 3.10 + 3.12 compatibility
     |
     v
compile + dependency audit
     |
     v
unit baseline + 115 red-team probes
     |
     v
wheel + source archive
     |
     v
twine metadata + sdist content validation
     |
     v
clean wheel install + pip check + installed doctor
     |
     v
release-manifest.json + SHA256SUMS
     |
     v
tag/version/main-branch validation
     |
     v
GitHub release assets
```

`src/bella_harness/release_manifest.py` requires:

- a 40-character commit SHA;
- at least 207 passing unit tests;
- at least 115 passing red-team probes;
- successful dependency audit, distribution validation, and wheel smoke test;
- a ready doctor report whose installed version matches `pyproject.toml`;
- exactly one version-matched wheel and one source archive;
- verified artifact hashes.

The tag-driven workflow accepts only `v<project-version>` tags whose commit is
contained in `main` and whose notes file exists at `docs/releases/<tag>.md`.
Manual release-workflow runs build evidence but do not publish.

## Verification boundary

CI proves source compilation, Python 3.10/3.12 behavior, dependency audit,
unit/red-team baselines, package metadata, source-archive contents, clean wheel
installation, installed doctor readiness, and release-manifest integrity.

CI does not claim:

- a real local model has passed on the final host;
- physical Android/iPhone behavior;
- final screen-reader or voice quality;
- long-running host stability and performance;
- successful backup restoration on the operator's storage;
- safety of real connectors, because real connectors are intentionally absent.

See `docs/PRODUCTION_READINESS.md` and `docs/RELEASE_PROCESS.md`.
