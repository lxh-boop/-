from app.pages.ai_paper_trading import build_today_action_table


def test_ui_action_table_does_not_render_ai_action_labels() -> None:
    table = build_today_action_table(
        [
            {
                "stock_code": "1",
                "stock_name": "A",
                "paper_action": "paper_buy",
                "target_weight": 0.05,
                "current_weight": 0.0,
                "order_amount": 1000,
                "order_quantity": 100,
                "news_adjustment": 0.0,
                "user_adjustment": 0.0,
                "effective_news_adjustment": 0.0,
                "combined_adjustment": 0.0,
                "position_adjustment_ratio": 1.0,
                "reason": "numeric reason",
            }
        ]
    )

    rendered = "\n".join([*map(str, table.columns), *map(str, table.iloc[0].tolist())])
    for forbidden in ["来源动作", "最终动作", "观察名单", "排除", "降低仓位", "保留"]:
        assert forbidden not in rendered

