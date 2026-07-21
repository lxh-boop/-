from __future__ import annotations

from agent.context import ContextManager, build_agent_context
from agent.memory import MemoryManager, MemoryScope, MemoryType


def test_phase14_context_manager_reads_memory_refs(tmp_path) -> None:
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

    context = ContextManager(output_dir=tmp_path).create_initial_context(
        user_id="u1",
        query="600519 drawdown",
        conversation_id="conv_1",
        run_id="run_1",
    )

    assert record.memory_id in context.memory_context.memory_refs
    assert context.memory_context.metadata["phase14_memory"]["item_count"] == 1


def test_phase14_legacy_context_builder_includes_phase14_memory_view(tmp_path) -> None:
    manager = MemoryManager(db_path=tmp_path / "memory" / "memory_store.sqlite")
    record = manager.remember(
        user_id="u1",
        content="Prefer evidence-first answers about 600519.",
        memory_type=MemoryType.SEMANTIC,
        memory_subtype="preference",
        scope=MemoryScope.USER,
        source_type="confirmed_user_preference",
        source_id="msg_1",
        stock_codes=["600519"],
        metadata={"user_confirmed": True},
        user_confirmed=True,
    )

    built = build_agent_context(
        query="600519 evidence",
        user_id="u1",
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
        run_id="run_1",
    )

    encoded = str([section.to_dict() for section in built.sections])
    assert "phase14_memory" in encoded
    assert record.memory_id in encoded
    assert "confirmation_token" not in encoded
