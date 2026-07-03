"""Verify the README quickstart commands actually work as documented.

Only the commands that resolve deterministically (no LLM backend) are asserted
end-to-end, since CI has no Ollama server. The free-form 'ask' example in the
README is explicitly documented as needing a backend, so it is not run here.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


def _run(args, extra_path=""):
    pythonpath = f"{SRC}{extra_path}"
    env = {**os.environ, "PYTHONPATH": pythonpath}
    return subprocess.run(
        [sys.executable, "-m", "bella_harness.cli", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_readme_exists_and_has_quickstart():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Quickstart" in readme


def test_ask_greeting_matches_readme():
    result = _run(["ask", "hello"])
    assert result.returncode == 0, result.stderr
    assert "Hello" in result.stdout


def test_ask_arithmetic_matches_readme():
    result = _run(["ask", "2 + 2"])
    assert result.returncode == 0, result.stderr
    assert "4" in result.stdout


def test_redteam_command_matches_readme():
    # README documents this as fully offline; PYTHONPATH needs src + repo root.
    result = _run(["redteam"], extra_path=f"{os.pathsep}{REPO_ROOT}")
    assert result.returncode == 0, result.stderr
    assert "115/115" in result.stdout
