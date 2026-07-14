from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.schemas import PipelineContext


def test_latest_alias_is_not_saved_as_trade_date_and_decision_time_is_set(tmp_path) -> None:
    context = PipelineContext(user_id="u1", trade_date="latest", decision_time="2026-06-13 10:30:00", output_dir=tmp_path / "outputs", db_path=tmp_path / "agent_quant.db", paper_trading_enabled=True)
    result = run_paper_trading_pipeline(
        context,
        [
            {
                "trade_date": "2026-06-12",
                "stock_code": "000001",
                "stock_name": "A",
                "final_score": 0.9,
                "final_action": "keep",
                "target_weight": 0.08,
                "original_target_weight": 0.08,
                "current_price": 5.0,
            }
        ],
    )

    assert result.plan.trade_date == "2026-06-12"
    assert result.orders
    assert all(order.trade_date == "2026-06-12" for order in result.orders)
    assert all(order.decision_time == "2026-06-13 10:30:00" for order in result.orders)
