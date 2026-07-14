from __future__ import annotations

from pipelines.daily_update_pipeline import run_daily_update_pipeline
from pipelines.schemas import (
    PaperTradingPipelineResult,
    PipelineContext,
    PipelineStatus,
    PredictionPipelineResult,
    RAGPipelineResult,
    ReportPipelineResult,
    SignalFusionPipelineResult,
)
from scoring.schemas import ModelPredictionSignal


def test_daily_update_pipeline_runs_steps_in_order() -> None:
    calls = []
    prediction = ModelPredictionSignal("2026-06-11", "000001", 0.9)

    def prediction_fn(context):
        calls.append("prediction")
        return PredictionPipelineResult(status="success", message="ok", output_count=1, predictions=[prediction])

    def rag_fn(context, predictions):
        calls.append("rag")
        return RAGPipelineResult(status="success", message="ok", input_count=1, output_count=0, evidence=[])

    def scoring_fn(context, predictions, evidence):
        calls.append("scoring")
        return SignalFusionPipelineResult(status="success", message="ok", input_count=1, output_count=1, recommendations=["r"])

    def paper_fn(context, recommendations):
        calls.append("paper")
        return PaperTradingPipelineResult(status="success", message="ok", input_count=1, output_count=0)

    def report_fn(context, **kwargs):
        calls.append("report")
        return ReportPipelineResult(status="success", message="ok", input_count=1, output_count=1)

    result = run_daily_update_pipeline(
        PipelineContext(),
        prediction_fn=prediction_fn,
        rag_fn=rag_fn,
        scoring_fn=scoring_fn,
        paper_fn=paper_fn,
        report_fn=report_fn,
    )

    assert result.status == PipelineStatus.SUCCESS
    assert calls == ["prediction", "rag", "scoring", "paper", "report"]


def test_daily_update_pipeline_returns_clear_error_on_failed_step() -> None:
    def prediction_fn(context):
        return PredictionPipelineResult(status="failed", message="missing ranking", errors=["missing ranking"])

    result = run_daily_update_pipeline(PipelineContext(), prediction_fn=prediction_fn)

    assert result.status == PipelineStatus.FAILED
    assert "prediction step failed" in result.message
    assert result.errors == ["missing ranking"]
