import pandas as pd

from pipelines.historical_account_replayer import replay_hold_day
from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage


def test_historical_hold_day_marks_positions_to_market(tmp_path) -> None:
    user_id = "u1"
    root = tmp_path / "portfolio" / user_id
    storage = PortfolioStorage(tmp_path / "agent.db", output_dir=root, use_database=False)
    account = create_default_account(user_id, 100000)
    account = account.__class__(**{**account.to_dict(), "cash": 90000, "total_assets": 100000})
    position = create_position(user_id, "000001", stock_name="A", quantity=1000, cost_price=10, current_price=10, total_assets=100000)
    storage.save_account(account)
    storage.save_positions([position])
    pd.DataFrame([{"trade_date": "2026-04-02", "code": "000001", "score": 0.9, "close": 12.0}]).to_csv(
        tmp_path / "backtest_daily_predictions.csv", index=False
    )

    replay_hold_day(user_id, "2026-04-02", output_dir=tmp_path, db_path=tmp_path / "agent.db")

    nav = pd.read_csv(root / "paper_nav_latest.csv")
    assert float(nav.iloc[-1]["position_market_value"]) == 12000
    assert float(nav.iloc[-1]["composite_nav"]) > 1.0
