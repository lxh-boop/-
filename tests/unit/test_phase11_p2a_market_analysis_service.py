from __future__ import annotations

from pathlib import Path

import pandas as pd

from agent.capability_index import build_trusted_capability_index
from agent.tool_engine import AGENT_READ, OP_READ, execute_tool, get_tool_registry_v2
from agent.tools import market_analysis_adapters
from agent.tools.position_recommendation_tool import recommend_position_weight
from agent_control_center_utils import write_agent_fixture
from app.classic_services import format_classic_ranking_for_display, load_classic_ranking_with_ai_adjustment


def test_p2a_market_tools_registered_with_legacy_aliases() -> None:
    registry = get_tool_registry_v2()
    expected = {
        "market.get_ranking": ["ranking"],
        "market.analyze_stock": ["stock_analysis"],
        "market.lookup_stock": ["stock_lookup", "classic_stock_score"],
        "market.compare_stocks": [],
        "market.get_signal_summary": ["classic_ranking"],
    }

    for canonical, aliases in expected.items():
        definition = registry.get(canonical)
        assert definition is not None
        assert definition.name == canonical
        assert definition.operation_type == OP_READ
        for alias in aliases:
            assert registry.get(alias).name == canonical

    assert callable(market_analysis_adapters.MarketGetRankingAdapter)
    assert callable(market_analysis_adapters.MarketAnalyzeStockAdapter)
    assert callable(market_analysis_adapters.MarketLookupStockAdapter)
    assert callable(market_analysis_adapters.MarketCompareStocksAdapter)
    assert callable(market_analysis_adapters.MarketSignalSummaryAdapter)


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


def test_p2a_stock_analysis_and_lookup_return_unified_data(tmp_path: Path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path)

    analysis = execute_tool(
        "stock_analysis",
        {"user_id": "u1", "stock_code": "600519", "include_rag": False},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_READ,
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
    assert analysis.metadata["canonical_tool_name"] == "market.analyze_stock"
    assert analysis.data["stock_code"] == "600519"
    assert analysis.data["records"]
    assert analysis.data["summary"]["position_adjustment_ratio"] == 0.8
    assert analysis.data["not_executed"] is True
    assert lookup_by_code.success is True
    assert lookup_by_code.metadata["canonical_tool_name"] == "market.lookup_stock"
    assert lookup_by_code.data["stock_code"] == "600519"
    assert lookup_by_name.success is True
    assert lookup_by_name.data["stock_code"] == "600519"


def test_p2a_classic_services_wrapper_keeps_dataframe_shape(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    rec_dir = output_dir / "recommendations"
    rec_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {"rank": 1, "date": "2026-06-12", "code": "000001", "name": "Ping An Bank", "score": 0.91, "confidence": "high", "risk_score": 0.2},
            {"rank": 2, "date": "2026-06-12", "code": "000002", "name": "Vanke A", "score": 0.82, "confidence": "medium", "risk_score": 0.4},
        ]
    ).to_csv(output_dir / "ranking_latest.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {
                "stock_code": "000001",
                "target_weight": 0.05,
                "news_adjustment": -0.01,
                "user_adjustment": 0.02,
                "effective_news_adjustment": -0.005,
                "combined_adjustment": 0.015,
                "position_adjustment_ratio": 1.015,
                "reason": "news checked",
                "risk_warning": "",
                "evidence_news_ids": '["n1"]',
                "evidence_chunk_ids": '["c1"]',
                "triggered_rules": "[]",
            }
        ]
    ).to_csv(rec_dir / "final_recommendations_latest.csv", index=False, encoding="utf-8-sig")

    merged = load_classic_ranking_with_ai_adjustment(output_dir=output_dir)
    display = format_classic_ranking_for_display(merged)

    assert merged.loc[0, "stock_code"] == "000001"
    assert merged.loc[0, "pred_rank"] == 1
    assert "final_action" not in merged.columns
    assert merged.loc[0, "combined_adjustment"] == 0.015
    assert any("AI" in str(column) for column in display.columns)


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
    assert "market.compare_stocks" in by_id["tool:market.compare_stocks"].registered_tool_names
