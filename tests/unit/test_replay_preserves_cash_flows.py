from pipelines.historical_account_replayer import replay_hold_day
from portfolio.cash_flow import make_cash_flow, save_cash_flow
from portfolio.storage import PortfolioStorage


def test_replay_preserves_cash_flows(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    db_path = tmp_path / "agent.db"
    flow = make_cash_flow("u1", "deposit", 10000, "2026-04-01", source="backfill")
    save_cash_flow(flow, db_path=db_path, output_dir=output_dir)

    replay_hold_day("u1", "2026-04-01", initial_cash=100000, output_dir=output_dir, db_path=db_path)
    account = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1").load_account("paper_u1")

    assert account is not None
    assert account.net_contribution == 110000
    assert account.daily_return == 0

