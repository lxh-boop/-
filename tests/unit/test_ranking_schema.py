from __future__ import annotations

import pandas as pd
import pytest

from ranking_schema import REQUIRED_RANKING_COLUMNS, normalize_ranking_columns, validate_ranking_schema


def test_ranking_schema_accepts_complete_sample(sample_ranking_df):
    validate_ranking_schema(sample_ranking_df)
    assert set(REQUIRED_RANKING_COLUMNS).issubset(sample_ranking_df.columns)


def test_ranking_code_is_six_digit_string(sample_ranking_df):
    normalized = normalize_ranking_columns(sample_ranking_df)
    assert normalized["code"].tolist() == ["000001", "000002", "000003"]


def test_ranking_rank_starts_at_one_and_increases(sample_ranking_df):
    ranks = sample_ranking_df["rank"].tolist()
    assert ranks[0] == 1
    assert ranks == sorted(ranks)


def test_ranking_numeric_columns(sample_ranking_df):
    normalized = normalize_ranking_columns(sample_ranking_df)
    for col in ["pred_5d_ret", "up_prob", "risk_score", "confidence_score", "score"]:
        assert pd.api.types.is_numeric_dtype(normalized[col])


def test_topk_slice_preserves_schema(sample_ranking_df):
    topk = sample_ranking_df.head(2).copy()
    validate_ranking_schema(topk)
    assert len(topk) == 2


def test_missing_ranking_columns_raise_clear_error(sample_ranking_df):
    broken = sample_ranking_df.drop(columns=["score"])
    with pytest.raises(ValueError, match="ranking 缺少必要字段"):
        validate_ranking_schema(broken)


def test_normalize_fills_missing_optional_columns():
    raw = pd.DataFrame(
        {
            "date": ["2026-06-01"],
            "code": ["1"],
            "name": ["A"],
            "close": [10],
            "raw_score": [0.8],
        }
    )
    normalized = normalize_ranking_columns(raw)
    assert set(REQUIRED_RANKING_COLUMNS).issubset(normalized.columns)
    assert normalized.loc[0, "code"] == "000001"
    assert normalized.loc[0, "rank"] == 1
