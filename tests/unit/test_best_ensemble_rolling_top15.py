from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT / "scripts" / "model_precision" / "evaluate_best_ensemble_rolling_top15.py"
)
SPEC = importlib.util.spec_from_file_location("best_ensemble_rolling_top15", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_rolling_periods_switches_from_batches_to_daily_without_overlap() -> None:
    dates = pd.to_datetime(
        [
            "2025-12-26",
            "2025-12-29",
            "2025-12-30",
            "2025-12-31",
            "2026-01-05",
            "2026-01-06",
        ]
    )

    periods = MODULE.rolling_periods(
        dates,
        retrain_every=3,
        daily_from=pd.Timestamp("2026-01-01"),
    )

    assert [[str(value.date()) for value in period] for period in periods] == [
        ["2025-12-26", "2025-12-29", "2025-12-30"],
        ["2025-12-31"],
        ["2026-01-05"],
        ["2026-01-06"],
    ]


def test_rolling_periods_rejects_invalid_retraining_cadence() -> None:
    try:
        MODULE.rolling_periods(
            [pd.Timestamp("2026-01-05")],
            retrain_every=0,
            daily_from=None,
        )
    except ValueError as error:
        assert "retrain_every" in str(error)
    else:
        raise AssertionError("Expected invalid cadence to be rejected")


def test_metrics_require_exactly_fifteen_rows_per_day() -> None:
    complete = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05"] * 15 + ["2026-01-06"] * 15),
            "code": [f"{index:06d}" for index in range(30)],
            "score": list(range(30)),
            "label_up": [1] * 9 + [0] * 6 + [1] * 6 + [0] * 9,
        }
    )
    incomplete = complete.iloc[:-1].copy()

    complete_metrics = MODULE._metrics(complete, "score")
    incomplete_metrics = MODULE._metrics(incomplete, "score")

    assert complete_metrics["precision"] == 0.5
    assert complete_metrics["all_days_have_15"] is True
    assert incomplete_metrics["all_days_have_15"] is False
