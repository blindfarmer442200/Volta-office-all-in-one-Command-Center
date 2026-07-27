# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY src ./src

RUN python -m pip install --no-cache-dir "setuptools>=68" "build>=1.2" \
    && SOURCE_DATE_EPOCH=315532800 python -m build --wheel --no-isolation

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Bella Harness" \
      org.opencontainers.image.description="Authenticated deterministic-first Bella AI service" \
      org.opencontainers.image.licenses="MIT"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BELLA__SERVICE__ENABLED=true \
    BELLA__SERVICE__HOST=127.0.0.1 \
    BELLA__SERVICE__PORT=8765

RUN groupadd --system --gid 10001 bella \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin bella

COPY --from=builder /build/dist/*.whl /tmp/dist/

RUN set -eux; \
    wheel="$(find /tmp/dist -maxdepth 1 -name '*.whl' -print -quit)"; \
    test -n "$wheel"; \
    python -m pip install --no-cache-dir "bella-harness[service] @ file://${wheel}"; \
    python -m pip check; \
    rm -rf /tmp/dist

USER 10001:10001
WORKDIR /app

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health/live', timeout=3).read()"]

CMD ["bella", "serve"]
