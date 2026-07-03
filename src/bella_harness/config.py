"""Configuration loading: YAML on disk, overridden by environment variables.

Precedence (lowest to highest): built-in defaults shipped in the YAML file
< environment variable overrides. API keys are a special case: they are
never read from the YAML file at all, only from the environment variable
named by a backend's ``api_key_env`` setting.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "default.yaml"
ENV_PREFIX = "BELLA"
ENV_NEST_SEP = "__"

# Config keys that must never hold a literal secret. Presence of these keys
# with a non-null scalar value in a YAML file is a hard error.
_FORBIDDEN_LITERAL_SECRET_KEYS = {"api_key", "apikey", "secret", "token"}


class ConfigError(ValueError):
    """Raised for invalid or unsafe configuration."""


def _reject_literal_secrets(node: Any, path: str = "") -> None:
    """Recursively walk the parsed YAML and refuse literal secret values."""
    if isinstance(node, dict):
        for key, value in node.items():
            key_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in _FORBIDDEN_LITERAL_SECRET_KEYS and value:
                raise ConfigError(
                    f"Config key '{key_path}' looks like a literal secret. "
                    "API keys and other secrets must be supplied via environment "
                    "variables only (see the corresponding '*_env' setting), "
                    "never written into a config file."
                )
            _reject_literal_secrets(value, key_path)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _reject_literal_secrets(item, f"{path}[{i}]")


def _apply_env_overrides(data: dict, prefix: str = ENV_PREFIX) -> dict:
    """Overlay environment variables of the form BELLA__SECTION__KEY=value.

    Nesting is expressed with a double underscore. Matching is case
    insensitive against the lowercase YAML keys; the resulting value is
    parsed as YAML scalar so booleans/ints/floats round-trip correctly.
    """
    result = data

    def set_path(d: dict, keys: list[str], value: Any) -> None:
        cur = d
        for k in keys[:-1]:
            nxt = cur.get(k)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[k] = nxt
            cur = nxt
        cur[keys[-1]] = value

    env_prefix = f"{prefix}{ENV_NEST_SEP}"
    for env_name, raw_value in os.environ.items():
        if not env_name.startswith(env_prefix):
            continue
        remainder = env_name[len(env_prefix):]
        if not remainder:
            continue
        keys = [part.lower() for part in remainder.split(ENV_NEST_SEP) if part]
        if not keys:
            continue
        try:
            parsed_value = yaml.safe_load(raw_value)
        except yaml.YAMLError:
            parsed_value = raw_value
        set_path(result, keys, parsed_value)

    return result


def resolve_api_key(backend_config: dict) -> str | None:
    """Resolve a backend's API key exclusively from its api_key_env variable."""
    env_var = backend_config.get("api_key_env")
    if not env_var:
        return None
    return os.environ.get(env_var)


def load_config(path: str | Path | None = None) -> dict:
    """Load configuration from YAML, validate, and apply env var overrides."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ConfigError(f"Config file must contain a YAML mapping at the top level: {config_path}")

    _reject_literal_secrets(data)
    data = _apply_env_overrides(data)
    _reject_literal_secrets(data)  # re-check in case an override injected one

    return data


def get_enabled_backends(config: dict) -> list[str]:
    """Return backend names with enabled: true, in config file order."""
    backends = config.get("backends", {}) or {}
    return [name for name, cfg in backends.items() if isinstance(cfg, dict) and cfg.get("enabled")]
