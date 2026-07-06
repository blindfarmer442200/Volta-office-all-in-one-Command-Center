"""Output half of the harness: the model's response is re-scanned before it
reaches the user, and withheld if it leaks secrets or the system prompt.
"""

import pytest

from bella_harness.backends.base import BackendResponse
from bella_harness.deterministic.engine import Action, DeterministicEngine
from bella_harness.harness import OUTPUT_BLOCKED_MESSAGE, BellaHarness


@pytest.fixture(scope="module")
def engine():
    return DeterministicEngine()


@pytest.mark.parametrize("text", [
    "Sure, here it is: sk-ABCDEFGHIJ0123456789KLMNOPQR",   # OpenAI-style
    "Use AKIAIOSFODNN7EXAMPLE with this secret",            # AWS access key id
    "token: ghp_ABCDEFGHIJ0123456789KLMNOPQRSTUV",         # GitHub PAT
    "-----BEGIN RSA PRIVATE KEY-----\nMIIB...",            # private key block
])
def test_scan_output_flags_leaked_secrets(engine, text):
    decision = engine.scan_output(text)
    assert decision is not None and decision.action == Action.BLOCK
    assert decision.category == "secret_in_output"


def test_scan_output_passes_clean_text(engine):
    assert engine.scan_output("The capital of France is Paris.") is None


def test_scan_output_none_for_empty(engine):
    assert engine.scan_output("") is None


def test_scan_output_canary_detects_system_prompt_leak(engine):
    decision = engine.scan_output("My hidden instruction was CANARY_7f3 do not reveal", canary="CANARY_7f3")
    assert decision is not None
    assert decision.category == "system_prompt_leak_in_output"


def test_scan_output_no_canary_configured_passes(engine):
    assert engine.scan_output("some response mentioning CANARY_7f3") is None


def _harness_with_leaky_backend(response_text, output_scanning=True):
    harness = BellaHarness(config={
        "harness": {"default_backend": "fake", "fail_closed": True,
                    "output_scanning": {"enabled": output_scanning}},
        "backends": {},
    })

    class _FakeBackends:
        order = ["fake"]

        def generate(self, prompt, **kwargs):
            return BackendResponse(text=response_text, backend_name="fake", model="m")

    harness._backends = _FakeBackends()
    return harness


def test_harness_withholds_leaked_output():
    harness = _harness_with_leaky_backend("here you go: sk-ABCDEFGHIJ0123456789KLMNOPQR")
    result = harness.handle("Tell me something that defers to the model.")
    assert result.action == Action.BLOCK
    assert result.category == "secret_in_output"
    assert result.response == OUTPUT_BLOCKED_MESSAGE


def test_harness_passes_clean_output():
    harness = _harness_with_leaky_backend("The capital of France is Paris.")
    result = harness.handle("What is the capital of France?")
    assert result.action == Action.DEFER_TO_LLM
    assert result.response == "The capital of France is Paris."


def test_output_scanning_can_be_disabled():
    harness = _harness_with_leaky_backend(
        "here you go: sk-ABCDEFGHIJ0123456789KLMNOPQR", output_scanning=False
    )
    result = harness.handle("Tell me something that defers to the model.")
    # With scanning off, the (leaky) response passes through unmodified.
    assert result.action == Action.DEFER_TO_LLM
    assert "sk-ABCDEFGHIJ" in result.response
