from __future__ import annotations

from portfolio.paper_account import create_default_account
from portfolio.paper_order import create_paper_order
from portfolio.paper_position import create_position
from portfolio.portfolio_risk import calculate_portfolio_risk
from portfolio.storage import PortfolioStorage


def test_portfolio_storage_uses_database_first(tmp_path) -> None:
    storage = PortfolioStorage(db_path=tmp_path / "agent_quant.db", output_dir=tmp_path / "portfolio")
    account = create_default_account("user_001", initial_cash=100000)
    position = create_position("user_001", "000001", quantity=100, cost_price=10, current_price=11, total_assets=100000)
    order = create_paper_order("user_001", "2026-06-11", "000001", "buy", 0.01, 11, 100, "paper")

    storage.save_account(account)
    storage.save_positions([position])
    storage.save_order(order)

    assert storage.load_account(account.account_id).account_id == account.account_id
    assert storage.load_positions("user_001")[0].stock_code == "000001"
    assert storage.load_orders("user_001")[0].order_id == order.order_id
    assert storage.account_path.exists()
    assert storage.positions_path.exists()
    assert storage.orders_path.exists()


def test_portfolio_storage_falls_back_to_local_files(tmp_path) -> None:
    storage = PortfolioStorage(output_dir=tmp_path / "portfolio", use_database=False)
    account = create_default_account("user_001", initial_cash=100000)
    position = create_position("user_001", "000001", quantity=100, cost_price=10, current_price=11, total_assets=100000)
    order = create_paper_order("user_001", "2026-06-11", "000001", "buy", 0.01, 11, 100, "paper")
    report = calculate_portfolio_risk("user_001", account, [position], None)

    storage.save_account(account)
    storage.save_positions([position])
    storage.save_order(order)
    storage.save_risk_report(report)

    assert storage.account_path.exists()
    assert storage.positions_path.exists()
    assert storage.orders_path.exists()
    assert storage.risk_report_path.exists()
    assert storage.load_account().account_id == account.account_id
    assert storage.load_positions("user_001")[0].stock_code == "000001"
    assert storage.load_orders("user_001")[0].is_paper_trading is True
    assert storage.load_risk_report()["is_paper_trading"] is True


def test_portfolio_storage_writes_headers_for_empty_latest_files(tmp_path) -> None:
    storage = PortfolioStorage(output_dir=tmp_path / "portfolio", use_database=False)

    storage.save_positions([])
    storage.save_orders([])

    assert storage.positions_latest_path.read_text(encoding="utf-8-sig").startswith("position_id,")
    assert storage.orders_latest_path.read_text(encoding="utf-8-sig").startswith("order_id,")
