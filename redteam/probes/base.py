"""Shared data model for red-team probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Expectation = Literal["block", "allow"]


@dataclass(frozen=True)
class Probe:
    id: str
    agent: str
    technique: str
    prompt: str
    expect: Expectation
    description: str = ""
