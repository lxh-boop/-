from pipelines.historical_ai_adjustment_loader import load_historical_ai_adjustments
from pipelines.historical_prediction_loader import load_historical_predictions
from stage5q_helpers import write_stage5q_inputs


def test_load_full_ai_adjustments_by_date(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=12)
    prediction = load_historical_predictions("2026-04-01", user_id="u1", output_dir=tmp_path, top_k=0)

    result = load_historical_ai_adjustments(
        "2026-04-01",
        prediction,
        user_id="u1",
        output_dir=tmp_path,
        top_k=10,
        full_results=True,
    )

    assert result.status == "success"
    assert result.full_record_count == 12
    assert len(result.records) == 12
    assert result.original_top10_codes == [f"{index:06d}" for index in range(1, 11)]
