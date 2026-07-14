import pandas as pd

from app.pages.ai_paper_trading import build_order_history_table


def test_order_table_only_buy_sell() -> None:
    table = build_order_history_table(
        pd.DataFrame(
            [
                {"trade_date": "2026-04-01", "paper_action": "paper_reduce", "quantity": 100, "stock_code": "000001"},
                {"trade_date": "2026-04-01", "paper_action": "paper_hold", "quantity": 100, "stock_code": "000002"},
                {"trade_date": "2026-04-01", "paper_action": "paper_buy", "quantity": 100, "stock_code": "000003", "executed_price": 5, "order_amount": 500},
                {"trade_date": "2026-04-01", "paper_action": "paper_sell", "quantity": 100, "stock_code": "000004", "executed_price": 6, "order_amount": 600},
            ]
        )
    )

    assert len(table) == 3
