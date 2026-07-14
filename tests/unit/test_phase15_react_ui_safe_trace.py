from __future__ import annotations

import json

from agent.communication import AgentMessage, MessageStore, MessageType
from agent.react import ObservationEvent, ObservationSeverity, ObservationType, ObserveStore
from agent.react.react_context_bridge import (
    build_react_health_summary,
    build_react_safe_summary,
    list_safe_observation_summaries,
)
from app.pages.system_monitor import _react_health_rows


def _encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def test_phase15_react_safe_summary_counts_replans_without_secrets(tmp_path) -> None:
    store = ObserveStore(output_dir=tmp_path)
    store.save_observation(
        ObservationEvent(
            conversation_id="conv1",
            run_id="run1",
            task_id="task1",
            source_tool_name="portfolio.state",
            observation_type=ObservationType.TOOL_ERROR,
            severity=ObservationSeverity.BLOCKING,
            summary=r"Tool failed token abc123 at D:\stock_daily_app\data\agent_quant.db",
            detail={
                "confirmation_token": "raw-token",
                "raw_tool_payload": {"path": r"D:\secret\payload.json"},
            },
            tool_call_refs=[{"tool_call_id": "tool1"}],
        ),
        user_id="u1",
    )
    MessageStore(output_dir=tmp_path).save_message(
        AgentMessage(
            message_id="msg_replan",
            conversation_id="conv1",
            run_id="run1",
            sender="executor",
            receiver="supervisor",
            message_type=MessageType.REPLAN_REQUESTED,
            payload={"summary": "safe replan", "confirmation_token": "raw-token"},
            metadata={"user_id": "u1"},
        )
    )

    summary = build_react_safe_summary(user_id="u1", output_dir=tmp_path, run_id="run1")
    rows = list_safe_observation_summaries(user_id="u1", output_dir=tmp_path, run_id="run1")
    encoded = _encoded({"summary": summary, "rows": rows})

    assert summary["observation_count"] == 1
    assert summary["blocking_observation_count"] == 1
    assert summary["replan_message_count"] == 1
    assert rows[0]["observation_type"] == "TOOL_ERROR"
    assert "raw-token" not in encoded
    assert "confirmation_token" not in encoded
    assert "agent_quant.db" not in encoded
    assert r"D:\stock_daily_app" not in encoded
    assert "raw_tool_payload" not in encoded


def test_phase15_react_health_rows_are_safe(tmp_path) -> None:
    ObserveStore(output_dir=tmp_path).save_observation(
        ObservationEvent(
            run_id="run2",
            observation_type=ObservationType.TOOL_SUCCESS,
            summary="safe summary",
        ),
        user_id="u1",
    )

    summary = build_react_health_summary(user_id="u1", output_dir=tmp_path)
    rows = _react_health_rows(summary)
    encoded = _encoded(rows.to_dict("records"))

    assert summary["status"] == "ok"
    assert summary["run_file_count"] == 1
    assert "react_logs/u1/files=1" in encoded
    assert str(tmp_path) not in encoded
    assert "confirmation_token" not in encoded
