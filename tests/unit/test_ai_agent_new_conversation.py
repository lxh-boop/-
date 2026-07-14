from __future__ import annotations

from app.pages.ai_agent import (
    _clear_chat,
    _delete_conversation,
    _init_chat,
    _list_active_conversations,
    _persist_conversation_message,
    st,
)


def _reset_state() -> None:
    try:
        st.session_state.clear()
    except Exception:
        st.session_state = {}


def test_new_conversation_creates_new_id_and_preserves_old_history(tmp_path) -> None:
    _reset_state()
    db_path = str(tmp_path / "agent.db")
    _, conv_a = _init_chat("u1", db_path)
    _persist_conversation_message(
        user_id="u1",
        conversation_id=conv_a,
        role="user",
        content="message in A",
        db_path=db_path,
        language="zh",
    )

    _clear_chat("u1", db_path)
    conv_b = st.session_state["ai_agent_chat_session_id::u1"]
    visible_messages = st.session_state["ai_agent_chat_messages::u1"]
    active_ids = {row["conversation_id"] for row in _list_active_conversations("u1", db_path)}

    assert conv_b != conv_a
    assert conv_a in active_ids
    assert conv_b in active_ids
    assert "message in A" not in str(visible_messages)


def test_delete_conversation_archives_only_target_conversation(tmp_path) -> None:
    _reset_state()
    db_path = str(tmp_path / "agent.db")
    _, conv_a = _init_chat("u1", db_path)
    _persist_conversation_message(
        user_id="u1",
        conversation_id=conv_a,
        role="user",
        content="keep this history",
        db_path=db_path,
        language="zh",
    )

    _clear_chat("u1", db_path)
    conv_b = st.session_state["ai_agent_chat_session_id::u1"]
    _persist_conversation_message(
        user_id="u1",
        conversation_id=conv_b,
        role="user",
        content="archive this history",
        db_path=db_path,
        language="zh",
    )

    assert _delete_conversation("u1", conv_b, db_path)
    active_ids = {row["conversation_id"] for row in _list_active_conversations("u1", db_path)}

    assert conv_a in active_ids
    assert conv_b not in active_ids
