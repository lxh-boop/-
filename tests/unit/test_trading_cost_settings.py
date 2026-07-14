from portfolio.storage import PortfolioStorage
from portfolio.trading_cost_config import TradingCostConfig


def test_trading_cost_settings_roundtrip(tmp_path) -> None:
    storage = PortfolioStorage(tmp_path / "agent.db", output_dir=tmp_path / "portfolio" / "u1")
    storage.save_trading_settings(TradingCostConfig(user_id="u1", buy_cost_rate=0.001, sell_cost_rate=0.002))

    loaded = storage.load_trading_settings("u1")

    assert loaded.buy_cost_rate == 0.001
    assert loaded.sell_cost_rate == 0.002
    assert loaded.entry_top_k == 10

