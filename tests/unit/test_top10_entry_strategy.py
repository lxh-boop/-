from portfolio.paper_account import create_default_account
from portfolio.rebalance_rules import build_rebalance_plan


def _candidate(rank: int) -> dict:
    return {
        "stock_code": f"{rank:06d}",
        "rank": rank,
        "final_score": 1 - rank / 100,
        "final_action": "keep",
        "action": "buy",
        "current_price": 10,
    }


def test_top10_entry_strategy() -> None:
    plan = build_rebalance_plan(
        "u1",
        "2026-04-01",
        [_candidate(rank) for rank in range(1, 13)],
        account=create_default_account("u1", 100000),
        entry_top_k=10,
        hold_buffer_rank=15,
        max_positions=10,
    )

    buy_codes = {item.stock_code for item in plan.decisions if item.action == "buy"}

    assert "000010" in buy_codes
    assert "000011" not in buy_codes

