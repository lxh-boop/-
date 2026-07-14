from __future__ import annotations

from agent.memory import (
    LayeredMemoryService,
    MemoryImportanceScorer,
    MemoryRecord,
    MemoryScope,
    MemoryType,
    MemoryVisibility,
)


def test_phase14_memory_record_roundtrip_and_legacy_mapping() -> None:
    record = MemoryRecord(
        user_id="u1",
        memory_type=MemoryType.SEMANTIC,
        memory_subtype="preference",
        scope=MemoryScope.USER,
        visibility=MemoryVisibility.LLM_VISIBLE,
        content="Prefer conservative portfolio explanations for 600519.",
        topics=["risk"],
        stock_codes=["600519.SH"],
        source_type="confirmed_user_preference",
        source_id="msg_1",
        metadata={"user_confirmed": True},
    )

    encoded = record.to_dict()
    restored = MemoryRecord.from_dict(encoded)
    legacy = restored.to_legacy_memory_item()

    assert restored.memory_type == MemoryType.SEMANTIC
    assert restored.stock_codes == ["600519"]
    assert legacy["memory_type"] == "preference"
    assert legacy["metadata"]["phase14_memory_type"] == "SEMANTIC"


def test_phase14_memory_record_from_existing_db_row() -> None:
    row = {
        "memory_id": "mem_1",
        "user_id": "u1",
        "memory_type": "risk_preference",
        "content": "Prefer lower drawdown.",
        "topics_json": ["risk"],
        "stock_codes_json": ["000001"],
        "importance": 0.9,
        "metadata_json": {"confidence": 0.7, "source_run_id": "run_1"},
    }

    record = MemoryRecord.from_legacy_memory_item(row)

    assert record.memory_type == MemoryType.SEMANTIC
    assert record.memory_subtype == "risk_preference"
    assert record.run_id == "run_1"
    assert record.confidence == 0.7


def test_phase14_importance_scorer_prioritizes_confirmed_semantic_memory() -> None:
    scorer = MemoryImportanceScorer()
    confirmed = MemoryRecord(
        memory_type=MemoryType.SEMANTIC,
        memory_subtype="preference",
        source_type="confirmed_user_preference",
        metadata={"user_confirmed": True},
        importance=0.9,
        confidence=0.9,
        stock_codes=["600519"],
    )
    working = MemoryRecord(memory_type=MemoryType.WORKING, importance=0.5, confidence=0.5)

    assert scorer.score(confirmed) > scorer.score(working)


def test_phase14_agent_memory_package_preserves_legacy_imports(tmp_path) -> None:
    service = LayeredMemoryService(tmp_path / "agent.db")

    record = service.remember_memory(
        user_id="u1",
        content="Prefer concise risk summaries.",
        memory_type="preference",
        source_run_id="run_1",
        source_type="confirmed_user_preference",
        source_id="msg_1",
        user_confirmed=True,
    )

    assert record["memory_id"].startswith("mem_")
    assert service.search_memories(user_id="u1", query="risk summaries", memory_type="preference")
