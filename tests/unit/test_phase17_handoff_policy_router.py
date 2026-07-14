from agent.handoff import AgentRole, HandoffPolicy, HandoffRouter, HandoffSanitizer, REDACTED
from agent.reflection.critic_types import CriticAction


def test_phase17_handoff_policy_blocks_specialist_write_tools() -> None:
    policy = HandoffPolicy.default()
    for role in {
        AgentRole.PORTFOLIO_ANALYST,
        AgentRole.RISK_ANALYST,
        AgentRole.EVIDENCE_RETRIEVER,
        AgentRole.STRATEGY_GUARD,
        AgentRole.REPORT_WRITER,
        AgentRole.SYSTEM_DIAGNOSTIC,
    }:
        assert "approval.confirm_plan" not in policy.allowed_tools_for_role(role)
        assert "approval.confirm_plan" in policy.blocked_tools_for_role(role)
        assert not policy.can_write_business_state(role)

    assert policy.can_write_business_state(AgentRole.COORDINATOR)
    assert policy.requires_approval(AgentRole.COORDINATOR, tool_name="approval.confirm_plan")
    assert policy.requires_approval(AgentRole.STRATEGY_GUARD, tool_name="portfolio.preview_manual_change")


def test_phase17_handoff_policy_edges_and_depth() -> None:
    policy = HandoffPolicy(default_max_depth=2)
    assert policy.can_handoff(AgentRole.COORDINATOR, AgentRole.EVIDENCE_RETRIEVER, depth=0)
    assert policy.can_handoff(AgentRole.PORTFOLIO_ANALYST, AgentRole.RISK_ANALYST, depth=1)
    assert not policy.can_handoff(AgentRole.REPORT_WRITER, AgentRole.EVIDENCE_RETRIEVER, depth=0)
    assert not policy.can_handoff(AgentRole.COORDINATOR, AgentRole.REPORT_WRITER, depth=2)
    assert policy.max_handoff_depth() == 2


def test_phase17_handoff_policy_validates_tools_and_sensitive_payloads() -> None:
    router = HandoffRouter()
    request = router.build_request(
        source_role=AgentRole.COORDINATOR,
        target_role=AgentRole.EVIDENCE_RETRIEVER,
        reason="need evidence",
        tool_names=["stock_rag", "approval.confirm_plan", "mcp.local.read"],
        input_summary={"query": "news"},
    )
    assert request.allowed_tools == ["stock_rag", "mcp.local.read"]
    assert "approval.confirm_plan" in request.blocked_tools
    assert router.policy.validate_request(request) == []

    bad_request = router.build_request(
        source_role=AgentRole.COORDINATOR,
        target_role=AgentRole.PORTFOLIO_ANALYST,
        reason="bad",
        input_summary={"api_key": "secret"},
    )
    assert "sensitive_data_detected" in router.policy.validate_request(bad_request)


def test_phase17_handoff_router_routes_common_goals() -> None:
    router = HandoffRouter()
    roles = router.route_by_user_goal("分析当前组合风险并给我一个调仓建议")
    assert roles[:3] == [
        AgentRole.PORTFOLIO_ANALYST,
        AgentRole.RISK_ANALYST,
        AgentRole.STRATEGY_GUARD,
    ]
    assert roles[-1] == AgentRole.REPORT_WRITER

    assert router.route_by_missing_context("missing rag evidence") == [AgentRole.EVIDENCE_RETRIEVER]
    assert router.route_by_tool_need("portfolio.preview_manual_change") == AgentRole.STRATEGY_GUARD
    assert router.route_by_tool_need("mcp.local.read") == AgentRole.EVIDENCE_RETRIEVER
    assert router.route_by_risk_level("high") == [AgentRole.RISK_ANALYST, AgentRole.STRATEGY_GUARD]


def test_phase17_handoff_router_routes_critic_action() -> None:
    router = HandoffRouter()
    assert router.route_by_critic_action(CriticAction.BLOCK_AND_REPORT) == [AgentRole.COORDINATOR]
    assert router.route_by_critic_action(CriticAction.HANDOFF_REQUESTED, handoff_hint="need more RAG evidence") == [
        AgentRole.EVIDENCE_RETRIEVER
    ]
    assert router.route_by_critic_action("HANDOFF_REQUESTED", handoff_hint="approval proposal boundary") == [
        AgentRole.STRATEGY_GUARD
    ]


def test_phase17_handoff_sanitizer_hides_sensitive_strings_from_ui() -> None:
    sanitizer = HandoffSanitizer()
    payload = {
        "summary": "ok",
        "error": "Traceback in D:\\stock_daily_app\\agent\\executor.py",
        "metadata": {"raw_tool_payload": {"x": 1}},
    }
    safe = sanitizer.sanitize_for_ui(payload)
    assert safe["summary"] == "ok"
    assert safe["error"] == REDACTED
    assert safe["metadata"]["raw_tool_payload"] == REDACTED
