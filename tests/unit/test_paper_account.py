from __future__ import annotations

import pytest

from portfolio.paper_account import (
    create_default_account,
    load_account_json,
    save_account_json,
    update_account_metrics,
)


def test_create_default_paper_account() -> None:
    account = create_default_account("user_001", initial_cash=200000)

    assert account.account_id == "paper_user_001"
    assert account.cash == 200000
    assert account.total_assets == 200000
    assert account.is_paper_trading is True


def test_update_account_metrics_calculates_returns() -> None:
    account = create_default_account("user_001", initial_cash=100000)
    updated = update_account_metrics(account, positions_value=10000, previous_total_assets=100000)

    assert updated.total_assets == 110000
    assert updated.daily_return == pytest.approx(0.10)
    assert updated.cumulative_return == pytest.approx(0.10)


def test_account_json_roundtrip(tmp_path) -> None:
    path = tmp_path / "paper_account.json"
    account = create_default_account("user_001", initial_cash=100000)

    save_account_json(account, path)
    loaded = load_account_json(path)

    assert loaded.account_id == account.account_id
    assert loaded.cash == account.cash
