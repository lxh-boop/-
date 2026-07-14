from __future__ import annotations

import json
import time

from agent.memory import MemoryRecord, MemoryType, WorkingMemory


def test_phase14_working_memory_ttl_and_user_isolation() -> None:
    memory = WorkingMemory(default_ttl_seconds=1)
    u1 = memory.put(
        MemoryRecord(
            user_id="u1",
            content="current task mentions 600519 risk",
            stock_codes=["600519"],
            topics=["risk"],
            importance=0.8,
        )
    )
    memory.put(MemoryRecord(user_id="u2", content="u2 private 000001", stock_codes=["000001"]))

    assert memory.get(u1.memory_id, user_id="u1") is not None
    assert memory.get(u1.memory_id, user_id="u2") is None
    assert [item.memory_id for item in memory.search(user_id="u1", query="600519 risk")] == [u1.memory_id]

    time.sleep(1.1)
    assert memory.get(u1.memory_id, user_id="u1") is None


def test_phase14_working_memory_sanitizes_secret_and_large_objects() -> None:
    memory = WorkingMemory(default_ttl_seconds=60)
    record = memory.put(
        {
            "user_id": "u1",
            "memory_type": MemoryType.WORKING,
            "content": "api_key=abc D:\\stock_daily_app\\data\\agent_quant.db",
            "metadata": {
                "confirmation_token": "secret",
                "raw_positions": [{"stock_code": "600519", "quantity": 100}],
            },
        }
    )
    encoded = json.dumps(record.to_dict(), ensure_ascii=False)

    assert "confirmation_token" not in encoded
    assert "api_key" not in encoded
    assert "agent_quant.db" not in encoded
    assert "raw_positions" not in encoded
    assert record.metadata["positions_summary"]["count"] == 1


def test_phase14_working_memory_delete_and_filter() -> None:
    memory = WorkingMemory(default_ttl_seconds=60)
    first = memory.put(MemoryRecord(user_id="u1", content="alpha", topics=["topic-a"], importance=0.9))
    second = memory.put(MemoryRecord(user_id="u1", content="beta", topics=["topic-b"], importance=0.2))

    results = memory.search(user_id="u1", topics=["topic-a"], min_importance=0.5)

    assert [item.memory_id for item in results] == [first.memory_id]
    assert memory.delete(second.memory_id, user_id="u1") is True
    assert memory.get(second.memory_id, user_id="u1", include_expired=True) is None
