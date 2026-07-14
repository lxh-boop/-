import pandas as pd

from app.classic_services import build_ai_adjustment_detail, format_classic_ranking_for_display, load_classic_ranking_with_ai_adjustment


def test_home_page_data_contains_ai_adjustment_reason_and_evidence(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    rec_dir = output_dir / "recommendations"
    rec_dir.mkdir(parents=True)
    pd.DataFrame([{"rank": 1, "date": "2026-06-12", "code": "000001", "name": "A", "score": 0.9}]).to_csv(
        output_dir / "ranking_latest.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(
        [
            {
                "stock_code": "000001",
                "final_score": 0.8,
                "final_action": "down_weight",
                "reason": "AI adjusted because risk increased.",
                "triggered_rules": "risk_rule",
                "evidence_news_ids": '["n1"]',
                "evidence_chunk_ids": '["c1"]',
                "risk_warning": "risk warning",
            }
        ]
    ).to_csv(rec_dir / "final_recommendations_latest.csv", index=False, encoding="utf-8-sig")

    merged = load_classic_ranking_with_ai_adjustment(output_dir=output_dir)
    display = format_classic_ranking_for_display(merged)
    detail = build_ai_adjustment_detail(merged.iloc[0])

    assert "AI修正原因" in display.columns
    assert detail["reason"] == "AI adjusted because risk increased."
    assert "n1" in detail["evidence_news_ids"]
    assert detail["risk_warning"] == "risk warning"
