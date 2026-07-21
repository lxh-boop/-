from strategies.runtime_resolver import StrategyRuntimeResolver
from strategy_runtime_test_utils import bind_runtime


def test_runtime_resolver_returns_binding_strategy(tmp_path) -> None:
    manifest, binding = bind_runtime(tmp_path)
    runtime = StrategyRuntimeResolver(
        db_path=tmp_path / "agent_quant.db",
        output_dir=tmp_path / "outputs",
    ).resolve(
        user_id="u1",
        account_id="paper_u1",
        as_of_date="2099-01-01",
    )

    assert runtime.strategy_id == manifest.strategy_id
    assert runtime.binding_id == binding.binding_id
    assert runtime.entry_top_k == 6
    assert runtime.target_invested_weight == 0.60
