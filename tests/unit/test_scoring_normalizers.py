from __future__ import annotations

from scoring.normalizers import clamp, normalize_confidence, normalize_rank, normalize_score, safe_float


def test_normalizers_are_safe_for_missing_values() -> None:
    assert safe_float("bad", 0.3) == 0.3
    assert clamp(2.0, 0.0, 1.0) == 1.0
    assert normalize_score(5, 0, 10) == 0.5
    assert normalize_score(None, 0, 10) == 0.0


def test_rank_and_confidence_normalization() -> None:
    assert normalize_rank(1, 10) == 1.0
    assert normalize_rank(10, 10) == 0.0
    assert normalize_confidence("low") < normalize_confidence("medium")
    assert normalize_confidence("high") > normalize_confidence("medium")
    assert normalize_confidence(1.5) == 1.0
