from __future__ import annotations

from pathlib import Path

from agent.capability_index import build_trusted_capability_index
from agent.tool_engine import AGENT_READ, OP_READ, execute_tool, get_tool_registry_v2
from agent.tools import market_analysis_adapters
from agent.services.market_analysis_service import market_analysis_service
from application.use_cases.position_recommendation import (
    recommend_position_weight,
)
from agent_control_center_utils import write_agent_fixture


def test_p2a_market_registry_contains_only_atomic_reads() -> None:
    registry = get_tool_registry_v2()
    expected = {
        "market.get_ranking": ["ranking"],
        "market.lookup_stock": ["stock_lookup", "classic_stock_score"],
        "market.get_signal_summary": ["classic_ranking"],
    }

    for canonical, aliases in expected.items():
        definition = registry.get(canonical)
        assert definition is not None
        assert definition.name == canonical
        assert definition.operation_type == OP_READ
        for alias in aliases:
            assert registry.get(alias).name == canonical

    assert callable(market_analysis_adapters.execute_market_ranking_tool)
    assert callable(market_analysis_adapters.execute_market_stock_lookup_tool)
    assert callable(market_analysis_adapters.execute_market_signal_summary_tool)
    assert registry.get("market.analyze_stock") is None
    assert registry.get("market.compare_stocks") is None
    assert registry.get("stock_analysis") is None


def test_p2a_ranking_alias_uses_v2_executor_and_artifact(tmp_path: Path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path)

    result = execute_tool(
        "ranking",
        {"top_k": 1},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_READ,
    )

    assert result.success is True
    assert result.metadata["canonical_tool_name"] == "market.get_ranking"
    assert result.artifact_id
    assert result.data["records"][0]["code"] == "600519"
    assert result.data["summary"]["returned_count"] == 1
    assert result.data["not_executed"] is True
    assert result.data["sources"]


def test_p2a_stock_analysis_is_business_function_and_lookup_is_tool(
    tmp_path: Path,
) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path)

    analysis = market_analysis_service.analyze_stock(
        "u1",
        "600519",
        output_dir=output_dir,
        db_path=db_path,
        include_rag=False,
    )
    lookup_by_code = execute_tool(
        "stock_lookup",
        {"user_id": "u1", "stock_query": "600519"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_READ,
    )
    lookup_by_name = execute_tool(
        "classic_stock_score",
        {"user_id": "u1", "stock_query": "Kweichow"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_READ,
    )

    assert analysis.success is True
    assert analysis.data["stock_code"] == "600519"
    assert analysis.data["records"]
    assert analysis.data["summary"]["position_adjustment_ratio"] == 0.8
    assert analysis.data["not_executed"] is True
    assert lookup_by_code.success is True
    assert lookup_by_code.metadata["canonical_tool_name"] == "market.lookup_stock"
    assert lookup_by_code.data["stock_code"] == "600519"
    assert lookup_by_name.success is True
    assert lookup_by_name.data["stock_code"] == "600519"
    assert get_tool_registry_v2().get("stock_analysis") is None


def test_p2a_position_recommendation_still_reads_market_service(tmp_path: Path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, price=10.0)

    result = recommend_position_weight("u1", "600519", output_dir=output_dir, db_path=db_path)

    assert result.success is True
    assert result.data["stock_code"] == "600519"
    assert result.data["recommended_weight"] > 0


def test_p2a_capability_index_points_market_tools_to_v2() -> None:
    index = build_trusted_capability_index()
    by_id = {record.capability_id: record for record in index.records}

    assert by_id["tool:ranking"].registered_tool_names[1] == "market.get_ranking"
    assert "market.lookup_stock" in by_id["tool:stock_lookup"].registered_tool_names
    assert "market.get_signal_summary" in by_id["tool:classic_ranking"].registered_tool_names
    assert "tool:market.compare_stocks" not in by_id
    assert "tool:stock_analysis" not in by_id
