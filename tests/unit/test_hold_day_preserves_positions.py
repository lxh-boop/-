from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage
from pipelines.historical_account_replayer import replay_hold_day


def test_hold_day_preserves_positions(tmp_path, monkeypatch) -> None:
    storage = PortfolioStorage(tmp_path / "agent.db", output_dir=tmp_path / "portfolio" / "u1", use_database=False)
    storage.save_account(create_default_account("u1", 100000))
    storage.save_positions([create_position("u1", "000001", quantity=1000, cost_price=10, current_price=10, total_assets=100000)])
    monkeypatch.setattr(
        "pipelines.historical_account_replayer.get_historical_price_lookup",
        lambda codes, trade_date, output_dir="outputs": {"000001": 12},
    )

    replay = replay_hold_day("u1", "2026-05-11", output_dir=tmp_path, db_path=tmp_path / "agent.db")

    assert replay.status == "success"
    assert len(replay.positions) == 1
    assert replay.positions[0].quantity == 1000
    assert replay.positions[0].current_price == 12

