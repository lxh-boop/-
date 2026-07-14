from __future__ import annotations

import pytest

from agent.agent_specs import (
    MARKET_INTELLIGENCE,
    PORTFOLIO_ANALYSIS,
    REPORTING,
    validate_tool_allowed,
)
from agent.executor import run_agent_request
from agent.runtime import load_run_snapshot
from agent_control_center_utils import write_agent_fixture
from database.repositories.agent_repository import AgentRepository


PHASE1_QUERY = (
    "\u7ed3\u5408\u5f53\u524d\u6301\u4ed3\u3001\u65b0\u95fb\u548c RAG"
    "\uff0c\u5206\u6790\u6392\u540d\u524d\u5341\u80a1\u7968"
    "\uff0c\u5e76\u7ed9\u51fa\u7ec4\u5408\u5c42\u9762\u7684"
    "\u98ce\u9669\u4e0e\u5efa\u8bae\u3002"
)


def test_specialist_tool_whitelist_blocks_privilege_escalation() -> None:
    validate_tool_allowed(MARKET_INTELLIGENCE, "ranking")
    validate_tool_allowed(PORTFOLIO_ANALYSIS, "portfolio_state")
    with pytest.raises(PermissionError):
        validate_tool_allowed(MARKET_INTELLIGENCE, "paper_trade_execute")
    with pytest.raises(PermissionError):
        validate_tool_allowed(REPORTING, "ranking")


def test_readonly_multi_agent_collaboration_records_handoff_and_no_writes(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True)

    result = run_agent_request(
        PHASE1_QUERY,
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
        llm_api_key="",
    )

    assert result["success"] is True
    assert result["intent"] == "multi_intent"
    orchestration = result["orchestration"]
    assert orchestration["multi_agent"] is True
    assert orchestration["read_only"] is True
    assert set(orchestration["agent_outputs"]) == {
        "supervisor",
        "market_intelligence",
        "portfolio_analysis",
        "reporting",
    }

    roles = [row["role"] for row in orchestration["agent_timeline"]]
    assert roles == [
        "supervisor",
        "market_intelligence",
        "portfolio_analysis",
        "reporting",
    ]
    assert orchestration["agent_outputs"]["market_intelligence"]["handoff_to"] == "portfolio_analysis"
    assert orchestration["agent_outputs"]["portfolio_analysis"]["handoff_to"] == "reporting"
    assert orchestration["agent_outputs"]["reporting"]["proposal"]["write_operations"] == 0

    tool_roles = {call["agent_role"] for call in result["tool_calls"]}
    assert tool_roles <= {"market_intelligence", "portfolio_analysis"}
    market_tools = {
        call["tool_name"]
        for call in result["tool_calls"]
        if call["agent_role"] == "market_intelligence"
    }
    portfolio_tools = {
        call["tool_name"]
        for call in result["tool_calls"]
        if call["agent_role"] == "portfolio_analysis"
    }
    assert {"ranking", "stock_analysis", "stock_news", "stock_rag"} <= market_tools
    assert {"portfolio_state", "portfolio_risk"} <= portfolio_tools

    snapshot = load_run_snapshot(db_path, result["run_id"])
    role_steps = [
        row
        for row in snapshot["steps"]
        if (row.get("metadata_json") or {}).get("agent_role")
    ]
    assert [row["metadata_json"]["agent_role"] for row in role_steps] == roles
    assert all(row["metadata_json"].get("message_id") for row in role_steps)
    assert role_steps[1]["metadata_json"]["handoff_from"] == "supervisor"
    assert role_steps[2]["metadata_json"]["handoff_to"] == "reporting"

    repo = AgentRepository(db_path)
    assert repo.store.list("action_proposals") == []
    assert repo.store.list("action_commits") == []


def test_single_intent_keeps_legacy_direct_execution_path(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True)

    result = run_agent_request(
        "\u67e5\u770b\u5f53\u524d\u6a21\u62df\u76d8\u6301\u4ed3",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
        llm_api_key="",
    )

    assert result["success"] is True
    assert result["intent"] == "portfolio_state"
    assert not result.get("orchestration", {}).get("multi_agent")
