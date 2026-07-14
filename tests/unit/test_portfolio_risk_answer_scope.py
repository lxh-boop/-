from __future__ import annotations

from agent.orchestration.result_aggregator import aggregate_multi_task_answer


def test_risk_only_answer_scope_has_no_candidates_or_buy_sell_recommendation() -> None:
    answer = aggregate_multi_task_answer(
        {
            "task_state": {
                "success": True,
                "intent": "portfolio_state",
                "data": {"position_count": 2, "cash": 10000},
            },
            "task_risk": {
                "success": True,
                "intent": "portfolio_risk",
                "data": {
                    "source": "calculated",
                    "risk_report": {
                        "risk_level": "high",
                        "position_count": 2,
                        "cash_ratio": 0.1,
                        "max_single_position": 0.35,
                        "max_drawdown": 0.02,
                        "risk_warnings": ["single position concentration is high"],
                    },
                },
            },
        },
        language="zh",
    )

    forbidden = [
        "\u66f4\u7a33\u5065",
        "\u63a8\u8350\u65b9\u6848",
        "\u5019\u9009\u8bc1\u636e",
        "\u5efa\u8bae\u4e70\u5165",
        "\u5efa\u8bae\u5356\u51fa",
        "proposal",
    ]

    assert "\u7ec4\u5408\u98ce\u9669\u5206\u6790" in answer
    assert "\u98ce\u9669\u63d0\u793a" in answer
    assert not any(item in answer for item in forbidden)


def test_risk_plus_explicit_ranking_can_still_use_recommendation_template() -> None:
    answer = aggregate_multi_task_answer(
        {
            "task_state": {
                "success": True,
                "intent": "portfolio_state",
                "data": {"positions": [{"stock_code": "000001"}]},
            },
            "task_risk": {
                "success": True,
                "intent": "portfolio_risk",
                "data": {"risk_report": {"risk_level": "medium", "position_count": 1}},
            },
            "task_ranking": {
                "success": True,
                "intent": "ranking",
                "data": {"records": [{"stock_code": "000001", "stock_name": "Ping An", "rank": 1}]},
            },
        },
        language="zh",
    )

    assert "\u63a8\u8350\u65b9\u6848" in answer
    assert "\u5019\u9009\u8bc1\u636e" in answer
