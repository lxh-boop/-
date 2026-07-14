from __future__ import annotations

from agent.executor import _normalise_readonly_multi_agent_tasks, run_agent_request
from agent.router import route_agent_query
from agent_control_center_utils import write_agent_fixture


RISK_QUERY = "\u5206\u6790\u5f53\u524d\u7684\u7ec4\u5408\u98ce\u9669"
RECOMMENDATION_QUERY = "\u6839\u636e\u5f53\u524d\u7ec4\u5408\u98ce\u9669\uff0c\u7ed9\u6211\u4e00\u4e2a\u8c03\u4ed3\u5efa\u8bae"


def _tool_names(result: dict) -> list[str]:
    return [str(call.get("tool_name") or "") for call in result.get("tool_calls", [])]


def test_portfolio_risk_intent_does_not_expand_to_market_or_recommendation_tools() -> None:
    routed = route_agent_query(RISK_QUERY, enable_llm=False)
    intents = [task["intent"] for task in routed.decomposition.get("tasks", [])]

    assert routed.intent == "multi_intent"
    assert intents == ["portfolio_state", "portfolio_risk"]

    market_tasks, portfolio_tasks = _normalise_readonly_multi_agent_tasks(
        query=RISK_QUERY,
        decomposition=routed.decomposition,
        default_top_k=10,
        context={},
    )

    assert market_tasks == []
    assert [task["intent"] for task in portfolio_tasks] == ["portfolio_state", "portfolio_risk"]


def test_portfolio_risk_run_uses_only_state_and_risk_tools(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(
        tmp_path,
        user_id="u1",
        with_position=True,
        cash=100000.0,
    )

    result = run_agent_request(
        RISK_QUERY,
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        top_k=10,
        llm_api_key="",
        session_id="risk_boundary",
    )

    names = set(_tool_names(result))
    orchestration = result.get("orchestration") or {}
    agent_outputs = orchestration.get("agent_outputs") or {}

    assert result["success"] is True
    assert names == {"portfolio_state", "portfolio_risk"}
    assert "ranking" not in names
    assert "stock_analysis" not in names
    assert "position_recommendation" not in names
    assert "market_intelligence" not in agent_outputs


def test_explicit_recommendation_still_enters_readonly_recommendation_chain(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(
        tmp_path,
        user_id="u1",
        with_position=True,
        cash=100000.0,
    )

    result = run_agent_request(
        RECOMMENDATION_QUERY,
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        top_k=10,
        llm_api_key="",
        session_id="risk_recommendation",
    )

    names = set(_tool_names(result))
    answer = str(result.get("answer") or "")

    assert result["success"] is True
    assert {"portfolio_state", "portfolio_risk", "ranking"}.issubset(names)
    assert "position_recommendation" not in names
    assert "\u63a8\u8350\u65b9\u6848" in answer
    assert "\u4e0d\u81ea\u52a8\u6267\u884c" in answer
