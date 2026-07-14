from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage
from app.classic_services import load_daily_position_snapshot


def test_historical_position_query(tmp_path) -> None:
    storage = PortfolioStorage(tmp_path / "agent.db", output_dir=tmp_path / "portfolio" / "u1", use_database=False)
    positions = [create_position("u1", "000001", quantity=1000, cost_price=10, current_price=10, total_assets=100000)]
    account = create_default_account("u1", 100000).__class__(
        **{**create_default_account("u1", 100000).to_dict(), "cash": 90000, "total_assets": 100000}
    )
    storage.write_daily_snapshot(account=account, positions=positions, orders=[], trade_date="2026-05-10")

    snapshot = load_daily_position_snapshot("u1", "2026-05-11", output_dir=tmp_path)

    assert not snapshot.empty
    assert snapshot.iloc[0]["stock_code"] == "000001"
