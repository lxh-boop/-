from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@pytest.fixture
def fixtures_dir() -> Path:
    return ROOT_DIR / "tests" / "fixtures"


@pytest.fixture
def sample_ranking_df(fixtures_dir: Path) -> pd.DataFrame:
    return pd.read_csv(fixtures_dir / "sample_ranking.csv", dtype={"code": str}, encoding="utf-8-sig")


@pytest.fixture
def sample_backtest_master_df(fixtures_dir: Path) -> pd.DataFrame:
    return pd.read_csv(fixtures_dir / "sample_backtest_master_table.csv", encoding="utf-8-sig")


@pytest.fixture
def sample_daily_returns_df(fixtures_dir: Path) -> pd.DataFrame:
    return pd.read_csv(fixtures_dir / "sample_daily_returns.csv", encoding="utf-8-sig")


@pytest.fixture
def sample_search_results_df(fixtures_dir: Path) -> pd.DataFrame:
    return pd.read_csv(fixtures_dir / "sample_search_results.csv", encoding="utf-8-sig")


@pytest.fixture
def sample_prediction_df() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    stocks = [
        ("000001", "A", 0.30, 0.10),
        ("000002", "B", 0.20, 0.05),
        ("000003", "C", 0.10, -0.02),
    ]
    for date in dates:
        for code, name, pred, future in stocks:
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "name": name,
                    "pred_5d_ret": pred,
                    "raw_score": pred,
                    "score": pred,
                    "future_5d_ret": future,
                }
            )
    return pd.DataFrame(rows)
