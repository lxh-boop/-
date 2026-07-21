from __future__ import annotations

import json

import pytest

from agent.memory import MemoryManager, MemoryRecord, MemoryScope, MemoryType


def test_phase14_memory_manager_remember_retrieve_and_forget(tmp_path) -> None:
    manager = MemoryManager(db_path=tmp_path / "memory.sqlite")
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

    context = manager.retrieve_for_context(user_id="u1", query="600519 drawdown", stock_codes=["600519"])

    assert context["items"]
    assert context["items"][0]["memory"]["memory_id"] == record.memory_id
    assert context["policy"]["memory_manager_has_no_commit_permission"] is True
    assert manager.forget(record.memory_id, user_id="u1") is True
    assert manager.retrieve(user_id="u1", query="600519") == []


def test_phase14_memory_manager_rejects_unconfirmed_long_term_user_fact(tmp_path) -> None:
    manager = MemoryManager(db_path=tmp_path / "memory.sqlite")

    with pytest.raises(ValueError, match="long_term_user_fact_requires_confirmation"):
        manager.remember(
            user_id="u1",
            content="Prefer speculative high-volatility names.",
            memory_type=MemoryType.SEMANTIC,
            memory_subtype="risk_preference",
            source_type="user_message",
            source_id="msg_1",
        )


def test_phase14_memory_manager_candidates_do_not_enter_long_term_store(tmp_path) -> None:
    manager = MemoryManager(db_path=tmp_path / "memory.sqlite")
    candidates = manager.remember_candidate("我更偏好稳健一点，记住这个偏好", user_id="u1")

    assert candidates
    assert manager.store.count(user_id="u1") == 0
    context = manager.retrieve_for_context(user_id="u1", query="稳健 偏好")
    encoded = json.dumps(context, ensure_ascii=False)

    assert "稳健" in encoded
    assert context["items"][0]["memory"]["memory_type"] == "WORKING"


def test_phase14_memory_manager_sanitizes_context_view(tmp_path) -> None:
    manager = MemoryManager(db_path=tmp_path / "memory.sqlite")
    record = manager.remember(
        MemoryRecord(
            user_id="u1",
            memory_type=MemoryType.WORKING,
            content="api_key=abc D:\\stock_daily_app\\data\\agent_quant.db",
            metadata={"confirmation_token": "secret", "raw_positions": [{"stock_code": "600519"}]},
        ),
        long_term=False,
    )

    context = manager.retrieve_for_context(user_id="u1", query="redacted", include_long_term=False)
    encoded = json.dumps(context, ensure_ascii=False)

    assert record.memory_id in encoded
    assert "confirmation_token" not in encoded
    assert "api_key" not in encoded
    assert "agent_quant.db" not in encoded
    assert "raw_positions" not in encoded


def test_phase14_memory_manager_has_no_commit_surface(tmp_path) -> None:
    manager = MemoryManager(db_path=tmp_path / "memory.sqlite")

    assert not hasattr(manager, "commit")
    assert not hasattr(manager, "execute")
    assert not hasattr(manager, "write_portfolio_state")
