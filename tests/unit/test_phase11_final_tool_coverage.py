from __future__ import annotations

from pathlib import Path

import pandas as pd

from agent.capability_index import build_trusted_capability_index
from agent.tool_engine import AGENT_MAIN, AGENT_READ, OP_WRITE, execute_tool, get_tool_registry_v2
from agent_control_center_utils import write_agent_fixture
from database.repositories import NewsRepository


def _v2_name_set() -> set[str]:
    registry = get_tool_registry_v2()
    names = {definition.name for definition in registry.list()}
    for definition in registry.list():
        names.update(definition.legacy_names)
    return names


def test_final_capability_index_is_built_from_v2_registry_only() -> None:
    index = build_trusted_capability_index()
    v2_names = _v2_name_set()
    tool_records = [record for record in index.records if record.tool_or_workflow == "tool"]

    assert tool_records
    for record in tool_records:
        assert set(record.registered_tool_names) & v2_names
        assert record.implementation_files == ["agent.tool_engine"]
        assert record.test_status == "passed"

    assert not any("unsafe_write" in name for record in tool_records for name in record.registered_tool_names)


def test_final_write_tools_require_approval_and_mcp_write_is_not_exposed() -> None:
    registry = get_tool_registry_v2()
    write_tools = [definition for definition in registry.list() if definition.operation_type == OP_WRITE]

    assert write_tools
    assert all(definition.requires_approval for definition in write_tools)
    assert all("unsafe_write" not in definition.name for definition in registry.list())

    blocked_commit = execute_tool(
        "portfolio.commit_paper_trade",
        {"user_id": "u1", "plan_id": "missing", "confirmation_token": "bad"},
        context={"user_id": "u1"},
        agent_type=AGENT_MAIN,
    )
    blocked_mcp = execute_tool(
        "evidence.invoke_mcp_readonly",
        {"mcp_tool_name": "mcp.local_financial_evidence.unsafe_write_trade", "arguments": {"stock_code": "000001"}},
        context={"mcp": {"servers": []}},
        agent_type=AGENT_READ,
    )

    assert blocked_commit.success is False
    assert blocked_commit.error_type == "approval_required"
    assert blocked_mcp.success is False
    assert "mcp_readonly_tool_not_allowed" in blocked_mcp.errors


def test_final_agent_default_path_has_no_read_tool_direct_fallbacks() -> None:
    specialist_source = Path(
        "agent/collaboration/specialist_runtime.py"
    ).read_text(encoding="utf-8")
    executor_source = Path("agent/executor.py").read_text(encoding="utf-8")

    forbidden_worker_calls = [
        "query_portfolio_state(",
        "query_portfolio_risk(",
        "query_stock_news(",
        "query_stock_rag(",
    ]
    for marker in forbidden_worker_calls:
        assert marker not in specialist_source

    assert "prepare_strategy_change(" not in executor_source
    assert "execute_unified_agent_request(" in executor_source


def test_final_representative_tools_create_artifacts(tmp_path: Path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True, price=10.0)
    NewsRepository(db_path).insert_news_event(
        {
            "news_id": "news_final_1",
            "title": "Final coverage news",
            "summary": "Coverage summary",
            "content": "Coverage evidence",
            "source": "unit_test",
            "url": "https://example.test/final",
            "publish_time": "2026-06-12 10:00:00",
            "trade_date": "2026-06-12",
        }
    )
    NewsRepository(db_path).insert_news_stock_mapping(
        {
            "mapping_id": "mapping_final_1",
            "news_id": "news_final_1",
            "stock_code": "600519",
            "stock_name": "Kweichow Moutai",
            "impact_direction": "neutral",
            "mapping_confidence": 0.9,
            "evidence_text": "Coverage evidence",
        }
    )

    context = {"user_id": "u1", "output_dir": output_dir, "db_path": db_path, "session_id": "s_final"}
    results = [
        execute_tool("ranking", {"top_k": 1}, context=context, agent_type=AGENT_READ),
        execute_tool("stock_lookup", {"user_id": "u1", "stock_code": "600519"}, context=context, agent_type=AGENT_READ),
        execute_tool("stock_news", {"stock_code": "600519", "as_of_date": "2026-06-12"}, context=context, agent_type=AGENT_READ),
        execute_tool("portfolio.read_snapshot", {"user_id": "u1"}, context=context, agent_type=AGENT_READ),
        execute_tool("portfolio.analyze_risk", {"user_id": "u1"}, context=context, agent_type=AGENT_READ),
        execute_tool("portfolio.preview_rebalance", {"user_id": "u1", "stock_code": "600519"}, context=context, agent_type=AGENT_MAIN),
    ]

    assert all(result.success for result in results)
    assert all(result.artifact_id for result in results)


def test_removed_nonwrite_compatibility_wrappers_do_not_return() -> None:
    removed_paths = [
        "agent/tools/tool_registry.py",
        "agent/tools/ranking_tool.py",
        "agent/tools/stock_lookup_tool.py",
        "agent/tools/stock_analysis_tool.py",
        "agent/tools/stock_news_tool.py",
        "agent/tools/stock_rag_tool.py",
        "agent/tools/portfolio_state_tool.py",
        "agent/tools/portfolio_risk_tool.py",
        "agent/tools/position_recommendation_tool.py",
        "agent/tools/python_sandbox_tool.py",
        "agent/tools/replacement_recommendation_tool.py",
        "agent/tools/report_tool.py",
        "agent/tools/scheduler_tool.py",
        "agent/tools/user_profile_tool.py",
    ]

    assert all(not Path(path).exists() for path in removed_paths)
