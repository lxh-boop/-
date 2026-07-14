import pytest

from portfolio.paper_strategy_config import PaperStrategyConfig
from portfolio.trading_cost_config import TradingCostConfig, cost_config_from_dict


def test_default_maximum_cash_ratio_is_30_percent() -> None:
    cfg = PaperStrategyConfig(user_id="u1")
    assert cfg.target_cash_ratio == 0.05
    assert cfg.maximum_cash_ratio == 0.30


def test_cash_ratio_config_validation() -> None:
    with pytest.raises(ValueError):
        PaperStrategyConfig(target_cash_ratio=0.31, maximum_cash_ratio=0.31)
    with pytest.raises(ValueError):
        TradingCostConfig(target_cash_ratio=0.20, maximum_cash_ratio=0.10)


def test_trading_cost_config_reads_legacy_minimum_cash_ratio() -> None:
    cfg = cost_config_from_dict({"minimum_cash_ratio": 0.07}, "u1")
    assert cfg.target_cash_ratio == 0.07
    assert cfg.maximum_cash_ratio == 0.30
