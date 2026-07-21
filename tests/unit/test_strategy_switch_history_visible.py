from strategies.binding_repository import StrategyBindingRepository
from strategy_runtime_test_utils import bind_runtime


def test_strategy_switch_history_visible(tmp_path) -> None:
    manifest, first = bind_runtime(tmp_path)
    repository = StrategyBindingRepository(
        tmp_path / "agent_quant.db"
    )
    second = repository.activate(
        user_id="u1",
        account_id="paper_u1",
        strategy_id=manifest.strategy_id,
        strategy_version=manifest.version,
        config_hash=first.config_hash,
        effective_from="2026-01-02",
        source_plan_id="plan_phase7_second",
    )

    history = repository.list_history(
        user_id="u1",
        account_id="paper_u1",
    )
    assert [item.binding_id for item in history] == [
        first.binding_id,
        second.binding_id,
    ]
    assert history[0].status == "replaced"
    assert history[1].status == "active"
