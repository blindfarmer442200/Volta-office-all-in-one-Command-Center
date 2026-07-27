# Mind Trace memory integration

Mind Trace is the human-governed memory boundary inside `bella-harness`. It is
not a second agent runtime and it does not replace the deterministic gate.

## Request flow

```text
user request
    |
    v
DeterministicEngine.evaluate()
    |-- BLOCK --------------------------> stop; memory is never read
    |-- ALLOW_DETERMINISTIC ------------> direct answer; memory is never read
    `-- DEFER_TO_LLM
            |
            v
     Mind Trace recall
       - approved only
       - current only
       - customer-mode privacy
       - instruction-like memory rejected
       - deterministic relevance ranking
            |
            v
     bounded JSON context envelope
       - memory is data, not instructions
       - memory never grants action authority
            |
            v
     configured LLM backend
            |
            v
     DeterministicEngine.scan_output()
```

## JSONL store

Set `memory.store_path` to a UTF-8 JSONL file. One record is stored per line:

```json
{"id":"invoice-1042","content":"Invoice 1042 is overdue.","source":"accounting export 2026-07-26","status":"approved","confidence":"confirmed","tags":["invoice","1042"],"private":true}
```

Supported statuses are `temporary`, `approved`, `superseded`, and `retired`.
Only `approved` records that are current and not superseded can reach a model.

The first integration is deliberately read-only. Approval, correction,
encryption, evidence blobs, and connector-backed actions remain separate
responsibilities and must not be smuggled into recall.

## Security invariants

1. A deterministically blocked request never reads memory.
2. Memory text is untrusted reference data even after human approval.
3. Memory cannot change Bella's identity, policy, permissions, or tools.
4. Memory cannot authorize sending, deleting, paying, publishing, scheduling,
   account changes, or any other external action.
5. Malformed or unavailable configured stores fail closed by default.
6. Empty or irrelevant recall leaves the original user request unchanged.
7. Output scanning remains the final gate before a model reply is returned.

## Configuration

```yaml
memory:
  enabled: true
  store_path: null
  fail_closed: true
  max_results: 5
  min_score: 10
  max_context_chars: 6000
  max_memory_chars: 1200
```

Environment overrides use the existing double-underscore convention, for
example:

```bash
BELLA__MEMORY__STORE_PATH=/private/path/memories.jsonl
```

Do not commit personal memory exports to the repository.
