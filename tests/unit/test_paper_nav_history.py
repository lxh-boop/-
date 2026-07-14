from portfolio.paper_account import create_default_account
from portfolio.performance_metrics import build_nav_record
from portfolio.storage import PortfolioStorage


def test_paper_nav_history_roundtrip(tmp_path) -> None:
    storage = PortfolioStorage(tmp_path / "agent.db", output_dir=tmp_path / "portfolio" / "u1")
    account = create_default_account("u1", 100000)
    record = build_nav_record(account, "2026-04-01", [], previous_total_assets=100000)

    storage.save_nav_record(record)
    history = storage.load_nav_history("u1")

    assert len(history) == 1
    assert history[0]["trade_date"] == "2026-04-01"

