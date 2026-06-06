from __future__ import annotations

from confidence_scoring import add_confidence_scores
from risk_scoring import add_risk_scores


def test_risk_scores_have_valid_levels(sample_ranking_df):
    out = add_risk_scores(sample_ranking_df)
    assert out["risk_score"].between(0, 1).all()
    assert set(out["risk_level"]).issubset({"高", "中", "低", "未知"})
    assert out["risk_detail"].notna().all()


def test_confidence_scores_have_valid_levels(sample_ranking_df):
    risky = add_risk_scores(sample_ranking_df)
    out = add_confidence_scores(risky, calibration_report={"calibrated": True, "brier": 0.1})
    assert out["confidence_score"].between(0, 1).all()
    assert set(out["confidence"]).issubset({"高", "中", "低", "未知"})
    assert out["confidence_detail"].notna().all()


def test_empty_risk_confidence_frames_do_not_crash(sample_ranking_df):
    empty = sample_ranking_df.iloc[0:0].copy()
    assert add_risk_scores(empty).empty
    assert add_confidence_scores(empty).empty
