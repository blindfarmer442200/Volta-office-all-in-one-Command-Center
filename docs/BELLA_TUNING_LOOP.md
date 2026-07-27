# Bella Correction and Tuning Loop

Bella's tuning loop converts explicit human reviews into local, auditable data
without silently capturing conversations, uploading private text, training a
model, or changing the active backend.

## Scope

This layer provides:

- an explicit human review command;
- immutable interaction records;
- immutable feedback events;
- versioned human replacement answers;
- one active correction per interaction;
- SQLite durability and integrity checks;
- a hash-chained audit trail;
- redacted-by-default JSONL export;
- SFT, preference, evaluation-only, and regression artifacts;
- file-level SHA-256 hashes and a dataset manifest.

It does **not**:

- capture ordinary `bella ask` requests;
- store hidden Mind Trace packets;
- store Action Gate capabilities;
- store connector credentials;
- upload a dataset;
- start fine-tuning;
- activate a model;
- decide that a corrected answer is legally, medically, or factually correct.

## Ratings

The human may assign one of these ratings:

- `good`
- `too_soft`
- `too_harsh`
- `too_long`
- `too_vague`
- `missed_point`
- `wrong_memory`
- `unsafe_overreach`

A `good` response becomes an SFT candidate using Bella's original reviewed
answer. A negative response with an exact human correction becomes:

1. an SFT candidate using the corrected answer;
2. a chosen-versus-rejected preference pair;
3. a replayable regression case that still requires human judgment.

A negative response without a correction remains `evaluation_only`. It is not
silently treated as positive training data.

## Durable store

The local store uses SQLite with:

- schema version validation;
- foreign keys;
- WAL journaling;
- full synchronization;
- a 15-second busy timeout;
- a 512 MiB database safety limit;
- immutable prompt and original-response SHA-256 values;
- immutable feedback history;
- correction version history;
- a partial unique index allowing only one active correction;
- an append-only hash-chained audit table;
- best-effort owner-only file permissions on POSIX systems.

Reusing an interaction ID with identical immutable content is idempotent. Reusing
it with different content fails closed.

A correction is accepted only after the latest human rating is negative.
Positive responses cannot receive a replacement answer.

## Explicit review

Inline text may be supplied directly. Prefix a value with `@` to read UTF-8 text
from a file, which is easier for longer responses and assistive workflows.

```bash
PYTHONPATH=src python -m bella_harness.cli review-response \
  --db bella-tuning.sqlite3 \
  --interaction-id invoice-answer-001 \
  --prompt @prompt.txt \
  --response @original-response.txt \
  --rating unsafe_overreach \
  --corrected @corrected-response.txt \
  --note "Bella claimed the email had already been sent." \
  --mode business \
  --risk-level high \
  --profile-id bella-core-v1 \
  --model qwen3.5
```

The command returns identifiers and integrity status. It does not echo the
prompt, original response, or correction.

## Verification

```bash
PYTHONPATH=src python -m bella_harness.cli verify-tuning \
  --db bella-tuning.sqlite3
```

Verification checks:

- SQLite's integrity result;
- prompt and response content hashes;
- correction content hashes;
- one-active-correction uniqueness;
- audit sequence continuity;
- audit previous-hash links;
- every audit event hash.

Export refuses to run if verification fails.

## Redacted export

```bash
PYTHONPATH=src python -m bella_harness.cli export-tuning \
  --db bella-tuning.sqlite3 \
  --output-dir bella-dataset
```

Default export locally redacts common:

- email addresses;
- United States phone-number forms;
- Social Security number forms;
- payment-card-like number strings;
- common API-key forms;
- bearer tokens;
- credentials embedded in URLs.

Redaction is a defense-in-depth filter, not a guarantee that every possible
identifier will be detected. Human review of exported data remains required.

The output directory contains:

```text
bella-dataset/
├── sft.jsonl
├── preference.jsonl
├── evaluation-only.jsonl
├── regression.jsonl
└── manifest.json
```

`manifest.json` includes record counts, byte counts, SHA-256 hashes, redaction
status, and a dataset digest. Files are written atomically and receive
best-effort owner-only permissions.

## Exact export

An exact unredacted export requires a separate explicit flag:

```bash
PYTHONPATH=src python -m bella_harness.cli export-tuning \
  --db bella-tuning.sqlite3 \
  --output-dir bella-dataset-exact \
  --exact
```

Exact export is for a trusted local environment only. It still does not upload,
train, or activate anything.

## Regression data

Human corrections are exported as reference cases, not simplistic exact-match
tests. Many valid responses can differ in wording while respecting the same
correction. The regression artifact therefore records:

- the prompt;
- mode and risk level;
- chosen human reference;
- rejected original reference;
- original rating;
- `human_review_required=true`;
- `automatic_exact_match_required=false`.

A future model-training workflow must run both the fixed 18-scenario Bella
Evaluation Gate and these human-derived regression cases before a model is
considered for activation.

## Production boundary

This layer is suitable for local prototype data collection, but production
model training still requires:

- a selected base model with a verified license;
- dataset consent and retention policy;
- additional PII review;
- train/validation/test separation;
- duplicate and contamination checks;
- reproducible training configuration;
- model artifact hashing and provenance;
- evaluation on real hardware;
- rollback to the previously accepted model;
- explicit human activation after all gates pass.
