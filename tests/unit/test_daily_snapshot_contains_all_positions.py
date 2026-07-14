import pandas as pd

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage


def test_daily_snapshot_contains_all_positions(tmp_path) -> None:
    storage = PortfolioStorage(tmp_path / "agent.db", output_dir=tmp_path / "portfolio" / "u1", use_database=False)
    positions = [
        create_position("u1", "000001", quantity=1000, cost_price=10, current_price=10, total_assets=100000),
        create_position("u1", "000002", quantity=500, cost_price=20, current_price=22, total_assets=100000),
    ]
    account = create_default_account("u1", 100000).__class__(
        **{**create_default_account("u1", 100000).to_dict(), "cash": 79000, "total_assets": 100000}
    )

    storage.write_daily_snapshot(account=account, positions=positions, orders=[], trade_date="2026-05-11")
    df = pd.read_csv(tmp_path / "portfolio" / "u1" / "history" / "positions" / "positions_20260511.csv", dtype={"stock_code": str})

    assert set(df["stock_code"]) == {"000001", "000002"}
    for column in ["trade_date", "available_quantity", "average_cost", "last_price", "position_weight", "source_trade_date"]:
        assert column in df.columns
