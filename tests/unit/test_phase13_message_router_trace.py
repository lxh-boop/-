from __future__ import annotations

from agent.communication import (
    AgentMessage,
    MessageRouter,
    MessageTrace,
    MessageType,
    MessageVisibility,
    build_message_trace,
)


def test_message_router_returns_expected_channels() -> None:
    router = MessageRouter()

    user_env = router.route_message(
        AgentMessage(message_type=MessageType.USER_REQUEST, sender="user", receiver="supervisor")
    )
    tool_env = router.route_message(
        AgentMessage(message_type=MessageType.TOOL_CALL_REQUESTED, sender="executor", receiver="tool_executor")
    )
    approval_env = router.route_message(
        AgentMessage(message_type=MessageType.APPROVAL_REQUESTED, sender="risk_operation", receiver="ui")
    )
    final_env = router.route_message(
        AgentMessage(message_type=MessageType.FINAL_REPORT, sender="reporting", receiver="ui")
    )

    assert user_env.route == ["executor"]
    assert tool_env.route == ["tool_executor"]
    assert tool_env.visibility == MessageVisibility.TOOL_ONLY
    assert "write_gateway" in approval_env.route
    assert "ui" in approval_env.route
    assert final_env.route == ["ui", "audit"]


def test_message_trace_builds_edges_and_refs() -> None:
    messages = [
        AgentMessage(
            message_id="msg_parent",
            run_id="run1",
            task_id="task_parent",
            sender="supervisor",
            receiver="tool_executor",
            message_type=MessageType.TASK_PLANNED,
        ),
        AgentMessage(
            message_id="msg_child",
            run_id="run1",
            task_id="task_child",
            parent_task_id="task_parent",
            sender="tool_executor",
            receiver="supervisor",
            message_type=MessageType.TOOL_RESULT_RECEIVED,
            tool_call_refs=[{"tool_call_id": "call1", "tool_name": "ranking"}],
            artifact_refs=[{"artifact_id": "artifact1", "artifact_type": "tool_result"}],
            approval_refs=[{"plan_id": "plan1"}],
            warnings=["warning1"],
        ),
    ]

    trace = build_message_trace(messages, trace_id="trace1")
    payload = trace.to_dict()

    assert isinstance(trace, MessageTrace)
    assert payload["trace_id"] == "trace1"
    assert payload["run_id"] == "run1"
    assert payload["parent_child_edges"][0]["parent_task_id"] == "task_parent"
    assert payload["tool_call_edges"][0]["tool_call_id"] == "call1"
    assert payload["artifact_edges"][0]["artifact_id"] == "artifact1"
    assert payload["approval_edges"][0]["plan_id"] == "plan1"
    assert payload["warnings"] == ["warning1"]
