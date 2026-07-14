import pandas as pd

from app.pages.ai_paper_trading import build_order_history_table


def test_watchlist_and_hold_are_not_order_history() -> None:
    table = build_order_history_table(
        pd.DataFrame(
            [
                {"trade_date": "2026-06-12", "paper_action": "paper_hold", "quantity": 0, "stock_code": "000001"},
                {"trade_date": "2026-06-12", "paper_action": "paper_hold", "quantity": 0, "stock_code": "000002"},
                {"trade_date": "2026-06-12", "paper_action": "paper_buy", "quantity": 100, "stock_code": "000003", "executed_price": 5, "order_amount": 500},
            ]
        )
    )

    assert len(table) == 1
    assert table.iloc[0]["股票代码"] == "000003"
