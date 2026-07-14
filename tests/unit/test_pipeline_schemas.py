from __future__ import annotations

from pipelines.schemas import PipelineContext, PipelineStatus, PredictionPipelineResult


def test_pipeline_context_defaults_and_dict() -> None:
    context = PipelineContext()
    data = context.to_dict()

    assert context.user_id == "default"
    assert context.paper_trading_enabled is True
    assert data["output_dir"] == "outputs"
    assert data["db_path"] == ""


def test_pipeline_result_has_standard_fields() -> None:
    result = PredictionPipelineResult(
        status=PipelineStatus.SUCCESS,
        message="ok",
        input_count=1,
        output_count=1,
        output_paths={"ranking": "outputs/ranking_latest.csv"},
    )

    assert result.ok is True
    assert result.to_dict()["status"] == "success"
    assert result.to_dict()["output_paths"]["ranking"].endswith("ranking_latest.csv")
