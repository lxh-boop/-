from __future__ import annotations

from agent.memory.memory_retriever import MemoryRetriever
from agent.memory.memory_types import MemoryRecord, MemoryStatus, MemoryType


class FakeStore:
    def list_records(self, **kwargs):
        return [
            MemoryRecord(
                memory_id=f"m{i}",
                user_id="u1",
                memory_type=MemoryType.SEMANTIC,
                status=MemoryStatus.ACTIVE,
                summary=f"memory {i}",
                content=f"memory {i}",
                importance=0.5,
                confidence=0.8,
            )
            for i in range(100)
        ][: kwargs.get("limit", 100)]


def test_candidate_top_n_is_not_fixed_context_top_k():
    retriever = MemoryRetriever(store=FakeStore())
    candidates = retriever.retrieve(
        user_id="u1",
        query="memory",
        candidate_top_n=40,
    )
    assert len(candidates) == 40
