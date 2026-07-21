from __future__ import annotations

import json

from agent.memory import (
    MemoryManager,
    MemoryScope,
    MemoryType,
    build_memory_safe_summary,
    build_memory_store_health_summary,
)
from agent.tool_engine import execute_tool, get_tool_registry_v2
from app.pages.system_monitor import _memory_store_health_rows


def test_phase14_memory_tools_are_registered_and_read_only(tmp_path) -> None:
    registry = get_tool_registry_v2()

    search_def = registry.get("memory.search")
    summary_def = registry.get("memory.get_summary")

    assert search_def is not None
    assert summary_def is not None
    assert search_def.operation_type == "read"
    assert summary_def.operation_type == "read"
    assert search_def.requires_approval is False


def test_phase14_memory_search_and_summary_tools(tmp_path) -> None:
    manager = MemoryManager(db_path=tmp_path / "memory" / "memory_store.sqlite")
    record = manager.remember(
        user_id="u1",
        content="Prefer lower drawdown explanations for 600519.",
        memory_type=MemoryType.SEMANTIC,
        memory_subtype="preference",
        scope=MemoryScope.USER,
        source_type="confirmed_user_preference",
        source_id="msg_1",
        topics=["risk"],
        stock_codes=["600519"],
        metadata={"user_confirmed": True},
        user_confirmed=True,
    )

    result = execute_tool(
        "memory.search",
        {"user_id": "u1", "query": "600519 drawdown", "stock_codes": ["600519"]},
        context={"user_id": "u1", "output_dir": str(tmp_path)},
    )
    summary = execute_tool(
        "memory.get_summary",
        {"user_id": "u1"},
        context={"user_id": "u1", "output_dir": str(tmp_path)},
    )
    encoded = json.dumps(result.to_dict(), ensure_ascii=False)

    assert result.success is True
    assert record.memory_id in encoded
    assert result.data["not_committed"] is True
    assert summary.success is True
    assert summary.data["user_count"] == 1
    assert "confirmation_token" not in encoded


def test_phase14_memory_ui_helpers_are_safe(tmp_path) -> None:
    manager = MemoryManager(db_path=tmp_path / "memory" / "memory_store.sqlite")
    manager.remember(
        user_id="u1",
        content="Prefer evidence-first answers.",
        memory_type=MemoryType.SEMANTIC,
        memory_subtype="preference",
        scope=MemoryScope.USER,
        source_type="confirmed_user_preference",
        source_id="msg_1",
        metadata={"user_confirmed": True},
        user_confirmed=True,
    )

    summary = build_memory_store_health_summary(user_id="u1", output_dir=tmp_path)
    rows = _memory_store_health_rows(summary)
    safe_text = build_memory_safe_summary(user_id="u1", output_dir=tmp_path)
    encoded = json.dumps({"rows": rows.to_dict("records"), "safe_text": safe_text}, ensure_ascii=False)

    assert summary["user_count"] == 1
    assert "Memory safe summary" in safe_text
    assert "agent_quant.db" not in encoded
    assert "confirmation_token" not in encoded
