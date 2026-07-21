from __future__ import annotations

from strategies.runtime_resolver import StrategyRuntimeResolver


def test_binding_default_fallback_matches_builtin_strategy(tmp_path) -> None:
    resolved = StrategyRuntimeResolver(
        db_path=tmp_path / "agent_quant.db",
        output_dir=tmp_path / "outputs",
    ).resolve(
        user_id="unbound",
        account_id="paper_unbound",
    )

    assert resolved.source == "builtin_default"
    assert resolved.binding_id == ""
    assert resolved.entry_top_k == 10
    assert resolved.hold_buffer_rank == 15
    assert resolved.max_positions == 10
    assert resolved.target_invested_weight == 0.8
    assert resolved.minimum_cash_ratio == 0.05
    assert resolved.min_rebalance_weight_delta == 0.01
