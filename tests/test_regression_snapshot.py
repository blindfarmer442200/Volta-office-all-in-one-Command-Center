"""Regression snapshot: every probe's classification is pinned to a committed
snapshot (redteam/snapshots/probe_outcomes.json). A rule change that silently
reclassifies a probe -- even one that keeps the suite at 115/115 clean -- will
fail this test, forcing the snapshot to be reviewed and updated deliberately.

To regenerate after an intentional change:
    python -m redteam.snapshot_tool --write
"""

import json
from pathlib import Path

import pytest

from bella_harness.deterministic.engine import DeterministicEngine
from redteam.probes import ALL_PROBES

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "redteam" / "snapshots" / "probe_outcomes.json"


def _current_outcomes() -> dict:
    engine = DeterministicEngine()
    outcomes = {}
    for probe in ALL_PROBES:
        decision = engine.evaluate(probe.prompt)
        outcomes[probe.id] = {
            "expect": probe.expect,
            "action": decision.action.value,
            "category": decision.category,
            "severity": decision.severity,
        }
    return outcomes


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_snapshot_exists(snapshot):
    assert snapshot, "snapshot file is empty or missing"


def test_probe_ids_match_snapshot(snapshot):
    current_ids = {p.id for p in ALL_PROBES}
    snapshot_ids = set(snapshot)
    assert current_ids == snapshot_ids, (
        f"probe set drifted from snapshot; "
        f"added={sorted(current_ids - snapshot_ids)} removed={sorted(snapshot_ids - current_ids)}"
    )


def test_every_probe_classification_matches_snapshot(snapshot):
    current = _current_outcomes()
    drift = {pid: (snapshot[pid], current[pid]) for pid in current if snapshot.get(pid) != current[pid]}
    assert not drift, f"classification drifted from snapshot for: {sorted(drift)}"
