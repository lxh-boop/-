from portfolio.schemas import PaperNavRecord
from strategy_position_test_utils import setup_position_account


def test_historical_nav_still_queryable(tmp_path) -> None:
    storage, _, _ = setup_position_account(tmp_path)
    storage.save_nav_record(
        PaperNavRecord(
            nav_id="nav_u1_20260715",
            user_id="u1",
            account_id="paper_u1",
            trade_date="2026-07-15",
            cash=90000.0,
            position_market_value=10000.0,
            total_assets=100000.0,
        )
    )
    storage.save_nav_record(
        PaperNavRecord(
            nav_id="nav_u1_20260716",
            user_id="u1",
            account_id="paper_u1",
            trade_date="2026-07-16",
            cash=89980.0,
            position_market_value=10000.0,
            total_assets=99980.0,
        )
    )

    history = storage.load_nav_history("u1")
    assert [row["trade_date"] for row in history] == [
        "2026-07-15",
        "2026-07-16",
    ]
