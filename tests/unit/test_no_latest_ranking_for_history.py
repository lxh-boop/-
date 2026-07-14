import pandas as pd

from pipelines.historical_prediction_loader import load_historical_predictions


def test_no_latest_ranking_for_history_even_when_latest_exists(tmp_path) -> None:
    pd.DataFrame([{"trade_date": "latest", "code": "999999", "score": 1.0}]).to_csv(
        tmp_path / "ranking_latest.csv", index=False
    )

    result = load_historical_predictions("2026-04-01", user_id="u1", output_dir=tmp_path, top_k=10)

    assert result.status == "missing_prediction"
    assert not result.predictions
