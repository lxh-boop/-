from __future__ import annotations

import csv
import json

from scoring.final_score import generate_final_recommendations


def test_final_score_batch_outputs_csv_and_json(tmp_path) -> None:
    records, paths = generate_final_recommendations(
        [
            {
                "date": "2026-06-11",
                "code": "000001",
                "name": "Demo",
                "close": 10.5,
                "score": 0.9,
                "rank": 1,
                "confidence": "high",
                "risk_level": "medium",
                "industry": "bank",
            }
        ],
        news_stock_mapping=[
            {
                "news_id": "news_001",
                "stock_code": "000001",
                "impact_direction": "negative",
                "impact_strength": 0.8,
                "impact_confidence": 0.9,
                "mapping_confidence": 0.9,
                "publish_time": "2026-06-11 10:00:00",
                "trade_date": "2026-06-11",
            }
        ],
        user_profile={"user_id": "u1", "profile_type": "balanced"},
        portfolio_risk={"confidence": "high", "stock_industry": "bank"},
        output_dir=tmp_path / "recommendations",
    )

    assert len(records) == 1
    assert paths["latest_csv"].exists()
    assert paths["dated_csv"].exists()
    assert paths["latest_json"].exists()

    with paths["latest_csv"].open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    data = json.loads(paths["latest_json"].read_text(encoding="utf-8"))

    assert rows[0]["stock_code"] == "000001"
    assert float(rows[0]["current_price"]) == 10.5
    assert data[0]["stock_code"] == "000001"
    assert data[0]["current_price"] == 10.5
    assert "final_action" not in data[0]
    assert "combined_adjustment" in data[0]
    assert "position_adjustment_ratio" in data[0]
