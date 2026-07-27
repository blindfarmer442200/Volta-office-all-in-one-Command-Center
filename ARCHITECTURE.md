# Architecture

## Response flow

```text
request text
     |
     v
DeterministicEngine.evaluate()
     |
     |-- BLOCK --------------------------> refusal; operator, memory, LLM untouched
     |-- ALLOW_DETERMINISTIC ------------> direct answer; operator, memory untouched
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
       Bella operator envelope
         - fixed identity and mode rules
         - risk and approval metadata
         - memory is not authority
         - plan is not execution
             |
             v
       BackendAbstraction.generate()
             |
             v
       DeterministicEngine.scan_output()
```

`BellaHarness.handle()` never executes actions and never writes tuning data. It
returns a response plus visible memory and operator metadata. Saving a review is
a separate explicit workflow.

## Action flow

Consequential operations use a separate API:

```text
BellaHarness.prepare_action(request, exact ActionSpec)
     |
     v
DeterministicEngine.evaluate()
     |-- BLOCK --------------------------> no preview
     |-- ALLOW_DETERMINISTIC ------------> cannot become an action
     `-- DEFER_TO_LLM
             |
             v
       BellaOperator.decide()
         - High or Critical
         - approval_required=true
         - decision risk meets action-kind floor
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

The response path cannot call the Action Gate. Action Gate cannot call a real
connector in this release.

## Model acceptance flow

Candidate models use a third, separate path:

```text
18 fixed synthetic scenarios
     |
     v
BellaOperator.decide()
  - current bella-core-v1 profile
  - real mode and risk policy
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
     |-- any failure --------------------> rejected; nonzero exit
     `-- 18/18 pass ---------------------> hashed acceptance report
```

A passing report does not activate the model and does not grant tool access. It
only records that the exact model tag passed the current mandatory suite under
the current Bella profile.

## Human correction and tuning-data flow

Human-reviewed learning uses a fourth, explicit path:

```text
human selects one completed interaction
     |
     v
review-response command
  - stable interaction id
  - visible prompt only
  - visible original response only
  - human rating
  - optional exact human replacement
  - no hidden Mind Trace packet
  - no credential or capability capture
     |
     v
SQLiteTuningStore
  - immutable interaction hashes
  - immutable feedback events
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

Export does not upload data, start training, or activate a model. Human-derived
regression cases are references that still require human judgment; they are not
forced exact-string tests.

## Bella Operator boundary

`src/bella_harness/operator/` keeps assistant behavior outside model weights:

- `models.py` defines modes, risk levels, decisions, and validation.
- `profile.py` defines `bella-core-v1`, core rules, and mode directives.
- `risk.py` distinguishes explanations, previews, communications, commitments,
  money movement, destructive actions, medication changes, and physical control.
- `context.py` creates the `bella.operator.v1` prompt envelope.
- `service.py` is the facade used by `BellaHarness`.

High and Critical decisions set `approval_required=true`, but that metadata is
not a capability. It only allows a separately supplied exact `ActionSpec` to be
reviewed by Action Gate.

## Mind Trace memory boundary

`src/bella_harness/memory/` provides a read-only deterministic memory seam:

- bounded record validation;
- strict JSONL storage checks;
- approved/current filtering before ranking;
- Customer-mode private-memory exclusion;
- prompt-injection screening before model context;
- bounded JSON context that denies instruction and action authority.

Memory does not approve, edit, delete, write, or execute.

## Bella Action Gate boundary

`src/bella_harness/action_gate/` contains:

- `models.py` -- action kinds, risk floors, payload validation, preview,
  authorization, execution, and audit contracts;
- `canonical.py` -- deterministic `bella.action.v1` JSON and SHA-256 binding;
- `gate.py` -- preview, authorize, execute, expire, revoke, replay protection,
  and hash-chain verification.

Security properties:

- only `mock_action_sandbox` is accepted;
- payload keys resembling credentials or capabilities are rejected;
- preview lifetime is at most 900 seconds;
- authorization lifetime is at most 300 seconds;
- raw capability values are never stored or written to audit events;
- mutation, wrong fingerprint, wrong capability, expiration, and replay fail;
- High decisions cannot authorize Critical action kinds;
- all successful executions are local simulations with no side effects.

`owner_confirmed=true` is an explicit API assertion, not biometric proof. Real
connectors require a future authenticated device-owner layer and durable
encrypted authorization store.

## Bella Evaluation Gate boundary

`src/bella_harness/evaluation/` contains:

