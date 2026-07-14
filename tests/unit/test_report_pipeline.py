from __future__ import annotations

from pipelines.report_pipeline import COMPLIANCE_TEXT, run_report_pipeline
from pipelines.schemas import PipelineContext, PredictionPipelineResult, RAGPipelineResult, SignalFusionPipelineResult
from scoring.schemas import FusionOutput, ModelPredictionSignal


def test_report_pipeline_generates_markdown_report(tmp_path) -> None:
    context = PipelineContext(user_id="u1", trade_date="2026-06-11", output_dir=tmp_path / "outputs")
    prediction_result = PredictionPipelineResult(status="success", message="ok", input_count=1, output_count=1, predictions=[ModelPredictionSignal("2026-06-11", "000001", 0.9)])
    rag_result = RAGPipelineResult(status="success", message="ok", input_count=1, output_count=0)
    scoring_result = SignalFusionPipelineResult(
        status="success",
        message="ok",
        input_count=1,
        output_count=1,
        fusion_outputs=[
            FusionOutput(
                user_id="u1",
                trade_date="2026-06-11",
                stock_code="000001",
                original_pred_score=0.9,
                original_pred_rank=1,
                original_score=0.9,
                original_rank=1,
                news_adjustment=0,
                user_adjustment=0,
                combined_adjustment=0,
                position_adjustment_ratio=1,
                target_weight=0.08,
                confidence="high",
            )
        ],
    )

    result = run_report_pipeline(context, prediction_result, rag_result, scoring_result)

    assert result.report_path.endswith("daily_pipeline_report_20260611.md")
    assert "neutral: 1" in result.report_text
    assert COMPLIANCE_TEXT in result.report_text
    assert (tmp_path / "outputs" / "reports" / "daily_pipeline_report_20260611.md").exists()
