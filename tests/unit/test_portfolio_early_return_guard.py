from __future__ import annotations

from agent.executor import run_agent_request
from agent.intent_decomposition.layered_decomposer import decompose_intent
from agent.intent_decomposition.schemas import IntentDecomposition, IntentTask
from agent.router import route_agent_query
from agent_control_center_utils import write_agent_fixture


PURE_HOLDINGS_QUERY = "\u67e5\u770b\u5f53\u524d\u6301\u4ed3"
STABLE_RECOMMENDATION_QUERY = (
    "\u63a8\u8350\u4e00\u4e2a\u6bd4\u73b0\u5728\u66f4\u7a33\u5065"
    "\u7684\u6301\u4ed3\uff0c\u5e76\u8bf4\u660e\u4e3a\u4ec0\u4e48\u7a33\u5065\u3002"
)
RISK_REVIEW_QUERY = "\u5206\u6790\u5f53\u524d\u6301\u4ed3\u98ce\u9669"
REBALANCE_ADVICE_QUERY = (
    "\u6839\u636e\u5f53\u524d\u6301\u4ed3\u7ed9\u6211\u8c03\u4ed3\u5efa\u8bae"
)
HOLDING_COUNT_QUERY = "\u5f53\u524d\u6301\u4ed3\u6709\u591a\u5c11\u53ea\u80a1\u7968"


def _task_intents(routed) -> list[str]:
    return [task["intent"] for task in routed.decomposition.get("tasks", [])]


def test_pure_current_holdings_keeps_single_portfolio_state_route() -> None:
    routed = route_agent_query(PURE_HOLDINGS_QUERY, enable_llm=False)

    assert routed.intent == "portfolio_state"
    assert _task_intents(routed) == ["portfolio_state"]
    assert routed.decomposition["diagnostics"]["decision_source"] in {"rule", "fallback"}


def test_stable_holding_recommendation_is_not_single_portfolio_state() -> None:
    routed = route_agent_query(STABLE_RECOMMENDATION_QUERY, enable_llm=False)
    intents = _task_intents(routed)

    assert routed.intent == "multi_intent"
    assert intents != ["portfolio_state"]
    assert {"portfolio_state", "portfolio_risk", "ranking"}.issubset(set(intents))
    diagnostics = routed.decomposition["diagnostics"]
    assert diagnostics["completeness_guard_triggered"] is True
    assert "portfolio_state_keyword" in diagnostics["denied_low_priority_rules"]
    assert diagnostics["mcp_candidate_view"]["entered"] is False


def test_current_holding_risk_review_adds_risk_task() -> None:
    routed = route_agent_query(RISK_REVIEW_QUERY, enable_llm=False)
    intents = _task_intents(routed)

    assert routed.intent == "multi_intent"
    assert "portfolio_state" in intents
    assert "portfolio_risk" in intents
    assert "ranking" not in intents


def test_rebalance_advice_is_readonly_multi_task_not_auto_execution() -> None:
    routed = route_agent_query(REBALANCE_ADVICE_QUERY, enable_llm=False)
    intents = _task_intents(routed)

    assert routed.intent == "multi_intent"
    assert {"portfolio_state", "portfolio_risk", "ranking"}.issubset(set(intents))
    assert "one_time_position_operation" not in intents
    assert "confirm_execute" not in intents


def test_holding_count_query_keeps_fast_single_tool_route() -> None:
    routed = route_agent_query(HOLDING_COUNT_QUERY, enable_llm=False)

    assert routed.intent == "portfolio_state"
    assert _task_intents(routed) == ["portfolio_state"]


def test_completeness_guard_repairs_single_portfolio_state_plan(monkeypatch) -> None:
    def fake_rules(query: str, *, warning: str = "") -> IntentDecomposition:
        return IntentDecomposition(
            query=query,
            route_layer="rule_fallback",
            tasks=[
                IntentTask(
                    task_id="task_1",
                    intent="portfolio_state",
                    parameters={},
                    depends_on=[],
                    reason="legacy low priority state query",
                    confidence=0.62,
                    capability_status="executable",
                )
            ],
            is_multi_intent=False,
            confidence=0.62,
            warnings=[warning] if warning else [],
            diagnostics={"llm_used": False, "fallback_used": True},
        )

    monkeypatch.setattr(
        "agent.intent_decomposition.layered_decomposer.decompose_with_rules",
        fake_rules,
    )

    result = decompose_intent(STABLE_RECOMMENDATION_QUERY, enable_llm=False)
    intents = [task.intent for task in result.tasks]

    assert result.is_multi_intent is True
    assert {"portfolio_state", "portfolio_risk", "ranking"}.issubset(set(intents))
    assert result.diagnostics["completeness_guard_triggered"] is True


def test_stable_recommendation_runs_multi_agent_and_reports_plan(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(
        tmp_path,
        user_id="u1",
        with_position=True,
        cash=100000.0,
    )

    result = run_agent_request(
        STABLE_RECOMMENDATION_QUERY,
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        top_k=10,
        llm_api_key="",
        session_id="stable_recommendation_test",
    )

    answer = str(result.get("answer") or "")
    tool_names = [call.get("tool_name") for call in result.get("tool_calls", [])]

    assert result["success"] is True
    assert result["intent"] == "multi_intent"
    assert (result.get("orchestration") or {}).get("multi_agent") is True
    assert {"portfolio_state", "portfolio_risk", "ranking"}.issubset(set(tool_names))
    assert "\u98ce\u9669\u5206\u6790" in answer
    assert "\u63a8\u8350\u65b9\u6848" in answer
    assert "\u4e3a\u4ec0\u4e48\u66f4\u7a33\u5065" in answer
    assert "\u672c\u6b21\u53ea\u751f\u6210\u53ea\u8bfb\u5206\u6790" in answer
