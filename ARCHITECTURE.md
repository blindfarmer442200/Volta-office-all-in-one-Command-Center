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

`BellaHarness.handle()` never executes actions. It returns a response plus
visible memory and operator metadata.

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
attack. Operator, memory, backend alignment, output scanning, and exact action
binding provide separate layers.

## Backends

`BackendAbstraction` supports Ollama, OpenAI, Anthropic, and OpenRouter. Enabled
backends are attempted with the configured default first and fall back on
`BackendError`.

## Configuration

`config/default.yaml` supports `BELLA__SECTION__KEY=value` overrides and rejects
literal secrets.

- `memory` controls the Mind Trace store and recall bounds.
- `operator` controls identity, mode, risk, and prompt wrapping.
- `action_gate` controls only mock preview and authorization lifetimes.
- minimal programmatic configs that omit newer sections keep legacy behavior;
  the shipped default enables the bounded layers.

## Verification

`redteam/` contains 115 offline probes across 39 specialist agents. Pytest adds
memory, operator, action fingerprint, risk-floor, expiration, replay, mutation,
audit-chain, CLI proof, and harness-boundary coverage.

`.github/workflows/redteam.yml` runs the full unit and red-team suites on Python
3.10 and 3.12 and uploads both pytest output and red-team reports.
