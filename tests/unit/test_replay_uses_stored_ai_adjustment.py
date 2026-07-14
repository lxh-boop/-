from __future__ import annotations

from pipelines.historical_ai_adjustment_loader import load_historical_ai_adjustments
from pipelines.historical_prediction_loader import load_historical_predictions
from stage5q_helpers import write_stage5q_inputs


def test_replay_uses_stored_ai_adjustment(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, count=12)
    prediction = load_historical_predictions("2026-04-01", user_id="u1", output_dir=tmp_path, top_k=30)
    result = load_historical_ai_adjustments("2026-04-01", prediction, user_id="u1", output_dir=tmp_path, top_k=30)
    assert result.status == "success"
    assert len(result.records) == 12
    assert result.records[0]["stored_target_weight"] == "0.08"
