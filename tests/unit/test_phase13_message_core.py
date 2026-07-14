from __future__ import annotations

import json

from agent.communication import (
    AgentMessage,
    MessageEnvelope,
    MessagePriority,
    MessageStatus,
    MessageType,
    MessageVisibility,
    MessageWindow,
)


def test_agent_message_and_envelope_are_serializable() -> None:
    message = AgentMessage(
        conversation_id="conv1",
        run_id="run1",
        task_id="task1",
        parent_task_id="root",
        sender="supervisor",
        receiver="tool_executor",
        message_type=MessageType.TOOL_CALL_REQUESTED,
        status=MessageStatus.QUEUED,
        priority=MessagePriority.HIGH,
        payload={"tool_name": "ranking", "summary": "read latest ranking"},
        payload_schema="tool_call.v1",
        context_refs=[{"context_id": "ctx1"}],
        artifact_refs=[{"artifact_id": "artifact1"}],
        approval_refs=[{"plan_id": "plan1", "token_present": True}],
        tool_call_refs=[{"tool_call_id": "call1"}],
        source_refs=[{"source_id": "src1"}],
        warnings=["warning1"],
        metadata={"safe": "ok"},
    )
    envelope = MessageEnvelope(
        message=message,
        route=["supervisor", "tool_executor"],
        visibility=MessageVisibility.TOOL_ONLY,
        delivery_status=MessageStatus.DELIVERED,
        trace_id="trace1",
    )

    payload = envelope.to_dict()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["message"]["message_type"] == "TOOL_CALL_REQUESTED"
    assert payload["message"]["status"] == "QUEUED"
    assert payload["visibility"] == "TOOL_ONLY"
    assert "artifact1" in encoded


def test_message_type_enum_contains_required_phase13_values() -> None:
    expected = {
        "USER_REQUEST",
        "CONTEXT_CREATED",
        "GOAL_PARSED",
        "TASK_PLANNED",
        "TOOL_CALL_REQUESTED",
        "TOOL_RESULT_RECEIVED",
        "OBSERVATION_CREATED",
        "APPROVAL_REQUESTED",
        "APPROVAL_RESULT_RECEIVED",
        "ARTIFACT_CREATED",
        "ERROR_RAISED",
        "WARNING_RAISED",
        "REPORT_DRAFTED",
        "FINAL_REPORT",
        "HANDOFF_REQUESTED",
        "REFLECTION_REQUESTED",
        "REFLECTION_RESULT",
    }

    assert expected <= {item.name for item in MessageType}


def test_message_window_keeps_required_messages_and_summarizes_old_results() -> None:
    messages = [
        AgentMessage(
            message_id="msg_user",
            sender="user",
            receiver="supervisor",
            message_type=MessageType.USER_REQUEST,
            payload={"query": "查看当前持仓"},
        ),
        *[
            AgentMessage(
                message_id=f"msg_tool_{index}",
                sender="tool_executor",
                receiver="supervisor",
                message_type=MessageType.TOOL_RESULT_RECEIVED,
                payload={
                    "tool_name": "stock_news",
                    "message": "large result",
                    "raw_evidence": [
                        {"chunk_id": f"chunk_{i}", "body": "very-large-body" * 30}
                        for i in range(20)
                    ],
                },
                artifact_refs=[{"artifact_id": f"artifact_{index}"}],
            )
            for index in range(8)
        ],
        AgentMessage(
            message_id="msg_final",
            sender="reporting",
            receiver="ui",
            message_type=MessageType.FINAL_REPORT,
            payload={"answer": "当前持仓摘要"},
        ),
    ]

    trimmed = MessageWindow(default_budget=1200).trim_messages_to_budget(messages, max_chars=1200)
    encoded = json.dumps([item.to_dict() for item in trimmed], ensure_ascii=False, sort_keys=True)

    assert "msg_user" in {item.message_id for item in trimmed}
    assert "msg_final" in {item.message_id for item in trimmed}
    assert "very-large-body" not in encoded
    assert "artifact_" in encoded or "summarized_messages" in encoded

