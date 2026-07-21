from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.schemas import PipelineContext
from strategy_runtime_test_utils import bind_runtime, runtime_candidates


def test_pipeline_consumes_runtime_strategy(tmp_path) -> None:
    manifest, binding = bind_runtime(tmp_path)
    result = run_paper_trading_pipeline(
        PipelineContext(
            user_id="u1",
            trade_date="2026-07-16",
            output_dir=tmp_path / "outputs",
            db_path=tmp_path / "agent_quant.db",
            dry_run=True,
        ),
        runtime_candidates(),
    )

    assert result.ok
    assert result.plan.strategy_id == manifest.strategy_id
    assert result.plan.binding_id == binding.binding_id
    assert result.plan.execution_diagnostics["entry_top_k"] == 6
    assert result.plan.execution_diagnostics["top10_target_ratio"] == 0.60
