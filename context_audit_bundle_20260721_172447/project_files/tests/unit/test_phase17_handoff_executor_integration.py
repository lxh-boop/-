from agent.communication import MessageStore
from agent.executor import run_agent_request
from agent_control_center_utils import write_agent_fixture


PHASE17_MULTI_AGENT_QUERY = "结合当前持仓、新闻和 RAG，分析排名前十股票，并给出组合层面的风险与建议。"


def test_phase17_readonly_multi_agent_emits_handoff_trace_and_messages(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True)
    result = run_agent_request(
        PHASE17_MULTI_AGENT_QUERY,
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
        llm_api_key="",
    )

    handoff = result["orchestration"]["phase17_handoff"]
    assert handoff["handoff_available"] is True
    assert handoff["handoff_count"] == 3
    assert set(handoff["roles_used"]) == {"EVIDENCE_RETRIEVER", "PORTFOLIO_ANALYST", "REPORT_WRITER"}
    assert handoff["blocked_handoff_count"] == 0
    assert result["context"]["phase17_handoff"]["handoff_count"] == 3
    assert result["context"]["phase17_handoff"]["handoff_refs"]

    messages = MessageStore(output_dir=output_dir).list_messages_by_run(result["run_id"], user_id="u1")
    handoff_types = [message.message_type.value for message in messages if message.message_type.value.startswith("HANDOFF_")]
    assert handoff_types.count("HANDOFF_REQUESTED") == 3
    assert handoff_types.count("HANDOFF_RESULT") == 3
    encoded = str([message.to_dict() for message in messages])
    assert "confirmation_token" not in encoded
    assert "raw_positions" not in encoded
    assert "raw_evidence" not in encoded


def test_phase17_protected_position_preview_uses_strategy_guard_without_commit(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True, cash=100000.0)
    result = run_agent_request(
        "000001 卖出100股",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
        llm_api_key="",
    )

    assert result["intent"] == "one_time_position_operation"
    assert result["runtime"]["status"] == "waiting_for_approval"
    handoff = result["orchestration"]["phase17_handoff"]
    assert handoff["handoff_count"] == 3
    assert "STRATEGY_GUARD" in handoff["roles_used"]
    assert handoff["blocked_handoff_count"] == 0
    assert result["orchestration"]["write_operations_executed"] == 0

    messages = MessageStore(output_dir=output_dir).list_messages_by_run(result["run_id"], user_id="u1")
    assert any(
        message.message_type.value == "HANDOFF_RESULT"
        and (message.payload or {}).get("target_role") == "STRATEGY_GUARD"
        for message in messages
    )
