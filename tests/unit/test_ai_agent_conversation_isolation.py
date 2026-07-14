from __future__ import annotations

from app.pages.ai_agent import (
    _init_chat,
    _persist_conversation_message,
    _phase15_lazy_detail_key,
    _phase8_developer_details_key,
    _phase8_set_message_limit,
    _switch_conversation,
    st,
)


def _reset_state() -> None:
    try:
        st.session_state.clear()
    except Exception:
        st.session_state = {}


def test_switch_conversation_loads_only_target_messages_and_resets_lazy_state(tmp_path) -> None:
    _reset_state()
    db_path = str(tmp_path / "agent.db")
    _, conv_a = _init_chat("u1", db_path)
    _persist_conversation_message(
        user_id="u1",
        conversation_id=conv_a,
        role="user",
        content="only in A",
        db_path=db_path,
        language="zh",
    )
    from app.pages.ai_agent import _clear_chat

    _clear_chat("u1", db_path)
    conv_b = st.session_state["ai_agent_chat_session_id::u1"]
    _persist_conversation_message(
        user_id="u1",
        conversation_id=conv_b,
        role="user",
        content="only in B",
        db_path=db_path,
        language="zh",
    )

    st.session_state[_phase8_developer_details_key("u1", conv_a)] = True
    st.session_state[_phase15_lazy_detail_key("react_summary", "u1", "run_a")] = True
    _phase8_set_message_limit("u1", conv_a, 20)
    _phase8_set_message_limit("u1", conv_b, 10)

    _switch_conversation("u1", conv_a, db_path)
    visible_a = st.session_state["ai_agent_chat_messages::u1"]
    assert any(row["content"] == "only in A" for row in visible_a)
    assert "only in B" not in str(visible_a)
    assert _phase8_developer_details_key("u1", conv_a) not in st.session_state
    assert _phase15_lazy_detail_key("react_summary", "u1", "run_a") not in st.session_state

    _switch_conversation("u1", conv_b, db_path)
    visible_b = st.session_state["ai_agent_chat_messages::u1"]
    assert any(row["content"] == "only in B" for row in visible_b)
    assert "only in A" not in str(visible_b)
