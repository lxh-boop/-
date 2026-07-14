import pandas as pd

from app.classic_services import format_classic_ranking_for_display, load_classic_ranking_with_ai_adjustment


def test_classic_ranking_merges_original_and_ai_adjustment(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    rec_dir = output_dir / "recommendations"
    rec_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {"rank": 1, "date": "2026-06-12", "code": "000001", "name": "平安银行", "score": 0.91, "confidence": "high", "risk_score": 0.2},
            {"rank": 2, "date": "2026-06-12", "code": "000002", "name": "万科A", "score": 0.82, "confidence": "medium", "risk_score": 0.4},
        ]
    ).to_csv(output_dir / "ranking_latest.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {
                "stock_code": "000001",
                "target_weight": 0.05,
                "news_adjustment": -0.01,
                "user_adjustment": 0.02,
                "effective_news_adjustment": -0.005,
                "combined_adjustment": 0.015,
                "position_adjustment_ratio": 1.015,
                "reason": "news checked",
                "risk_warning": "",
                "evidence_news_ids": '["n1"]',
                "evidence_chunk_ids": '["c1"]',
                "triggered_rules": "[]",
            }
        ]
    ).to_csv(rec_dir / "final_recommendations_latest.csv", index=False, encoding="utf-8-sig")

    merged = load_classic_ranking_with_ai_adjustment(output_dir=output_dir)
    display = format_classic_ranking_for_display(merged)

    assert merged.loc[0, "stock_code"] == "000001"
    assert merged.loc[0, "pred_rank"] == 1
    assert "final_action" not in merged.columns
    assert merged.loc[0, "combined_adjustment"] == 0.015
    assert "原始预测分" in display.columns
    assert "综合调整" in display.columns
    assert "AI修正原因" in display.columns
