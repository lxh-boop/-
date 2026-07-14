import pytest


def test_actual_position_plus_cash_equals_100_percent() -> None:
    total_assets = 100000.0
    cash = 23000.0
    position_market_value = 77000.0

    assert cash / total_assets + position_market_value / total_assets == pytest.approx(1.0)
