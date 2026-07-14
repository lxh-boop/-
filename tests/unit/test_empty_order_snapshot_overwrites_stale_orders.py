import pandas as pd

from portfolio.paper_account import create_default_account
from portfolio.storage import PortfolioStorage


def test_empty_order_snapshot_overwrites_stale_orders(tmp_path) -> None:
    storage = PortfolioStorage(tmp_path / "agent.db", output_dir=tmp_path / "portfolio" / "u1", use_database=False)
    stale_path = tmp_path / "portfolio" / "u1" / "history" / "orders" / "orders_20260401.csv"
    stale_path.parent.mkdir(parents=True)
    stale_path.write_text(
        "trade_date,stock_code,action,paper_action,quantity,executed_price\n"
        "2026-04-01,000001,buy,paper_buy,100,10\n",
        encoding="utf-8-sig",
    )

    storage.write_daily_snapshot(account=create_default_account("u1"), positions=[], orders=[], trade_date="2026-04-01")
    df = pd.read_csv(stale_path, encoding="utf-8-sig")

    assert df.empty

