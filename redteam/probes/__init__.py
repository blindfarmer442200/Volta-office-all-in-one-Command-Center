"""Aggregates every probe module into a single ordered list."""

from __future__ import annotations

from redteam.probes import advanced, benign, encoding, escalation, exfiltration, injection, jailbreak, multilingual
from redteam.probes.base import Probe

ALL_PROBES: list[Probe] = [
    *injection.PROBES,
    *jailbreak.PROBES,
    *escalation.PROBES,
    *exfiltration.PROBES,
    *encoding.PROBES,
    *multilingual.PROBES,
    *advanced.PROBES,
    *benign.PROBES,
]


def specialist_agents() -> list[str]:
    """Return the distinct specialist agent names covered by ALL_PROBES."""
    seen: list[str] = []
    for probe in ALL_PROBES:
        if probe.agent not in seen:
            seen.append(probe.agent)
    return seen
