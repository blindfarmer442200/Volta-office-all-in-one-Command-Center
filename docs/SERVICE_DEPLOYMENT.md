# Bella Authenticated Service Deployment

Bella's HTTP service exposes ordinary chat and health checks only. It does not
expose Action Gate, tuning-write, connector, file, calendar, payment, account,
smart-home, or device-control endpoints.

## API surface

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| `GET` | `/health/live` | No | Minimal process liveness only |
| `GET` | `/health/ready` | Bearer token | Full prompt-free readiness checks |
| `POST` | `/v1/chat` | Bearer token | Ordinary Bella response path |

Interactive API documentation, OpenAPI, CORS, and action routes are disabled.

## Create a service token

Generate a strong token locally:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Store it in an environment variable, not YAML, source control, shell history, or
an application log:

```bash
export BELLA_SERVICE_TOKEN='paste-the-generated-token-here'
```

For a local `.env` file used by Docker Compose:

```bash
umask 077
printf 'BELLA_SERVICE_TOKEN=%s\n' 'paste-the-generated-token-here' > .env
chmod 600 .env
```

`.env` files are excluded from the Docker build context and should remain out of
Git.

## Direct host installation

Install the service extra in a clean environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install 'bella-harness[service]'
```

Enable and start the loopback service:

```bash
export BELLA_SERVICE_TOKEN='paste-the-generated-token-here'
export BELLA__SERVICE__ENABLED=true
bella doctor
bella serve
```

Default bind address:

```text
127.0.0.1:8765
```

The service refuses to start when the token is missing or weak, critical doctor
checks fail, or a non-loopback bind is requested without explicit remote-bind
consent.

## Docker Compose on Linux

`compose.service.yml` uses host networking deliberately:

- Bella stays bound to host loopback;
- Bella can reach a host Ollama process at `127.0.0.1:11434`;
- a host Caddy process can reach Bella at `127.0.0.1:8765`;
- no public Docker port is published.

Start it:

```bash
export BELLA_SERVICE_TOKEN='paste-the-generated-token-here'
docker compose -f compose.service.yml build
docker compose -f compose.service.yml up -d
```

Verify liveness:

```bash
curl --fail --silent http://127.0.0.1:8765/health/live
```

Verify authenticated readiness:

```bash
curl --fail --silent \
  -H "Authorization: Bearer $BELLA_SERVICE_TOKEN" \
  http://127.0.0.1:8765/health/ready
```

The Compose service runs as non-root, drops all Linux capabilities, enables
`no-new-privileges`, uses a read-only root filesystem, and provides only a small
`/tmp` tmpfs.

`network_mode: host` is intended for Linux. Docker Desktop on Windows or macOS
requires a different private-network design and must not be assumed equivalent.

## Caddy reverse proxy

Keep Bella bound to loopback and terminate HTTPS in Caddy. Add the public domain
to Bella's trusted-host list because Caddy normally preserves the original Host
header.

Example environment override:

```bash
export BELLA__SERVICE__TRUSTED_HOSTS='["localhost","127.0.0.1","::1","bella.example.com"]'
```

Example Caddyfile:

```caddyfile
bella.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8765
}
```

Clients must still send Bella's bearer token. Caddy TLS does not replace Bella
service authentication.

Do not expose port `8765` publicly. Allow inbound HTTPS to Caddy and keep Bella
on loopback.

## Send a chat request

```bash
curl --fail --silent \
  -H "Authorization: Bearer $BELLA_SERVICE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"hello","mode":"life"}' \
  http://127.0.0.1:8765/v1/chat
```

The response always includes:

```json
{
  "external_action_performed": false
}
```

Memory identifiers, recall explanations, excluded unsafe-memory identifiers,
operator reasons, and operator plans are hidden by default. A trusted client may
request them explicitly:

```json
{
  "prompt": "Explain invoice 1042",
  "mode": "business",
  "trace": true
}
```

Trace data can reveal internal memory identifiers and reasoning metadata. Do not
return it to untrusted clients.

## Limits

The shipped defaults enforce:

- request body: 64 KiB;
- prompt: 32,000 characters;
- concurrent model requests: 4;
- request timeout: 90 seconds;
- authenticated chat rate: 60 requests per 60 seconds;
- trusted hosts: loopback names and addresses only;
- one process-local limiter and executor.

Run a single service worker. Multiple workers would each have separate rate and
concurrency state. Scale-out requires a future shared limiter, shared operational
audit, and explicit load-balancing design.

A timed-out model worker retains its concurrency slot until that worker actually
finishes. This prevents repeated timeouts from creating unbounded background
work.

## Logging and privacy

Service logs contain only:

- request ID;
- HTTP method;
- route path;
- response status;
- duration;
- exception type for unexpected failures.

They do not contain request bodies, response bodies, prompt text, memory content,
tokens, credentials, or Action Gate capabilities.

Uvicorn access logging, proxy-header trust, server headers, API docs, and CORS
are disabled by the installed command.

## Remote binding

Loopback is the recommended production configuration. A non-loopback bind
requires all of the following:

```yaml
service:
  allow_remote_bind: true
  host: 192.168.1.20
  trusted_hosts:
    - bella.internal.example
```

The host must be a literal IP address; arbitrary DNS bind names and wildcard
trusted hosts are rejected. Use network firewall rules and TLS in addition to
the bearer token.

## Rotation and restart

To rotate the token:

1. Generate a new token.
2. Replace `BELLA_SERVICE_TOKEN` in the service environment.
3. Restart Bella.
4. Update trusted clients.
5. Remove the old token from any secret manager or local environment.

Bella stores only a SHA-256 digest of the active token in memory while running.
A restart is required to activate a new token.

## Deployment acceptance

Before serving real users:

```bash
bella doctor
bella doctor --live
bella evaluate-bella --model <exact-model-tag> --report bella-evaluation-report.json
```

Also verify:

- HTTPS and trusted Host behavior through Caddy;
- token rotation;
- backup restoration for configured memory/tuning stores;
- final screen-reader and voice workflow;
- target-host load and long-running Ollama stability;
- rollback to the previous accepted wheel and model.

A healthy HTTP process does not prove that the chosen model, host, network,
accessibility workflow, or backups are production-ready.
