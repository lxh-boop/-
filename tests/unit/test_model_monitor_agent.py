from __future__ import annotations

import json

from agent.model_monitor_agent import ModelMonitorAgent


def test_model_monitor_agent_reports_artifact_status(tmp_path) -> None:
    rec_dir = tmp_path / "recommendations"
    rec_dir.mkdir()
    (rec_dir / "final_recommendations_latest.json").write_text(
        json.dumps([{"stock_code": "000001", "combined_adjustment": 0.0, "position_adjustment_ratio": 1.0}]),
        encoding="utf-8",
    )
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "daily_pipeline_report_20260611.md").write_text("# report", encoding="utf-8")

    result = ModelMonitorAgent().answer("model monitor", output_dir=tmp_path)
    assert result["agent"] == "model_monitor"
    assert "Final recommendations: 1" in result["answer"]
    assert "does not claim statistical model drift detection" in result["answer"]
