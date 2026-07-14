from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.schemas import PipelineContext


def test_backfill_pipeline_path_uses_new_allocator(tmp_path) -> None:
    context = PipelineContext(
        user_id="u1",
        trade_date="2026-04-01",
        output_dir=tmp_path / "outputs",
        db_path=tmp_path / "agent.db",
        top_k=15,
        paper_trading_enabled=True,
    )
    recommendations = [
        {"stock_code": "000001", "rank": 1, "final_action": "keep", "final_score": 0.99, "target_weight": 0.05, "current_price": 200.0},
        {"stock_code": "000002", "rank": 2, "final_action": "keep", "final_score": 0.80, "target_weight": 0.20, "current_price": 5.0},
    ]

    result = run_paper_trading_pipeline(context, recommendations)

    assert result.plan.execution_diagnostics["allocation_details"]
    assert "redistributed_cash" in result.plan.execution_diagnostics
