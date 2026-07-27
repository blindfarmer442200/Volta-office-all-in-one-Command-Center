# Architecture

Bella Harness is deterministic-first. Models generate language, but deterministic
code owns input blocking, memory eligibility, Bella identity, consequence risk,
action authorization, HTTP authentication, network egress, output scanning,
evaluation, tuning history, and release acceptance.

## Core response flow

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
returns a response plus visible memory and operator metadata.

## Authenticated HTTP flow

```text
HTTP request
     |
     v
trusted Host + body-size boundary + request ID
     |
     |-- /health/live ----------------> minimal unauthenticated liveness
     `-- authenticated route
             |
             v
       constant-time bearer-token check
         - raw token never logged
         - failed-auth limiter
             |
             v
       authenticated request limiter
             |
             |-- /health/ready --------> prompt-free service-aware doctor
             `-- /v1/chat
                     |
                     v
               strict JSON model
                 - extra fields rejected
                 - prompt/mode bounded
                     |
                     v
               bounded semaphore + thread executor
                 - timeout does not free slot until worker ends
                     |
                     v
               BellaHarness.handle()
                     |
                     v
               response metadata
                 - external_action_performed=false
                 - trace hidden unless explicitly requested
```

The service registers no Action Gate, tuning-write, connector, file, calendar,
payment, account, smart-home, or device-control route. API docs, OpenAPI, CORS,
proxy-header trust, and Uvicorn access logs are disabled.

The default bind is `127.0.0.1:8765`. Remote binding requires an explicit
`allow_remote_bind` setting, a literal IP address, and an explicit non-loopback
trusted Host. Wildcard trusted hosts are rejected.

Service logs contain request ID, method, path, status, duration, and unexpected
exception type only. Prompt, response, memory, token, and capability content is
not logged.

## Cloud-egress boundary

The shipped routing configuration is:

```yaml
harness:
  default_backend: ollama
  allow_cloud_fallback: false
```

An unpinned request therefore uses eligible local backends only. An Ollama
failure does not silently transmit the operator envelope or approved memory to a
cloud provider. Local-to-cloud fallback requires explicit consent.

Ollama accepts only `localhost` or a literal loopback/private IP. Public IPs,
arbitrary DNS hosts, embedded credentials, path prefixes, queries, fragments,
redirects, malformed JSON, invalid UTF-8, and oversized prompts or responses
fail closed.

See `docs/CLOUD_EGRESS.md`.

## Action flow

Consequential operations use a separate Python API:

```text
BellaHarness.prepare_action(request, exact ActionSpec)
     |
     v
input gate + Bella consequence decision
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
  - random short-lived one-use capability
  - only capability hash retained
     |
     v
ActionGate.execute_sandbox()
  - fingerprint rechecked
  - mutation/replay rejected
  - simulated=true
  - sideEffectsPerformed=false
```

The response and HTTP paths cannot call Action Gate. Action Gate cannot call a
real connector in the current production scope.

## Model acceptance flow

```text
18 fixed synthetic scenarios
     |
     v
Bella Operator envelope
     |
     v
one pinned Ollama model
  - temperature 0
  - no cloud fallback
  - no tools or personal memory
     |
     v
strict evaluation JSON
     |
     v
deterministic checks
     |
     |-- any failure ----------------> rejected
     `-- 18/18 pass -----------------> hashed acceptance report
```

Passing never activates the model or grants memory, connector, or action
authority.

## Human correction and tuning flow

```text
explicit human review
     |
     v
immutable interaction + append-only rating
     |
     v
optional versioned human correction
     |
     v
SQLite integrity + hash-chained audit
     |
     v
redacted local export
     +--> sft.jsonl
     +--> preference.jsonl
     +--> evaluation-only.jsonl
     +--> regression.jsonl
     `--> manifest.json
```

Normal chat is never automatically captured. Export never uploads, trains, or
activates a model.

## Component boundaries

### Deterministic engine

`src/bella_harness/deterministic/` normalizes Unicode and scans confusables,
leetspeak, spacing, fragments, Markdown, Base64, hex, and ROT13 variants before
applying blocking and direct-answer rules.

### Bella Operator

