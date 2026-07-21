from __future__ import annotations

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage
from strategy_workflow_test_utils import database_path, prepare_proposal


def test_strategy_backtest_does_not_change_formal_account(tmp_path) -> None:
    storage = PortfolioStorage(
        database_path(tmp_path),
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
    before_account = storage.load_account("paper_u1").to_dict()
    before_positions = [
        {
            key: value
            for key, value in item.to_dict().items()
            if key != "updated_at"
        }
        for item in storage.load_positions("u1")
    ]

    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "config",
            "config": {"target_invested_weight": 0.70},
        },
    )

    assert result.success
    assert storage.load_account("paper_u1").to_dict() == before_account
    assert [
        {
            key: value
            for key, value in item.to_dict().items()
            if key != "updated_at"
        }
        for item in storage.load_positions("u1")
    ] == before_positions
