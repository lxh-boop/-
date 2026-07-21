import pytest

from portfolio.portfolio_snapshot import PortfolioSnapshotConsistencyError, build_portfolio_snapshot


def test_portfolio_snapshot_rejects_cross_account() -> None:
    with pytest.raises(PortfolioSnapshotConsistencyError, match="account_id") as error:
        build_portfolio_snapshot(
            {"user_id": "u1", "account_id": "paper_u1", "cash": 100000, "updated_at": "2026-07-17"},
            [{"user_id": "u1", "account_id": "paper_other", "stock_code": "000001", "quantity": 1, "current_price": 12, "updated_at": "2026-07-17"}],
            user_id="u1",
            account_id="paper_u1",
        )

    assert error.value.code == "cross_account_position"
