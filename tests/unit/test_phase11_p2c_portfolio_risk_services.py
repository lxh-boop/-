from __future__ import annotations

from pathlib import Path

from agent.services.portfolio_risk_service import portfolio_risk_service
from agent.services.portfolio_service import portfolio_service
from agent.tool_engine import AGENT_READ, OP_READ, execute_tool, get_tool_registry_v2
from agent.tools import portfolio_risk_adapters, portfolio_state_adapters
from agent.tools.portfolio_risk_tool import query_portfolio_risk
from agent.tools.portfolio_state_tool import query_portfolio_state
from agent.tools.position_recommendation_tool import recommend_position_weight
from agent_control_center_utils import write_agent_fixture
from portfolio.paper_order import create_paper_order
from portfolio.storage import PortfolioStorage


def _fixture_with_order(tmp_path: Path):
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True, price=10.0)
    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1")
    storage.save_orders(
        [
            create_paper_order(
                user_id="u1",
                account_id="paper_u1",
                trade_date="2026-06-12",
                stock_code="000001",
                stock_name="Ping An Bank",
                action="buy",
                target_weight=0.12,
                executed_price=12.0,
                quantity=1000,
                reason="fixture",
            )
        ]
    )
    return output_dir, db_path


def test_p2c_portfolio_tools_registered_with_legacy_aliases() -> None:
    registry = get_tool_registry_v2()
    expected = {
        "portfolio.get_state": ["portfolio_state"],
        "portfolio.get_account_summary": ["portfolio_account_summary"],
        "portfolio.get_positions": ["portfolio_positions"],
        "portfolio.get_orders": ["portfolio_orders"],
        "portfolio.analyze_risk": ["portfolio_risk"],
        "portfolio.compare_risk_before_after": ["portfolio_risk_compare"],
    }

    for canonical, aliases in expected.items():
        definition = registry.get(canonical)
        assert definition is not None
        assert definition.name == canonical
        assert definition.operation_type == OP_READ
        for alias in aliases:
            assert registry.get(alias).name == canonical

    assert callable(portfolio_state_adapters.PortfolioGetStateAdapter)
    assert callable(portfolio_state_adapters.PortfolioGetAccountSummaryAdapter)
    assert callable(portfolio_state_adapters.PortfolioGetPositionsAdapter)
    assert callable(portfolio_state_adapters.PortfolioGetOrdersAdapter)
    assert callable(portfolio_risk_adapters.PortfolioAnalyzeRiskAdapter)
    assert callable(portfolio_risk_adapters.PortfolioCompareRiskBeforeAfterAdapter)


def test_p2c_portfolio_service_reads_account_positions_and_orders(tmp_path: Path) -> None:
    output_dir, db_path = _fixture_with_order(tmp_path)

    state = portfolio_service.get_portfolio_state("u1", output_dir=output_dir, db_path=db_path)
    account = portfolio_service.get_account_summary("u1", output_dir=output_dir, db_path=db_path)
    positions = portfolio_service.get_current_positions("u1", output_dir=output_dir, db_path=db_path)
    orders = portfolio_service.get_current_orders("u1", output_dir=output_dir, db_path=db_path)

    assert account["account"]["account_id"] == "paper_u1"
    assert state["position_count"] == 1
    assert positions["position_weights"]["000001"] > 0
    assert orders["order_count"] == 1
    assert state["not_executed"] is True
    assert state["mutation_performed"] is False


def test_p2c_risk_service_and_tool_executor_artifacts(tmp_path: Path) -> None:
    output_dir, db_path = _fixture_with_order(tmp_path)

    direct = portfolio_risk_service.analyze_current_risk("u1", output_dir=output_dir, db_path=db_path)
    state_tool = execute_tool(
        "portfolio_state",
        {"user_id": "u1"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_READ,
    )
    risk_tool = execute_tool(
        "portfolio.analyze_risk",
        {"user_id": "u1"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_READ,
    )

    assert direct["status"] == "success"
    assert direct["risk_report"]["holding_count"] == 1
    assert state_tool.success is True
    assert state_tool.metadata["canonical_tool_name"] == "portfolio.get_state"
    assert state_tool.artifact_id
    assert risk_tool.success is True
    assert risk_tool.metadata["canonical_tool_name"] == "portfolio.analyze_risk"
    assert risk_tool.artifact_id
    assert risk_tool.data["summary"]["holding_count"] == 1


def test_p2c_old_wrappers_keep_compatible_shape(tmp_path: Path) -> None:
    output_dir, db_path = _fixture_with_order(tmp_path)

    state = query_portfolio_state("u1", output_dir=output_dir, db_path=db_path)
    risk = query_portfolio_risk("u1", output_dir=output_dir, db_path=db_path)

    assert state["account"]["account_id"] == "paper_u1"
    assert state["positions"][0]["stock_code"] == "000001"
    assert state["orders"][0]["stock_code"] == "000001"
    assert state["position_count"] == 1
    assert risk["status"] == "success"
    assert risk["risk_report"]["holding_count"] == 1


def test_p2c_risk_comparison_and_p1a_recommendation_still_work(tmp_path: Path) -> None:
    output_dir, db_path = _fixture_with_order(tmp_path)

    comparison = execute_tool(
        "portfolio.compare_risk_before_after",
        {"user_id": "u1"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_READ,
    )
    recommendation = recommend_position_weight("u1", "600519", output_dir=output_dir, db_path=db_path)

    assert comparison.success is True
    assert comparison.data["delta"]["max_single_position"] == 0
    assert comparison.data["not_executed"] is True
    assert recommendation.success is True
    assert recommendation.data["stock_code"] == "600519"
