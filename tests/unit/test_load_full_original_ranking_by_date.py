from pipelines.historical_prediction_loader import load_historical_predictions
from stage5q_helpers import write_stage5q_inputs


def test_load_full_original_ranking_by_date(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=12)

    result = load_historical_predictions("2026-04-01", user_id="u1", output_dir=tmp_path, top_k=0)

    assert result.status == "success"
    assert len(result.predictions) == 12
    assert "ranking_20260401.csv" in result.source
