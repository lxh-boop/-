from portfolio.rebalance_rules import build_rebalance_plan
from portfolio.paper_account import create_default_account


def test_recursive_lot_reallocation_has_no_backup_pool() -> None:
    candidates = [
        {
            "stock_code": f"{rank:06d}",
            "stock_name": f"S{rank}",
            "original_rank": rank,
            "score": 1.0,
            "position_adjustment_ratio": 1.0,
            "current_price": 1000.0 if rank == 10 else 10.0,
        }
        for rank in range(1, 16)
    ]

    plan = build_rebalance_plan(
        user_id="u1",
        trade_date="2026-04-01",
        candidates=candidates,
        account=create_default_account("u1", initial_cash=100000),
        strategy_mode="hierarchical_top10",
    )

    diagnostics = plan.execution_diagnostics
    assert diagnostics.get("backup_pool_max_rank") == 0
    assert diagnostics.get("backup_candidate_count", 0) == 0
    assert diagnostics.get("replacement_candidates", []) == []
