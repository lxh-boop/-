from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.schemas import PipelineContext
from scoring.schemas import FusionOutput


def test_missing_price_does_not_default_to_one(tmp_path) -> None:
    output = FusionOutput(
        user_id="u1",
        trade_date="2026-06-12",
        stock_code="000001",
        original_pred_score=0.9,
        original_pred_rank=1,
        original_score=0.9,
        original_rank=1,
        news_adjustment=0,
        user_adjustment=0,
        combined_adjustment=0,
        position_adjustment_ratio=1,
        original_target_weight=0.08,
        target_weight=0.08,
        confidence="high",
        current_price=None,
    )
    context = PipelineContext(user_id="u1", trade_date="latest", output_dir=tmp_path / "outputs", db_path=tmp_path / "agent_quant.db", paper_trading_enabled=True)

    result = run_paper_trading_pipeline(context, [output])

    assert result.orders == []
    assert result.plan.execution_diagnostics["valid_price_count"] == 0
    assert "缺少有效市场价格" in "；".join(result.plan.execution_diagnostics["reasons"])
