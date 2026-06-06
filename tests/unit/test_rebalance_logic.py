import numpy as np

from backtest_rebalance import calculate_topk_rebalance, format_code_set


def test_rebalance_keeps_overlap_and_splits_buy_sell():
    result = calculate_topk_rebalance(
        previous_codes=["000001", "000002", "000003"],
        current_codes=["000002", "000003", "000004"],
    )

    assert result.held_codes == {"000002", "000003"}
    assert result.bought_codes == {"000004"}
    assert result.sold_codes == {"000001"}
    assert np.isclose(result.buy_turnover, 1 / 3)
    assert np.isclose(result.sell_turnover, 1 / 3)
    assert np.isclose(result.turnover, 1 / 3)
    assert format_code_set(result.bought_codes) == "000004"


def test_initial_rebalance_only_buys():
    result = calculate_topk_rebalance(
        previous_codes=[],
        current_codes=["000001", "000002"],
    )

    assert result.bought_codes == {"000001", "000002"}
    assert result.sold_codes == set()
    assert np.isclose(result.buy_turnover, 1.0)
    assert np.isclose(result.sell_turnover, 0.0)
    assert np.isclose(result.turnover, 1.0)
