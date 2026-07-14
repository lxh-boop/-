from agent.handoff import (
    AgentRole,
    HandoffPriority,
    HandoffRequest,
    HandoffResult,
    HandoffSanitizer,
    HandoffStatus,
    HandoffTrace,
    REDACTED,
)


def test_phase17_agent_roles_are_complete() -> None:
    assert {role.value for role in AgentRole} == {
        "COORDINATOR",
        "PORTFOLIO_ANALYST",
        "RISK_ANALYST",
        "EVIDENCE_RETRIEVER",
        "STRATEGY_GUARD",
        "REPORT_WRITER",
        "SYSTEM_DIAGNOSTIC",
    }
    assert AgentRole.from_value("market_intelligence") == AgentRole.EVIDENCE_RETRIEVER
    assert AgentRole.from_value("risk_operation") == AgentRole.STRATEGY_GUARD


def test_phase17_handoff_request_result_serialize_roundtrip() -> None:
    request = HandoffRequest(
        conversation_id="conv1",
        run_id="run1",
        task_id="task1",
        source_role="COORDINATOR",
        target_role="PORTFOLIO_ANALYST",
        reason="need portfolio state",
        priority=HandoffPriority.HIGH,
        input_summary={"query": "查看当前持仓"},
        context_refs=[{"context_id": "ctx1"}],
        allowed_tools=["portfolio_state"],
    )
    encoded = request.to_dict()
    decoded = HandoffRequest.from_dict(encoded)
    assert decoded.handoff_id == request.handoff_id
    assert decoded.target_role == AgentRole.PORTFOLIO_ANALYST
    assert decoded.priority == HandoffPriority.HIGH
    assert decoded.allowed_tools == ["portfolio_state"]

    result = HandoffResult(
        handoff_id=request.handoff_id,
        conversation_id="conv1",
        run_id="run1",
        task_id="task1",
        target_role=AgentRole.PORTFOLIO_ANALYST,
        status=HandoffStatus.SUCCEEDED,
        summary="portfolio state ready",
        findings=[{"position_count": 10}],
        recommended_action={"type": "report_only"},
    )
    result_roundtrip = HandoffResult.from_dict(result.to_dict())
    assert result_roundtrip.status == HandoffStatus.SUCCEEDED
    assert result_roundtrip.findings[0]["position_count"] == 10


def test_phase17_handoff_trace_collects_safe_edges() -> None:
    request = HandoffRequest(
        source_role=AgentRole.COORDINATOR,
        target_role=AgentRole.EVIDENCE_RETRIEVER,
        reason="need evidence",
        allowed_tools=["stock_rag"],
        artifact_refs=[{"artifact_id": "artifact1"}],
        critic_refs=[{"critic_id": "critic1"}],
    )
    trace = HandoffTrace(run_id="run1")
    trace.add_request(request)
    payload = trace.to_dict()
    assert request.handoff_id in payload["handoff_ids"]
    assert payload["role_edges"][0]["target_role"] == "EVIDENCE_RETRIEVER"
    assert payload["tool_edges"][0]["tool_name"] == "stock_rag"
    assert payload["artifact_edges"][0]["artifact_id"] == "artifact1"


def test_phase17_handoff_sanitizer_redacts_secrets_paths_and_private_reasoning() -> None:
    sanitizer = HandoffSanitizer()
    request = HandoffRequest(
        source_role=AgentRole.COORDINATOR,
        target_role=AgentRole.STRATEGY_GUARD,
        input_summary={
            "confirmation_token": "secret-token",
            "db_path": r"D:\stock_daily_app\data\agent_quant.db",
            "raw_positions": [{"stock_code": "000001"}],
            "chain_of_thought": "hidden",
            "safe": "visible",
        },
    )
    safe = sanitizer.sanitize_for_llm(request)
    assert safe["input_summary"]["confirmation_token"] == REDACTED
    assert safe["input_summary"]["db_path"] == REDACTED
    assert safe["input_summary"]["raw_positions"] == REDACTED
    assert safe["input_summary"]["chain_of_thought"] == REDACTED
    assert safe["input_summary"]["safe"] == "visible"
