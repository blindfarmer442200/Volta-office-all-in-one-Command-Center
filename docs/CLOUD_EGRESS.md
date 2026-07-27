# Cloud Egress Policy

Bella is local-first. A local Ollama failure must not silently transmit a user
request, Bella operator envelope, or recalled Mind Trace context to a cloud
provider.

## Default

```yaml
harness:
  default_backend: ollama
  allow_cloud_fallback: false
```

With this configuration, unpinned requests may use enabled local backends only.
If Ollama fails, Bella returns a backend-unavailable result rather than trying
OpenAI, Anthropic, or OpenRouter.

Merely setting a cloud backend to `enabled: true` does not authorize automatic
egress.

## Explicit automatic fallback

Automatic local-to-cloud fallback requires both:

1. the cloud backend is enabled and has its credential supplied through its
   named environment variable; and
2. `harness.allow_cloud_fallback` is explicitly `true`.

```yaml
harness:
  default_backend: ollama
  allow_cloud_fallback: true

backends:
  openai:
    enabled: true
    api_key_env: OPENAI_API_KEY
```

This setting means an Ollama failure may send the complete model prompt to the
next enabled cloud backend. That prompt can include approved memory context.
Enable it only after the operator has approved the provider, privacy policy,
retention terms, jurisdiction, and data classification.

## Explicit pinned route

Library callers may select a specifically enabled backend by name. A pinned
cloud backend is treated as an explicit routing decision and does not trigger
fallback to another backend if it fails.

The ordinary `BellaHarness.handle()` response path does not expose a backend
selector. It follows the configured automatic order.

## Default cloud backend

Setting a cloud provider as `harness.default_backend` is itself an explicit
cloud-routing configuration. `allow_cloud_fallback: false` does not block the
chosen default provider; it prevents an implicit escalation from a local
default to cloud.

## Validation

The backend abstraction rejects non-boolean `allow_cloud_fallback` values.
Regression tests prove:

- local failure does not call cloud by default;
- the cloud transport is untouched when fallback is disabled;
- explicit opt-in permits fallback;
- explicit pinned cloud routing remains possible;
- pinned backend failure does not cascade;
- packaged defaults keep fallback disabled.

`bella doctor` warns when cloud backends are enabled. Treat that warning as a
required privacy review before deployment.
