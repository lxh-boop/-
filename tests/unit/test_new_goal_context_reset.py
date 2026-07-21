from __future__ import annotations

from agent.memory.conversation_state_manager import (
    ConversationMessage,
    RELATION_NEW_GOAL,
    resolve_turn_from_messages,
)


def test_new_goal_does_not_inherit_previous_goal_or_history():
    history = [
        ConversationMessage(role="user", content="查看我的持仓", message_id="u1"),
        ConversationMessage(
            role="assistant",
            content="当前持仓如下",
            message_id="a1",
            run_id="r1",
            agent_result={
                "user_goal": {"action": "query", "objects": ["portfolio"]},
                "data": {"stock_code": "600000"},
            },
        ),
    ]
    turn = resolve_turn_from_messages(
        "分析股票 600519",
        conversation_id="c1",
        messages=history,
    )
    assert turn.relation_type == RELATION_NEW_GOAL
    assert turn.previous_user_goal == {}
    assert turn.previous_result_summary == ""
    assert turn.inherited_parameters == {}
    assert turn.active_entities == {}
    assert turn.reference_turn_ids == []
    assert turn.recent_messages == []
