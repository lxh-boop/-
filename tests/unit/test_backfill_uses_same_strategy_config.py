from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.schemas import PipelineContext
from strategy_runtime_test_utils import bind_runtime, runtime_candidates


def test_backfill_uses_same_strategy_config(tmp_path) -> None:
    _, binding = bind_runtime(tmp_path)
    common = {
        "user_id": "u1",
        "trade_date": "2026-07-16",
        "output_dir": tmp_path / "outputs",
        "db_path": tmp_path / "agent_quant.db",
        "dry_run": True,
    }
    daily = run_paper_trading_pipeline(
        PipelineContext(**common, execution_source="daily"),
        runtime_candidates(),
    )
    backfill = run_paper_trading_pipeline(
        PipelineContext(**common, execution_source="backfill"),
        runtime_candidates(),
    )

    assert daily.plan.binding_id == binding.binding_id
    assert backfill.plan.binding_id == binding.binding_id
    assert daily.plan.config_hash == backfill.plan.config_hash
    assert daily.plan.resolved_config == backfill.plan.resolved_config
