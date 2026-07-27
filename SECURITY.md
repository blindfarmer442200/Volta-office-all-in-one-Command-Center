# Security Policy

## Supported version

Security fixes currently target the latest `0.2.x` release line and the `main`
branch.

## Reporting a vulnerability

Do not publish credentials, bearer tokens, private memory, tuning data, action
capabilities, or working exploit details in a public issue.

Use a private GitHub security advisory when available. Otherwise contact the
repository owner privately through GitHub and provide only enough non-sensitive
detail to establish a secure reporting channel.

Include:

- affected commit or release;
- affected operating system and Python version;
- minimal reproduction steps;
- expected and actual behavior;
- whether private data, authentication, authority, or external actions are
  affected;
- suggested mitigation, when known.

## Release-blocking invariants

1. Blocked requests cannot access Mind Trace or a model.
2. Memory is untrusted data and cannot grant authority.
3. Ordinary model and HTTP responses cannot execute actions.
4. Action Gate supports only the local side-effect-free mock sandbox.
5. The HTTP service exposes no Action Gate or connector route.
6. Raw one-use capabilities are not stored in audit history.
7. Model output is scanned before release to the user.
8. Literal secrets are rejected from configuration.
9. Ollama transport is limited to localhost or literal private addresses.
10. Ollama redirects and oversized or malformed responses fail closed.
11. Local backend failure cannot trigger cloud egress unless
    `harness.allow_cloud_fallback` is explicitly true.
12. Candidate models require 18/18 mandatory evaluation scenarios.
13. Normal conversations are not automatically captured for tuning.
14. Tuning export is redacted by default and never uploads or trains itself.
15. Configured memory and tuning-store integrity failures block affected flows.
16. Service chat and readiness require a strong bearer token.
17. Service binds loopback by default; remote binding requires explicit consent
    and explicit trusted hosts.
18. Wildcard trusted hosts, API docs, OpenAPI, CORS, proxy-header trust, and
    Uvicorn access logs are disabled.
19. Request bodies, prompts, concurrent model work, timeouts, authenticated
    requests, and failed authentication attempts are bounded.
20. Service logs must not contain prompt, response, memory, token, credential, or
    capability content.
21. Release evidence requires a non-root, read-only container smoke test and a
    closed action route.
22. Every pull request must preserve the 115-probe deterministic red-team gate.

## Authentication

Service tokens must be supplied through the configured environment variable and
contain 32 to 512 non-whitespace characters. Bella stores only a SHA-256 digest
of the token in memory and compares presented tokens in constant time.

Failed authentication attempts have a separate limiter so brute-force attempts
are bounded without locking out a client that presents the correct token.

Rotate a token by replacing the environment value and restarting the service.
Do not place tokens in YAML, Git, shell history, URLs, query parameters, general
logs, or client-side browser code.

Bearer authentication does not replace TLS. Use Caddy or another reviewed TLS
boundary when clients connect beyond host loopback.

## Data handling

Do not include raw prompts, private memory packets, unredacted tuning examples,
OAuth tokens, API keys, payment data, bearer tokens, or action capabilities in
general logs, issues, CI artifacts, or evaluation reports.

The tuning redactor is defense in depth and is not a complete PII classifier.
Review datasets manually before moving them outside the trusted local host.

Trace-enabled service responses may expose internal memory identifiers and
operator metadata. Enable trace only for trusted clients.

Enabling a cloud provider does not authorize automatic fallback from Ollama.
Review [docs/CLOUD_EGRESS.md](docs/CLOUD_EGRESS.md) before setting
`allow_cloud_fallback: true` or selecting a cloud provider as the default.

## Container and network

The provided container runs as UID/GID `10001:10001`. Production Compose uses a
read-only root filesystem, drops all capabilities, applies
`no-new-privileges`, and keeps Bella on loopback through Linux host networking.

Do not publish port 8765 directly to the internet. Put Caddy or another reviewed
reverse proxy in front of the loopback service and add the public domain to
Bella's explicit trusted-host list.

The image build and runtime smoke are release gates, but base-image provenance
and host Docker security remain operator responsibilities.

## Deployment

Run before deployment:

```bash
bella doctor
bella doctor --live
bella evaluate-bella --model <exact-model-tag> --report bella-evaluation-report.json
```

Then test authenticated service behavior, TLS, Host validation, token rotation,
load, accessibility, backup restoration, and rollback on the actual host. See:

- [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md)
- [docs/SERVICE_DEPLOYMENT.md](docs/SERVICE_DEPLOYMENT.md)
- [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md)

## Out of scope today

Real email, payment, calendar, file, account, smart-home, and device-control
connectors are not implemented. A report that those actions cannot execute is
not a vulnerability. Any path that creates such a side effect despite the
mock-only boundary is a critical vulnerability.
