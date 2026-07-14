from __future__ import annotations

from agent.pipeline_tool import get_latest_outputs, run_daily_pipeline
from pipelines.schemas import DailyUpdatePipelineResult, PipelineStatus


def test_run_daily_pipeline_uses_fixed_pipeline_context(tmp_path) -> None:
    seen = {}

    def fake_runner(context, steps=None):
        seen["context"] = context
        seen["steps"] = steps
        return DailyUpdatePipelineResult(status=PipelineStatus.SUCCESS, message="ok")

    result = run_daily_pipeline(
        user_id="u1",
        trade_date="2026-06-11",
        top_k=20,
        dry_run=True,
        paper_trading=False,
        steps=["prediction", "scoring"],
        output_dir=tmp_path,
        runner=fake_runner,
    )

    assert result["ok"] is True
    assert seen["context"].user_id == "u1"
    assert seen["context"].dry_run is True
    assert seen["context"].paper_trading_enabled is False
    assert seen["steps"] == ["prediction", "scoring"]
    assert "broker" in result["note"]


def test_get_latest_outputs_reports_missing_files(tmp_path) -> None:
    result = get_latest_outputs(tmp_path)
    assert result["ok"] is False
    assert result["outputs"]["recommendations_json"]["exists"] is False
