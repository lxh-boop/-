import pandas as pd

from scheduler.user_job_runner import has_existing_orders_for_trade_date


def test_existing_real_orders_make_user_task_idempotent(tmp_path) -> None:
    order_dir = tmp_path / "portfolio" / "u1" / "history" / "orders"
    order_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {"trade_date": "2026-06-11", "paper_action": "paper_buy", "order_quantity": 100},
            {"trade_date": "2026-06-11", "paper_action": "paper_hold", "order_quantity": 0},
        ]
    ).to_csv(order_dir / "orders_20260611.csv", index=False)

    assert has_existing_orders_for_trade_date("u1", "2026-06-11", output_dir=tmp_path)


def test_observation_only_history_does_not_block_user_task(tmp_path) -> None:
    order_dir = tmp_path / "portfolio" / "u1" / "history" / "orders"
    order_dir.mkdir(parents=True)
    pd.DataFrame(
        [{"trade_date": "2026-06-11", "paper_action": "paper_hold", "order_quantity": 0}]
    ).to_csv(order_dir / "orders_20260611.csv", index=False)

    assert not has_existing_orders_for_trade_date("u1", "2026-06-11", output_dir=tmp_path)
