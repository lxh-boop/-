from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from agent.memory import LayeredMemoryService
from agent.runtime import AgentRuntimeRecorder
from agent.session.pending_action_store import save_pending_plan
from app.pages.ai_agent import (
    _build_plan_card,
    _clear_chat,
    _delete_conversation,
    _init_chat,
    _list_active_conversations,
    _load_conversation_messages,
    _phase51_conversation_title,
    _phase51_plan_summary_rows,
    _phase51_public_messages,
    _pending_plans_for_conversation,
    _persist_conversation_message,
    _redact_ui_payload,
    _rename_conversation,
    _switch_conversation,
    _technical_plan_details,
    render_ai_agent_page,
    st,
)
from database.repositories import AgentRepository


def _reset_state() -> None:
    try:
        st.session_state.clear()
    except Exception:
        st.session_state = {}


def test_phase5_conversation_create_switch_rename_delete_persists(tmp_path) -> None:
    _reset_state()
    db_path = str(tmp_path / "agent.db")
    messages, conv1 = _init_chat("u1", db_path)
    assert conv1
    assert messages[0]["role"] == "assistant"

    _persist_conversation_message(
        user_id="u1",
        conversation_id=conv1,
        role="user",
        content="first persistent message",
        db_path=db_path,
        language="zh",
    )
    assert _rename_conversation("u1", conv1, "renamed conversation", db_path)

    _clear_chat("u1", db_path)
    conv2 = st.session_state["ai_agent_chat_session_id::u1"]
    assert conv2 != conv1
    assert "first persistent message" not in str(st.session_state["ai_agent_chat_messages::u1"])

    _switch_conversation("u1", conv1, db_path)
    restored = st.session_state["ai_agent_chat_messages::u1"]
    assert any(row["content"] == "first persistent message" for row in restored)
    assert _delete_conversation("u1", conv1, db_path)
    active_ids = {row["conversation_id"] for row in _list_active_conversations("u1", db_path)}
    assert conv1 not in active_ids
    assert conv2 in active_ids


def test_phase5_messages_restore_agent_result_and_run_id(tmp_path) -> None:
    _reset_state()
    db_path = str(tmp_path / "agent.db")
    _, conv = _init_chat("u1", db_path)
    result = {"success": True, "run_id": "run_123", "answer": "done"}
    _persist_conversation_message(
        user_id="u1",
        conversation_id=conv,
        role="assistant",
        content="done",
        db_path=db_path,
        language="zh",
        agent_result=result,
    )

    loaded = _load_conversation_messages("u1", conv, db_path, language="zh")

    assert loaded[-1]["agent_result"]["run_id"] == "run_123"
    assert loaded[-1]["run_id"] == "run_123"


def test_phase5_new_conversation_has_no_temporary_context_but_memory_crosses_sessions(tmp_path) -> None:
    _reset_state()
    db_path = str(tmp_path / "agent.db")
    service = LayeredMemoryService(db_path)
    service.remember_memory(
        user_id="u1",
        content="Prefer evidence-first explanations.",
        memory_type="preference",
        source_run_id="run_pref",
        source_type="confirmed_user_preference",
        source_id="msg_pref",
        user_confirmed=True,
    )
    _, conv1 = _init_chat("u1", db_path)
    _persist_conversation_message(
        user_id="u1",
        conversation_id=conv1,
        role="user",
        content="temporary one-off wording",
        db_path=db_path,
        language="zh",
    )

    _clear_chat("u1", db_path)
    conv2 = st.session_state["ai_agent_chat_session_id::u1"]

    assert conv2 != conv1
    assert "temporary one-off wording" not in str(st.session_state["ai_agent_chat_messages::u1"])
    assert service.search_memories(user_id="u1", query="evidence explanations", memory_type="preference")


def test_phase5_pending_plans_are_filtered_by_conversation(tmp_path) -> None:
    _reset_state()
    db_path = str(tmp_path / "agent.db")
    output_dir = str(tmp_path / "outputs")
    repo = AgentRepository(db_path)
    repo.upsert_conversation({"conversation_id": "conv_a", "user_id": "u1", "title": "A"})
    repo.upsert_conversation({"conversation_id": "conv_b", "user_id": "u1", "title": "B"})
    run_a = AgentRuntimeRecorder(user_id="u1", goal="a", db_path=db_path, session_id="conv_a")
    run_b = AgentRuntimeRecorder(user_id="u1", goal="b", db_path=db_path, session_id="conv_b")
    save_pending_plan(
        "u1",
        {
            "plan_id": "agent_plan_a",
            "run_id": run_a.run_id,
            "intent": "execute_adjust_position",
            "operation_type": "execute_adjust_position",
            "confirmation_status": "pending",
            "execution_status": "pending",
        },
        output_dir=output_dir,
    )
    save_pending_plan(
        "u1",
        {
            "plan_id": "agent_plan_b",
            "run_id": run_b.run_id,
            "intent": "execute_adjust_position",
            "operation_type": "execute_adjust_position",
            "confirmation_status": "pending",
            "execution_status": "pending",
        },
        output_dir=output_dir,
    )

    plans = _pending_plans_for_conversation("u1", output_dir, db_path, "conv_a")

    assert [plan["plan_id"] for plan in plans] == ["agent_plan_a"]


