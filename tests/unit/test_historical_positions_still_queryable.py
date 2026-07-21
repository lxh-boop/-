from dataclasses import replace

from strategy_position_test_utils import setup_position_account


def test_historical_positions_still_queryable(tmp_path) -> None:
    storage, account, positions = setup_position_account(tmp_path)
    storage.write_daily_snapshot(
        account=account,
        positions=positions,
        orders=[],
        trade_date="2026-07-15",
        decision_time="before_strategy_switch",
    )
    changed = [replace(positions[0], quantity=500.0, market_value=5000.0)]
    changed_account = replace(
        account,
        cash=95000.0,
        position_market_value=5000.0,
    )
    storage.save_positions(changed)
    storage.write_daily_snapshot(
        account=changed_account,
        positions=changed,
        orders=[],
        trade_date="2026-07-16",
        decision_time="after_strategy_switch",
    )

    old = storage.load_position_snapshot(
        "2026-07-15",
        "u1",
        fallback=False,
    )
    assert old[0].quantity == 1000.0
    assert storage.load_positions("u1")[0].quantity == 500.0
