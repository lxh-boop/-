from daily_incremental_update import run_post_prediction_ai_adjustment
from pipelines.schemas import BasePipelineResult, DailyUpdatePipelineResult, PipelineStatus, RAGPipelineResult


def test_daily_update_postprocess_runs_ai_adjustment(monkeypatch) -> None:
    captured = {}

    def fake_runner(context, steps):
        captured["context"] = context
        captured["steps"] = steps
        return DailyUpdatePipelineResult(
            status=PipelineStatus.SUCCESS,
            message="ok",
            step_results={
                "prediction": BasePipelineResult(status=PipelineStatus.SUCCESS, output_count=2),
                "rag": RAGPipelineResult(status=PipelineStatus.SUCCESS, output_count=0),
                "scoring": BasePipelineResult(status=PipelineStatus.SUCCESS, output_count=2),
                "report": BasePipelineResult(status=PipelineStatus.SUCCESS, output_count=1),
            },
        )

    monkeypatch.setattr("daily_incremental_update.run_daily_update_pipeline", fake_runner)
    result = run_post_prediction_ai_adjustment(user_id="u1", top_k=30, paper_trading_enabled=True)

    assert captured["context"].user_id == "u1"
    assert captured["context"].top_k == 30
    assert captured["context"].paper_trading_enabled is True
    assert captured["steps"] == ["prediction", "rag", "scoring", "paper", "report"]
    assert result.status == PipelineStatus.SUCCESS
