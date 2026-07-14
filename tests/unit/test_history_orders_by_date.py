from app.classic_services import list_daily_order_snapshot_dates, load_daily_order_snapshot
from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.schemas import PipelineContext


def test_history_orders_can_be_loaded_by_date(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    context = PipelineContext(user_id="u1", trade_date="latest", decision_time="2026-06-13 10:30:00", output_dir=output_dir, db_path=tmp_path / "agent_quant.db", paper_trading_enabled=True)
    run_paper_trading_pipeline(
        context,
        [
            {"trade_date": "2026-06-12", "stock_code": "000001", "final_score": 0.9, "final_action": "keep", "target_weight": 0.08, "current_price": 5.0}
        ],
    )

    dates = list_daily_order_snapshot_dates("u1", output_dir)
    orders = load_daily_order_snapshot("u1", "2026-06-12", output_dir)

    assert "2026-06-12" in dates
    assert not orders.empty
    assert set(orders["trade_date"]) == {"2026-06-12"}


def test_empty_same_day_run_does_not_overwrite_existing_orders(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    context = PipelineContext(user_id="u1", trade_date="latest", decision_time="2026-06-13 10:30:00", output_dir=output_dir, db_path=tmp_path / "agent_quant.db", paper_trading_enabled=True)
    run_paper_trading_pipeline(
        context,
        [
            {"trade_date": "2026-06-12", "stock_code": "000001", "final_score": 0.9, "final_action": "keep", "target_weight": 0.08, "current_price": 5.0}
        ],
    )
    first_orders = load_daily_order_snapshot("u1", "2026-06-12", output_dir)
    assert not first_orders.empty

    second_context = PipelineContext(user_id="u1", trade_date="latest", decision_time="2026-06-13 10:40:00", output_dir=output_dir, db_path=tmp_path / "agent_quant.db", paper_trading_enabled=True)
    run_paper_trading_pipeline(
        second_context,
        [
            {"trade_date": "2026-06-12", "stock_code": "000001", "final_score": 0.9, "final_action": "keep", "target_weight": 0.08, "current_price": 5.0}
        ],
    )
    second_orders = load_daily_order_snapshot("u1", "2026-06-12", output_dir)

    assert not second_orders.empty
    assert len(second_orders) == len(first_orders)


def test_order_snapshot_dates_ignore_empty_or_watchlist_files(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    orders_dir = output_dir / "portfolio" / "u1" / "history" / "orders"
    orders_dir.mkdir(parents=True)
    (orders_dir / "orders_20260611.csv").write_text(
        "trade_date,stock_code,action,paper_action,quantity,executed_price\n"
        "2026-06-11,000001,watchlist,paper_hold,0,0\n",
        encoding="utf-8",
    )
    (orders_dir / "orders_20260612.csv").write_text(
        "trade_date,stock_code,action,paper_action,quantity,executed_price\n"
        "2026-06-12,000002,buy,paper_buy,100,5\n",
        encoding="utf-8",
    )

    assert list_daily_order_snapshot_dates("u1", output_dir) == ["2026-06-12"]
