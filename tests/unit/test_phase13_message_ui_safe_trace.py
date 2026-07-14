from __future__ import annotations

import json

from agent.communication import AgentMessage, MessageStore, MessageType
from app.pages.ai_agent import _build_message_trace_safe_summary
from app.pages.system_monitor import _build_message_bus_health_summary


def _encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def test_message_trace_summary_hides_secret_paths_and_raw_payload(tmp_path) -> None:
    store = MessageStore(output_dir=tmp_path)
    store.save_message(
        AgentMessage(
            message_id="msg_secret",
            conversation_id="conv1",
            run_id="run1",
            sender="tool_executor",
            receiver="executor",
            message_type=MessageType.TOOL_RESULT_RECEIVED,
            payload={
                "summary": "safe summary",
                "confirmation_token": "raw-token",
                "db_path": r"D:\stock_daily_app\data\agent_quant.db",
                "raw_payload": {"artifact_path": r"D:\stock_daily_app\outputs\artifact.json"},
            },
            artifact_refs=[{"artifact_id": "artifact1", "artifact_type": "tool_result", "path": r"D:\secret\artifact.json"}],
            metadata={"user_id": "u1"},
        )
    )

    summary = _build_message_trace_safe_summary(
        {"run_id": "run1", "runtime": {"run_id": "run1"}},
        user_id="u1",
        output_dir=str(tmp_path),
    )
    encoded = _encoded(summary)

    assert summary["message_trace_available"] is True
    assert summary["message_count"] == 1
    assert summary["last_message_type"] == "TOOL_RESULT_RECEIVED"
    assert "safe summary" in encoded
    assert "raw-token" not in encoded
    assert "confirmation_token" not in encoded
    assert "agent_quant.db" not in encoded
    assert "artifact.json" not in encoded
    assert r"D:\stock_daily_app" not in encoded


def test_message_trace_summary_handles_empty_result_safely(tmp_path) -> None:
    summary = _build_message_trace_safe_summary({}, user_id="u1", output_dir=str(tmp_path))
    encoded = _encoded(summary)

    assert summary["message_trace_available"] is False
    assert summary["message_count"] == 0
    assert "confirmation_token" not in encoded


def test_system_monitor_message_bus_health_uses_safe_path_summary(tmp_path) -> None:
    store = MessageStore(output_dir=tmp_path)
    store.save_message(
        AgentMessage(
            message_id="msg_approval",
            run_id="run1",
            sender="tool_executor",
            receiver="ui",
            message_type=MessageType.APPROVAL_REQUESTED,
            payload={"plan_id": "plan1", "confirmation_token": "raw-token", "token_present": True},
            metadata={"user_id": "u1"},
        )
    )

    summary = _build_message_bus_health_summary(user_id="u1", output_dir=tmp_path)
    encoded = _encoded(summary)

    assert summary["status"] == "ok"
    assert summary["latest_run_message_count"] == 1
    assert summary["pending_approval_message_count"] == 1
    assert "message_logs/u1/files=" in summary["message_store_summary"]
    assert str(tmp_path) not in encoded
    assert "raw-token" not in encoded
    assert "confirmation_token" not in encoded