- `models.py` -- strict scenarios, candidate responses, results, and reports;
- `scenarios.py` -- exactly 18 mandatory synthetic scenarios;
- `gate.py` -- operator wrapping, Ollama calls, response parsing, deterministic
  checks, all-or-nothing acceptance, and base report generation;
- `secure_gate.py` -- metadata and SHA-256 report verification.

Security properties:

- only a backend whose name is exactly `ollama` is accepted;
- one exact model tag is pinned for the run;
- Ollama receives temperature `0`;
- there is no backend fallback;
- the suite includes no Mind Trace context, personal conversation, credential,
  capability, or real connector;
- candidate output must be one strict JSON object with exact fields and types;
- 17/18 is rejection, not partial acceptance;
- report schema, backend, model, counts, acceptance state, results, and digest are
  verified before the report is written;
- passing never activates a model or grants action authority.

The evaluation suite complements rather than replaces the deterministic red
team. Red team evaluates the rule-based input boundary; Evaluation Gate tests
candidate-model behavior beneath Bella Operator policy.

## Bella tuning boundary

`src/bella_harness/tuning/` contains:

- `models.py` -- bounded interactions, ratings, corrections, and export decisions;
- `store.py` -- SQLite schema, immutable history, versioned corrections, hashes,
  and audit verification;
- `secure_store.py` -- idempotent retry behavior, negative-only correction rules,
  normalized validation, and export audit events;
- `redaction.py` -- deterministic local redaction of common identifiers and keys;
- `export.py` -- atomic JSONL files, file hashes, and dataset manifest;
- `__init__.py` -- the public tuning API.

Security and privacy properties:

- ordinary `bella ask` never creates or writes the tuning store;
- only explicit human review commands create records;
- interaction IDs cannot be reused for different immutable content;
- feedback is append-only;
- corrections are versioned, and only one may be active;
- a correction requires the latest feedback to be negative;
- good responses cannot receive a replacement;
- hidden memory context is not accepted by the schema or CLI;
- redaction is the default export behavior;
- exact unredacted export requires `--exact`;
- export refuses an unverified store;
- outputs are written atomically with best-effort owner-only permissions;
- every export is recorded in the tuning audit chain;
- no automatic upload, training, or model activation exists.

The redaction layer detects common patterns but is not a complete PII classifier.
A human must review any dataset before it leaves the trusted local environment.

## Output scanning

After backend generation, `DeterministicEngine.scan_output()` withholds replies
containing leaked credentials, private keys, or a configured prompt canary.

## DeterministicEngine

The engine uses pure-Python normalization and regex decisions:

1. NFKC and zero-width normalization.
2. Confusable, leetspeak, spacing, fragment, Markdown, Base64, hex, and ROT13
   scan variants.
3. `BLOCK_RULES` matching.
4. Direct greetings and arithmetic.
5. Otherwise `DEFER_TO_LLM`.

This mechanical boundary does not claim to detect every semantic multi-step
attack. Operator, memory, backend alignment, output scanning, exact action
binding, model evaluation, and human review provide separate layers.

## Backends

`BackendAbstraction` supports Ollama, OpenAI, Anthropic, and OpenRouter. Enabled
backends are attempted with the configured default first and fall back on
`BackendError` for ordinary response generation.

Evaluation Gate does not use fallback. It obtains the pinned Ollama instance
directly and rejects nonlocal backend names.

## Configuration

`config/default.yaml` supports `BELLA__SECTION__KEY=value` overrides and rejects
literal secrets.

- `memory` controls the Mind Trace store and recall bounds.
- `operator` controls identity, mode, risk, and prompt wrapping.
- `action_gate` controls only mock preview and authorization lifetimes.
- `evaluation` pins local Ollama evaluation and optional candidate model tag.
- `tuning` documents explicit capture, local store, redaction, upload, training,
  and activation defaults. `store_path: null` requires `--db`.
- minimal programmatic configs that omit newer sections keep legacy behavior;
  the shipped default enables the bounded layers without automatic capture.

## Verification

`redteam/` contains 115 offline probes across 39 specialist agents. Pytest adds
memory, operator, action fingerprint, risk-floor, expiration, replay, mutation,
audit-chain, CLI proof, evaluation catalog, strict candidate JSON, all-or-nothing
acceptance, report integrity, cloud rejection, deterministic Ollama options,
SQLite tuning integrity, correction versioning, redaction, export hashes, and
normal-chat non-capture coverage.

`.github/workflows/redteam.yml` runs the full unit and red-team suites on Python
3.10 and 3.12 and uploads both pytest output and red-team reports. Live Ollama
evaluation and real training are explicit operator workflows and are not faked
in CI.