`src/bella_harness/operator/` owns `bella-core-v1`, nine modes, consequence
levels, visible plans, current approval metadata, accessibility and uncertainty
directives, and false-completion prevention.

### Mind Trace

`src/bella_harness/memory/` owns strict records, approved/current filtering,
superseded/expired exclusion, Customer privacy, stored-injection screening, and
bounded JSON context. Memory cannot approve, write, delete, or execute.

### Action Gate

`src/bella_harness/action_gate/` owns fingerprints, previews, one-use
authorization, expiry, revocation, replay protection, risk floors, and a
hash-chained audit. Only `mock_action_sandbox` is accepted.

### Evaluation Gate

`src/bella_harness/evaluation/` owns the scenario catalog, candidate contract,
all-or-nothing checks, and hashed reports. Evaluation is pinned to Ollama with no
memory, tools, or fallback.

### Tuning loop

`src/bella_harness/tuning/` owns bounded reviews, SQLite history, deterministic
redaction, atomic exports, and audit verification.

### Authenticated service

`src/bella_harness/service/` owns:

- strict service settings and strong environment-token validation;
- constant-time bearer authentication;
- independent failed-authentication and authenticated-request limits;
- trusted Host, body, prompt, concurrency, and timeout boundaries;
- safe request IDs, security headers, and metadata-only logging;
- `/health/live`, `/health/ready`, and `/v1/chat` only;
- service-aware doctor checks.

The service uses one process-local limiter and executor. Multi-worker or
multi-instance scale-out requires a future shared limiter and shared operational
audit.

### Production doctor

The core and service-aware doctor checks packaged configuration, fail-closed
policy, output scanning, Operator, Action Gate bounds, Evaluation Gate policy,
disabled automatic tuning, configured store integrity, backend routing, private
Ollama transport, service binding/authentication, and optional live Ollama
health.

## Container boundary

The provided image:

- builds from the verified wheel;
- runs as UID/GID `10001:10001`;
- can run read-only with all capabilities dropped and `no-new-privileges`;
- binds loopback by default;
- requires `BELLA_SERVICE_TOKEN`;
- exposes no action route.

`compose.service.yml` uses Linux host networking so the loopback-bound container
can reach host Ollama and be reached by host Caddy without publishing port 8765.

See `docs/SERVICE_DEPLOYMENT.md`.

## Configuration

The repository and packaged `default.yaml` files are byte-identical. Environment
overrides use `BELLA__SECTION__KEY=value`; literal secrets are rejected.

- `harness`: routing, cloud consent, fail-closed policy, output scanning.
- `memory`: Mind Trace store and recall bounds.
- `operator`: model-independent Bella policy.
- `action_gate`: mock preview and authorization lifetimes.
- `evaluation`: pinned local model acceptance.
- `tuning`: explicit review storage; automatic operations remain false.
- `service`: disabled-by-default authenticated HTTP boundary and limits.
- `backends`: enabled providers and transport bounds.

## Release-evidence flow

```text
source commit
     |
     v
Python 3.10 + 3.12 + dependency audit
     |
     v
unit baseline + 115 red-team probes
     |
     v
wheel + source archive + metadata/content validation
     |
     v
clean wheel install with service extra + installed doctor
     |
     v
non-root read-only authenticated container smoke
  - deterministic chat succeeds
  - external_action_performed=false
  - action route is 404
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

The release manifest requires dependency, distribution, wheel, doctor, and
container gates to pass, plus the established unit/red-team floors and verified
artifact hashes.

## Verification boundary

CI proves source compilation, supported Python behavior, dependency audit,
unit/red-team baselines, package metadata, source-archive contents, clean wheel
installation, service-extra installation, installed doctor readiness,
authenticated container behavior, closed action routing, and release-manifest
integrity.

CI does not prove:

- the selected real model passes on the final host;
- physical Android/iPhone behavior;
- final screen-reader or voice quality;
- Caddy/TLS behavior on the real domain;
- long-running host stability and load;
- backup restoration on the operator's storage;
- real connector safety, because real connectors remain absent.

See `docs/PRODUCTION_READINESS.md`, `docs/SERVICE_DEPLOYMENT.md`, and
`docs/RELEASE_PROCESS.md`.
