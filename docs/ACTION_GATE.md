# Bella Action Gate

Bella Action Gate separates **thinking**, **planning**, **approval**, and
**execution**. The normal `BellaHarness.handle()` response path cannot execute
an action. Consequential actions use a separate exact-preview API.

This release supports only `mock_action_sandbox`. It cannot send email, change a
calendar, modify a file, move money, change an account, control a device, or
produce any external side effect.

## Flow

```text
consequential user request
        |
        v
DeterministicEngine.evaluate()
        |-- BLOCK --------------------> no preview
        |-- ALLOW_DETERMINISTIC ------> cannot be upgraded into an action
        `-- DEFER_TO_LLM
                |
                v
BellaOperator.decide()
  - High or Critical
  - approval_required=true
  - risk must meet the action-kind floor
                |
                v
ActionGate.prepare()
  - exact connector, kind, target, payload
  - canonical JSON
  - SHA-256 fingerprint
  - 15-minute maximum preview lifetime
                |
                v
human reviews exact preview
                |
                v
ActionGate.authorize()
  - exact fingerprint required
  - explicit owner_confirmed=true required
  - random one-use capability
  - only capability hash retained
  - 5-minute maximum authorization lifetime
                |
                v
ActionGate.execute_sandbox()
  - exact spec fingerprint rechecked
  - one-use capability consumed before result creation
  - local simulation only
  - simulated=true
  - sideEffectsPerformed=false
```

## Action kinds and risk floors

| Action kind | Minimum operator risk |
|---|---|
| `send_message` | High |
| `calendar_change` | High |
| `file_change` | High |
| `payment` | Critical |
| `account_change` | Critical |
| `device_control` | Critical |

A Medium draft cannot be upgraded into `send_message`. A High communication
request cannot authorize `payment`. The action kind has its own minimum risk,
so a caller cannot lower consequence by supplying misleading text.

## Exact review binding

The fingerprint is SHA-256 over canonical UTF-8 JSON containing:

- schema `bella.action.v1`;
- connector;
- action kind;
- target;
- payload.

Object keys are sorted, ambiguous non-finite numbers are rejected, and payloads
are bounded. Any change to the target or payload after review changes the
fingerprint and execution fails closed.

Payload keys that look like passwords, API keys, tokens, credentials, secrets,
or private keys are rejected. Capabilities and connector credentials must never
be embedded in action payloads.

## One-use capability

Authorization returns a cryptographically random capability. The raw capability
is returned to the immediate caller once and is never stored in the gate or
audit log. Only its SHA-256 digest is retained for constant-time comparison.

The capability is:

- bound to one preview and one fingerprint;
- short lived;
- consumed before the simulation result is constructed;
- rejected on replay;
- cleared on expiration or revocation.

`owner_confirmed=true` is an explicit API assertion, not biometric identity
proof. A future device UI must establish actual device-owner authentication
before setting it for a real connector.

## Audit chain

Preview creation, authorization, expiration, revocation, and sandbox execution
produce append-only audit events. Each event includes the previous event hash
and its own SHA-256 hash. `verify_audit_chain()` detects event mutation, removal,
reordering, or broken linkage within the in-memory session.

The current audit store is intentionally in memory. It is a prototype boundary,
not durable forensic storage.

## Runnable proof

Preview only:

```bash
PYTHONPATH=src python -m bella_harness.cli sandbox-action \
  "Send an email to the customer" \
  --kind send_message \
  --target customer@example.com \
  --payload '{"subject":"Invoice","body":"Invoice 1042 is overdue."}' \
  --mode business
```

Confirm and consume in the mock sandbox:

```bash
PYTHONPATH=src python -m bella_harness.cli sandbox-action \
  "Send an email to the customer" \
  --kind send_message \
  --target customer@example.com \
  --payload '{"subject":"Invoice","body":"Invoice 1042 is overdue."}' \
  --mode business \
  --confirm
```

The command never prints the capability. Confirmed output records
`simulated=true` and `sideEffectsPerformed=false`.

## Scope boundary before real connectors

No real connector should be added until all of these exist:

1. durable encrypted authorization and audit storage;
2. verified device-owner authentication;
3. connector-specific target and payload schemas;
4. idempotency and rollback behavior;
5. separate permission grants per connector and operation;
6. live integration tests against non-production accounts;
7. explicit spend and geography controls for financial or communications tools;
8. independent security review.
