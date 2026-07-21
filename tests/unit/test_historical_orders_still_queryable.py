from app.classic_services import load_daily_order_snapshot
from strategy_position_test_utils import (
    create_position_preview,
    position_service,
    setup_position_account,
)


def test_historical_orders_still_queryable(tmp_path) -> None:
    setup_position_account(tmp_path)
    preview = create_position_preview(tmp_path)
    committed = position_service(tmp_path).commit(
        user_id="u1",
        plan_id=preview.data["plan_id"],
        confirmation_token=preview.confirmation_token,
    )

    assert committed.success
    orders = load_daily_order_snapshot(
        "u1",
        "2026-07-16",
        tmp_path / "outputs",
    )
    assert not orders.empty
    assert set(orders["strategy_id"]) == {
        committed.data["strategy_id"]
    }
