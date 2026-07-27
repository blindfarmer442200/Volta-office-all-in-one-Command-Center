# Security Policy

## Supported version

Security fixes currently target the latest `0.2.x` release line and the `main`
branch.

## Reporting a vulnerability

Do not publish credentials, private memory, tuning data, action capabilities, or
working exploit details in a public issue.

Use a private GitHub security advisory for this repository when available. If
that option is unavailable, contact the repository owner privately through
GitHub and provide only enough non-sensitive detail to establish a secure
reporting channel.

Include:

- affected commit or release;
- affected operating system and Python version;
- minimal reproduction steps;
- expected and actual behavior;
- whether private data, authority, or external actions are affected;
- suggested mitigation, when known.

## Security invariants

The project treats these as release-blocking invariants:

1. Blocked requests cannot access Mind Trace or a model.
2. Memory is untrusted data and cannot grant authority.
3. Ordinary model responses cannot execute actions.
4. Action Gate supports only the local side-effect-free mock sandbox.
5. Raw one-use capabilities are not stored in audit history.
6. Model output is scanned before release to the user.
7. Literal secrets are rejected from configuration.
8. Ollama transport is limited to localhost or literal private addresses.
9. Ollama redirects and oversized or malformed responses fail closed.
10. Local backend failure cannot trigger cloud egress unless
    `harness.allow_cloud_fallback` is explicitly true.
11. Candidate models require 18/18 mandatory evaluation scenarios.
12. Normal conversations are not automatically captured for tuning.
13. Tuning export is redacted by default and never uploads or trains itself.
14. Configured memory and tuning-store integrity failures block affected flows.
15. Every pull request must preserve the 115-probe deterministic red-team gate.

## Data handling

Do not place secrets in repository files or command examples. Use environment
variables for provider credentials.

Do not include raw prompts, private memory packets, unredacted tuning examples,
OAuth tokens, API keys, payment data, or action capabilities in general logs,
issues, CI artifacts, or evaluation reports.

The tuning redactor is defense in depth and is not a complete PII classifier.
Review datasets manually before moving them outside the trusted local host.

Enabling a cloud provider does not authorize automatic fallback from Ollama.
Review [docs/CLOUD_EGRESS.md](docs/CLOUD_EGRESS.md) before setting
`allow_cloud_fallback: true` or selecting a cloud provider as the default.

## Deployment

Run both commands before deployment:

```bash
bella doctor
bella doctor --live
```

Also run the exact selected model through the Bella Evaluation Gate. See
`docs/PRODUCTION_READINESS.md` for the complete release, backup, monitoring, and
rollback gates.

## Out of scope today

Real email, payment, calendar, file, account, smart-home, and device-control
connectors are not implemented. A report that those actions cannot execute is
not a vulnerability. Any path that creates such a side effect despite the
mock-only boundary is a critical vulnerability.
