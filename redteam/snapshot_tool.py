"""Regenerate the committed probe-outcome snapshot.

    python -m redteam.snapshot_tool --write     # rewrite the snapshot
    python -m redteam.snapshot_tool             # print without writing

Run this only after an *intentional* change to the rules/engine, then review
the diff before committing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bella_harness.deterministic.engine import DeterministicEngine
from redteam.probes import ALL_PROBES

SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshots" / "probe_outcomes.json"


def build_snapshot() -> dict:
    engine = DeterministicEngine()
    snapshot = {}
    for probe in ALL_PROBES:
        decision = engine.evaluate(probe.prompt)
        snapshot[probe.id] = {
            "expect": probe.expect,
            "action": decision.action.value,
            "category": decision.category,
            "severity": decision.severity,
        }
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write the snapshot to disk.")
    args = parser.parse_args()

    snapshot = build_snapshot()
    text = json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    if args.write:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {len(snapshot)} entries to {SNAPSHOT_PATH}")
    else:
        print(text)


if __name__ == "__main__":
    main()