def test_phase5_plan_card_hides_internal_fields_and_maps_business_fields() -> None:
    expires = (datetime.now() + timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
    plan = {
        "plan_id": "agent_plan_1",
        "intent": "execute_adjust_position",
        "operation_type": "execute_adjust_position",
        "confirmation_token": "secret_token",
        "confirmation_token_hash": "secret_hash",
        "plan_hash": "internal_hash",
        "snapshot_id": "snapshot_1",
        "business_state_version": "state_1",
        "confirmation_status": "pending",
        "execution_status": "pending",
        "expires_at": expires,
        "before_state_summary": {"stock_code": "000001", "quantity": 1000},
        "proposed_changes": [{"stock_code": "000001", "stock_name": "Ping An", "quantity_delta": -100}],
        "after_state_preview": {"stock_code": "000001", "quantity": 900},
        "warnings": ["lot size must be revalidated"],
    }

    card = _build_plan_card(plan)
    technical = _technical_plan_details(plan)

    assert card["operation_type"]
    assert "000001" in card["target"]
    assert "lot size" in card["risks"]
    assert "confirmation_token" not in technical
    assert "plan_hash" not in technical
    assert "snapshot_id" not in technical
    assert "secret_token" not in str(_redact_ui_payload(plan))


def test_phase5_expired_plan_card_requires_regeneration() -> None:
    expired = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    card = _build_plan_card(
        {
            "intent": "enable_strategy",
            "operation_type": "enable_strategy",
            "confirmation_status": "pending",
            "execution_status": "pending",
            "expires_at": expired,
            "proposed_changes": [{"strategy_name": "demo", "version": "v1"}],
        }
    )

    assert card["stage"] == "已过期"


def test_phase51_source_has_no_literal_placeholder() -> None:
    source = Path("app/pages/ai_agent.py").read_text(encoding="utf-8")

    assert "????" not in source


def test_phase51_current_render_uses_page_columns_not_global_sidebar() -> None:
    names = set(render_ai_agent_page.__code__.co_names)
    constants = "\n".join(str(item) for item in render_ai_agent_page.__code__.co_consts)

    assert "sidebar" not in names
    assert "_phase51_render_developer_details" in names
    assert "会话" in constants
    assert "待确认计划" in constants


def test_phase51_conversation_title_hides_raw_conversation_id() -> None:
    title = _phase51_conversation_title(
        {
            "conversation_id": "conv_secret_123",
            "title": "New conversation",
            "updated_at": "2026-07-02 19:00:00",
        },
        language="zh",
    )

    assert title == "新会话"
    assert "conv_secret_123" not in title
    assert "New conversation" not in title


def test_phase51_welcome_is_hidden_after_real_messages() -> None:
    messages = [
        {"role": "assistant", "content": "hello", "agent_result": None},
        {"role": "user", "content": "查看当前持仓", "agent_result": None},
        {"role": "assistant", "content": "当前持仓如下", "agent_result": {"success": True}},
    ]

    public_messages = _phase51_public_messages(messages, "zh")

    assert len(public_messages) == 3
    assert any(row["role"] == "user" for row in public_messages)


def test_phase51_plan_summary_uses_business_labels() -> None:
    expires = (datetime.now() + timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
    rows = _phase51_plan_summary_rows(
        {
            "plan_id": "agent_plan_1",
            "intent": "strategy_change",
            "operation_type": "strategy_change",
            "confirmation_status": "pending",
            "execution_status": "pending",
            "expires_at": expires,
            "before_state_summary": {
                "enabled_strategies": [
                    {
                        "strategy_name": "old",
                        "version": "v1",
                        "module_path": "internal.module.path",
                    }
                ]
            },
            "proposed_changes": [{"strategy_name": "demo", "version": "v2"}],
            "after_state_preview": {"strategy_name": "demo"},
            "warnings": ["需要重新校验"],
            "plan_hash": "internal",
            "confirmation_token_hash": "secret",
            "snapshot_id": "snapshot",
        }
    )
    labels = [row["label"] for row in rows]
    values = " ".join(str(row["value"]) for row in rows)

    assert labels == [
        "操作类型",
        "影响对象",
        "修改前",
        "拟执行变更",
        "修改后预览",
        "变化原因",
        "风险提示",
        "预计影响",
        "是否可撤销",
        "计划有效期",
    ]
    assert "策略变更" in values
    assert "plan_hash" not in values
    assert "confirmation_token_hash" not in values
    assert "snapshot_id" not in values
    assert "module_path" not in values
    assert "internal.module.path" not in values
