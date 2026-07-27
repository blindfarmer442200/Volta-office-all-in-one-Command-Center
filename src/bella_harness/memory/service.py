"""Facade used by BellaHarness to recall and package approved memory."""

from __future__ import annotations

from typing import Callable

from bella_harness.memory.context import MemoryContextBuilder, MemoryContextEnvelope
from bella_harness.memory.recall import MemoryRecallEngine
from bella_harness.memory.store import MemoryStore


class MindTraceMemoryService:
    def __init__(
        self,
        store: MemoryStore,
        *,
        max_results: int = 5,
        min_score: int = 10,
        max_context_chars: int = 6_000,
        max_memory_chars: int = 1_200,
        is_safe_for_context: Callable[[str], bool] | None = None,
    ):
        self.recall_engine = MemoryRecallEngine(
            store,
            max_results=max_results,
            min_score=min_score,
            is_safe_for_context=is_safe_for_context,
        )
        self.context_builder = MemoryContextBuilder(
            max_context_chars=max_context_chars,
            max_memory_chars=max_memory_chars,
        )

    def build_prompt(self, request_text: str, *, mode: str = "default") -> MemoryContextEnvelope:
        recall = self.recall_engine.recall(request_text, mode=mode)
        return self.context_builder.build(request_text, recall)
