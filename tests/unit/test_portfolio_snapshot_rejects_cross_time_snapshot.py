import pytest

from portfolio.portfolio_snapshot import PortfolioSnapshotConsistencyError, build_portfolio_snapshot


def test_portfolio_snapshot_rejects_cross_time_snapshot() -> None:
    with pytest.raises(PortfolioSnapshotConsistencyError, match="timestamp") as error:
        build_portfolio_snapshot(
            {"user_id": "u1", "account_id": "paper_u1", "cash": 100000, "as_of_date": "2026-07-17"},
            [{"user_id": "u1", "stock_code": "000001", "quantity": 1, "current_price": 12, "as_of_date": "2026-07-16"}],
            user_id="u1",
            account_id="paper_u1",
        )

    assert error.value.code == "cross_time_snapshot"
