from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from agent.tools.paper_trade_execute_tool import execute_confirmed_paper_trade_plan
from agent.tools.rebalance_plan_tool import preview_add_stock_to_paper, preview_adjust_position_to_weight
from database.repositories.agent_repository import AgentRepository
from portfolio.storage import PortfolioStorage
from agent_control_center_utils import write_agent_fixture
from agent.executor import run_agent_request
from portfolio.paper_position import create_position


@pytest.fixture(autouse=True)
def _fixed_agent_trade_date(monkeypatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 6, 12, 9, 30, 0)
            return value if tz is None else value.replace(tzinfo=tz)

    monkeypatch.setattr("agent.tools.rebalance_plan_tool.datetime", FixedDateTime)
    monkeypatch.setattr("portfolio.paper_position.now_text", lambda: "2026-06-12 09:30:00")


def test_agent_paper_trade_execution_after_confirmation(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, price=10.0)
    preview = preview_add_stock_to_paper("u1", "600519", output_dir=output_dir, db_path=db_path)
    result = execute_confirmed_paper_trade_plan(
        "u1",
        preview.data["plan_id"],
        preview.data["confirmation_token"],
        output_dir=output_dir,
        db_path=db_path,
    )
    assert result.success
    assert result.data["order_ids"]
    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1")
    assert storage.load_positions("u1")
    repo = AgentRepository(db_path)
    approvals = repo.store.list("action_approvals", {"plan_id": preview.data["plan_id"]})
    assert any(row["status"] == "confirmed" for row in approvals)
    commits = repo.store.list("action_commits", {"plan_id": preview.data["plan_id"]})
    assert len(commits) == 1
    assert commits[0]["status"] == "executed"

    duplicate = execute_confirmed_paper_trade_plan(
        "u1",
        preview.data["plan_id"],
        preview.data["confirmation_token"],
        output_dir=output_dir,
        db_path=db_path,
    )
    assert duplicate.success is False
    assert "already_executed" in duplicate.errors
    assert len(repo.store.list("action_commits", {"plan_id": preview.data["plan_id"]})) == 1


def test_agent_adjust_position_execution_after_confirmation(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True, cash=100000.0)
    preview = preview_adjust_position_to_weight(
        "u1",
        "000001",
        position_adjustment_ratio=0.5,
        output_dir=output_dir,
        db_path=db_path,
    )
    assert preview.success
    result = execute_confirmed_paper_trade_plan(
        "u1",
        preview.data["plan_id"],
        preview.data["confirmation_token"],
        output_dir=output_dir,
        db_path=db_path,
    )
    assert result.success
    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1")
    positions = storage.load_positions("u1")
    orders = storage.load_orders("u1")
    adjusted = [item for item in positions if item.stock_code == "000001"]
    assert adjusted
    assert adjusted[0].quantity == 500.0
    assert orders
    assert orders[-1].paper_action == "paper_reduce"
    assert orders[-1].quantity == 500.0


def test_agent_adjust_position_revalidation_rejects_changed_business_state(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True, cash=100000.0)
    preview = preview_adjust_position_to_weight(
        "u1",
        "000001",
        position_adjustment_ratio=0.5,
        output_dir=output_dir,
        db_path=db_path,
    )
    assert preview.success

    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1")
    account = storage.load_account("paper_u1")
    assert account is not None
    account = replace(account, cash=account.cash + 1.0, total_assets=account.total_assets + 1.0)
    storage.save_account(account)

    result = execute_confirmed_paper_trade_plan(
        "u1",
        preview.data["plan_id"],
        preview.data["confirmation_token"],
        output_dir=output_dir,
        db_path=db_path,
    )

    assert result.success is False
    assert "business_state_changed" in result.errors
    commits = AgentRepository(db_path).store.list("action_commits", {"plan_id": preview.data["plan_id"]})
    assert commits == []


def test_agent_adjust_position_sub_lot_answer_is_actionable(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=False, cash=100000.0)
    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1")
    account = storage.load_account("paper_u1")
    assert account is not None
    storage.save_positions(
        [
            create_position(
                "u1",
                "000001",
                stock_name="Ping An Bank",
                quantity=100,
                cost_price=12.0,
                current_price=12.0,
                total_assets=account.total_assets,
            )
        ]
    )
    query = "000001 " + "\u4ed3\u4f4d\u592a\u9ad8\u4e86\uff0c\u51cf\u534a"
    result = run_agent_request(query, user_id="u1", output_dir=output_dir, db_path=db_path)
    assert not result["success"]
    assert result["intent"] == "one_time_position_operation"
    assert "no_executable_lot_quantity" in result["result"]["errors"]
    assert "\u4e0d\u8db3\u4e00\u624b" in result["answer"]


def test_agent_adjust_position_preview_answer_includes_cascade_effects(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=False, cash=100000.0)
    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1")
    account = storage.load_account("paper_u1")
    assert account is not None
    storage.save_positions(
        [
            create_position(
                "u1",
                "000001",
                stock_name="Ping An Bank",
                quantity=100,
                cost_price=12.0,
                current_price=12.0,
                total_assets=account.total_assets,
            )
        ]
    )
    query = "000001 " + "\u5356\u51fa100\u80a1"
    result = run_agent_request(query, user_id="u1", output_dir=output_dir, db_path=db_path)
    assert result["success"]
    assert result["intent"] == "one_time_position_operation"
    assert "\u786e\u8ba4\u540e\u8fde\u9501\u5f71\u54cd" in result["answer"]
    assert "\u4f1a\u66f4\u65b0\u6a21\u62df\u76d8\u8d26\u6237" in result["answer"]
    assert result["result"]["data"]["plan_id"]
    assert result["runtime"]["status"] == "waiting_for_approval"
    proposal = AgentRepository(db_path).get_action_proposal(result["result"]["data"]["plan_id"])
    assert proposal is not None
    assert proposal["run_id"] == result["run_id"]
