from __future__ import annotations

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage
from strategy_binding_test_utils import (
    confirm_binding,
    create_binding_plan,
    register_strategy,
)


def test_activate_binding_does_not_change_positions_or_account(tmp_path) -> None:
    storage = PortfolioStorage(
        tmp_path / "agent_quant.db",
        output_dir=tmp_path / "outputs" / "portfolio" / "u1",
    )
    storage.save_account(create_default_account("u1", initial_cash=100000))
    storage.save_positions(
        [
            create_position(
                "u1",
                "000001",
                quantity=100,
                cost_price=10,
                current_price=11,
                total_assets=100000,
            )
        ]
    )
    account_bytes = storage.account_path.read_bytes()
    position_bytes = storage.positions_path.read_bytes()
    manifest = register_strategy(tmp_path)
    result = confirm_binding(
        tmp_path,
        create_binding_plan(tmp_path, manifest),
    )

    assert result.success
    assert result.data["positions_changed"] is False
    assert result.data["orders_created"] is False
    assert storage.account_path.read_bytes() == account_bytes
    assert storage.positions_path.read_bytes() == position_bytes
