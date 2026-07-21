from database.connection import initialize_database
from strategies.runtime_resolver import StrategyRuntimeResolver


def test_runtime_resolver_returns_default_for_unbound_user(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    initialize_database(db_path)
    runtime = StrategyRuntimeResolver(
        db_path=db_path,
        output_dir=tmp_path / "outputs",
    ).resolve(
        user_id="unbound",
        account_id="paper_unbound",
        as_of_date="2026-07-16",
    )

    assert runtime.source == "builtin_default"
    assert runtime.binding_id == ""
    assert runtime.resolved_config() == {
        "entry_top_k": 10,
        "hold_buffer_rank": 15,
        "max_positions": 10,
        "target_invested_weight": 0.8,
        "minimum_cash_ratio": 0.05,
        "min_rebalance_weight_delta": 0.01,
    }
