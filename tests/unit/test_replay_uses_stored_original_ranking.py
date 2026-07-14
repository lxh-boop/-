from __future__ import annotations

from pipelines.historical_prediction_loader import load_historical_predictions
from stage5q_helpers import write_stage5q_inputs


def test_replay_uses_stored_original_ranking(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, count=12)
    result = load_historical_predictions("2026-04-01", user_id="u1", output_dir=tmp_path, top_k=30)
    assert result.status == "success"
    assert "ranking_20260401.csv" in result.source
    assert len(result.predictions) == 12
