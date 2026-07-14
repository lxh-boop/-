from __future__ import annotations

import json

from agent.recommendation_tool import (
    explain_recommendation_fields,
    get_latest_recommendations,
    get_recommendation_by_stock,
)


def test_recommendation_tool_reads_latest_json(tmp_path) -> None:
    rec_dir = tmp_path / "recommendations"
    rec_dir.mkdir()
    (rec_dir / "final_recommendations_latest.json").write_text(
        json.dumps(
            [
                {
                    "stock_code": "000001",
                    "stock_name": "Ping An Bank",
                    "combined_adjustment": -0.2,
                    "position_adjustment_ratio": 0.8,
                    "confidence": "medium",
                }
            ]
        ),
        encoding="utf-8",
    )

    latest = get_latest_recommendations(tmp_path)
    assert latest["total_count"] == 1
    assert latest["adjustment_counts"]["negative"] == 1

    stock = get_recommendation_by_stock("000001.SZ", tmp_path)
    assert stock["ok"] is True
    assert stock["record"]["stock_code"] == "000001"

    fields = explain_recommendation_fields()
    assert "final_action" not in fields["fields"]
    assert "combined_adjustment" in fields["fields"]
    assert "not real trading instructions" in fields["note"]
