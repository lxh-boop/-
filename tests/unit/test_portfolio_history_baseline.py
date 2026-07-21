from __future__ import annotations

from dataclasses import replace

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage


def _position(quantity: float, trade_price: float):
    return create_position(
        "phase0_user",
        "000001",
        "S1",
        quantity=quantity,
        cost_price=9.0,
        current_price=trade_price,
        total_assets=100000.0,
        industry="I1",
    )


def test_current_positions_can_change_without_overwriting_history(tmp_path) -> None:
    output_dir = tmp_path / "outputs" / "portfolio" / "phase0_user"
    storage = PortfolioStorage(
        output_dir=output_dir,
        use_database=False,
    )
    base_account = create_default_account(
        "phase0_user",
        initial_cash=100000.0,
    )
    first_account = replace(
        base_account,
        cash=90000.0,
        position_market_value=10000.0,
        total_assets=100000.0,
    )
    second_account = replace(
        base_account,
        cash=86800.0,
        position_market_value=13200.0,
        total_assets=100000.0,
    )
    first = [_position(1000.0, 10.0)]
    second = [_position(1200.0, 11.0)]

    storage.save_positions(first)
    storage.write_daily_snapshot(
        account=first_account,
        positions=first,
        orders=[],
        trade_date="2026-07-15",
        decision_time="phase0_first",
    )
    storage.save_positions(second)
    storage.write_daily_snapshot(
        account=second_account,
        positions=second,
        orders=[],
        trade_date="2026-07-16",
        decision_time="phase0_second",
    )

    assert storage.load_positions("phase0_user")[0].quantity == 1200.0
    assert storage.load_position_snapshot(
        "2026-07-15",
        "phase0_user",
        fallback=False,
    )[0].quantity == 1000.0
    assert storage.load_position_snapshot(
        "2026-07-16",
        "phase0_user",
        fallback=False,
    )[0].quantity == 1200.0
    assert (
        output_dir
        / "history"
        / "accounts"
        / "account_20260715.json"
    ).exists()
    assert (
        output_dir
        / "history"
        / "positions"
        / "positions_20260715.csv"
    ).exists()
