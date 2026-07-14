from agent.communication.integration import publish_agent_message
from agent.communication.message_types import MessageType
from app.handoff_ui import build_handoff_health_summary, build_handoff_safe_summary, format_handoff_caption


def test_phase17_handoff_ui_summary_from_result_is_safe() -> None:
    result = {
        "run_id": "run1",
        "orchestration": {
            "phase17_handoff": {
                "handoff_available": True,
                "trace_id": "trace1",
                "handoff_count": 2,
                "roles_used": ["EVIDENCE_RETRIEVER", "REPORT_WRITER"],
                "latest_handoff_status": "SUCCEEDED",
                "blocked_handoff_count": 0,
                "handoff_refs": [{"handoff_id": "h1", "target_role": "EVIDENCE_RETRIEVER", "status": "SUCCEEDED"}],
                "handoff_role_summaries": [{"summary": "ok", "db_path": r"D:\secret.db"}],
            }
        },
    }

    summary = build_handoff_safe_summary(result, user_id="u1", output_dir="outputs")
    assert summary["handoff_available"] is True
    assert summary["handoff_count"] == 2
    assert summary["handoff_role_summaries"][0]["db_path"] == "[REDACTED]"
    assert "Handoff: count=2" in format_handoff_caption(summary)


def test_phase17_handoff_health_summary_from_messages(tmp_path) -> None:
    publish_agent_message(
        output_dir=tmp_path,
        user_id="u1",
        conversation_id="conv1",
        run_id="run1",
        sender="COORDINATOR",
        receiver="EVIDENCE_RETRIEVER",
        message_type=MessageType.HANDOFF_REQUESTED,
        payload={"handoff_id": "h1", "target_role": "EVIDENCE_RETRIEVER", "status": "requested"},
        payload_schema="phase17.handoff_request.v1",
    )
    publish_agent_message(
        output_dir=tmp_path,
        user_id="u1",
        conversation_id="conv1",
        run_id="run1",
        sender="EVIDENCE_RETRIEVER",
        receiver="COORDINATOR",
        message_type=MessageType.HANDOFF_RESULT,
        payload={"handoff_id": "h1", "target_role": "EVIDENCE_RETRIEVER", "status": "SUCCEEDED", "summary": "ok"},
        payload_schema="phase17.handoff_result.v1",
    )

    summary = build_handoff_safe_summary({"run_id": "run1"}, user_id="u1", output_dir=tmp_path)
    assert summary["handoff_available"] is True
    assert summary["handoff_messages_seen"] == 2
    assert summary["roles_used"] == ["EVIDENCE_RETRIEVER"]

    health = build_handoff_health_summary(user_id="u1", output_dir=tmp_path)
    assert health["status"] == "ok"
    assert health["latest_handoff_count"] == 1
    assert health["handoff_messages_seen"] == 2
