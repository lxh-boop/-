from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ranking_probability_calibration import calibrate_ranking_probabilities


def _write_archived_rankings(
    output_dir: Path,
    *,
    dates: list[str],
    backtest_dates: list[str] | None = None,
    rows_per_date: int = 20,
) -> pd.DataFrame:
    strengths = np.linspace(0.05, 0.95, rows_per_date)
    backtest_records: list[dict[str, object]] = []
    for trade_date in backtest_dates or []:
        for stock_index, strength in enumerate(strengths):
            backtest_records.append(
                {
                    "date": trade_date,
                    "code": f"{stock_index + 1:06d}",
                    "score": float(strength),
                    "up_prob": float(strength),
                    "model_name": "chronos_bolt_small",
                    "model_backend": "zoo:chronos_bolt_small",
                }
            )
    if backtest_records:
        pd.DataFrame(backtest_records).to_csv(
            output_dir / "backtest_daily_predictions.csv",
            index=False,
        )

    for trade_date in dates:
        records = []
        for stock_index, strength in enumerate(strengths):
            code = f"{stock_index + 1:06d}"
            records.append(
                {
                    "date": trade_date,
                    "code": code,
                    "up_prob": float(strength),
                    "model_name": "chronos_bolt_small",
                }
            )
        pd.DataFrame(records).to_csv(
            output_dir
            / f"ranking_{trade_date.replace('-', '')}_chronos_bolt_small.csv",
            index=False,
        )

    all_prediction_dates = list(backtest_dates or []) + dates
    realized_dates = list(pd.to_datetime(all_prediction_dates))
    realized_dates.append(realized_dates[-1] + pd.offsets.BDay(1))
    prices: list[dict[str, object]] = []
    for stock_index, strength in enumerate(strengths):
        code = f"{stock_index + 1:06d}"
        daily_multiplier = 1.02 if stock_index % 2 == 0 else 0.98
        for date_index, trade_date in enumerate(realized_dates):
            prices.append(
                {
                    "date": trade_date,
                    "code": code,
                    "close": 100.0 * daily_multiplier**date_index,
                }
            )
    return pd.DataFrame(prices)


def test_calibration_uses_only_realized_archived_rankings(
    tmp_path: Path,
) -> None:
    feature_data = _write_archived_rankings(
        tmp_path,
        backtest_dates=["2026-05-28", "2026-05-29"],
        dates=[
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-06-04",
            "2026-06-05",
            "2026-06-08",
        ],
    )
    current = pd.DataFrame(
        {
            "date": ["2026-06-09", "2026-06-09", "2026-06-09"],
            "code": ["000019", "000020", "000001"],
            "up_prob": [0.9, 0.8, 0.7],
        }
    )

    calibrated, report = calibrate_ranking_probabilities(
        current,
        feature_data=feature_data,
        history_dir=tmp_path,
        model_name="chronos_bolt_small",
        min_samples=80,
        min_positive=10,
        min_negative=10,
        min_unique_dates=5,
    )

    assert report["calibrated"] is True
    assert report["method"] == "empirical_stock_predicted_up_next_day_hit_rate"
    assert report["samples"] == 80
    assert report["unique_dates"] == 8
    assert report["start_date"] == "2026-05-28"
    assert report["top_k_per_date"] == 15
    assert report["history_mode"] == "all_predicted_up_observations_incremental"
    assert report["prediction_condition"] == "pred_return > 0"
    assert report["target"] == "future_1d_ret_gt_0"
    assert report["horizon_trading_days"] == 1
    assert report["daily_average_up_rates"] == {
        "top5": 2 / 5,
        "top10": 0.5,
        "top15": 7 / 15,
    }
    assert report["daily_average_up_rate"] == 7 / 15
    assert report["complete_days"] == 8
    assert calibrated["calibrated"].tolist() == [True, True, False]
    assert calibrated["up_prob_calibrated"].iloc[0] == 1.0
    assert calibrated["up_prob_calibrated"].iloc[1] == 0.0
    assert pd.isna(calibrated["up_prob_calibrated"].iloc[2])
    assert calibrated["calibration_sample_count"].tolist() == [8, 8, 0]
    assert calibrated["calibration_positive_count"].tolist() == [8, 0, 0]
    assert calibrated["calibration_top_k"].tolist() == [15, 15, 15]
    assert calibrated["top5_daily_average_up_rate"].tolist() == [2 / 5] * 3
    assert calibrated["top10_daily_average_up_rate"].tolist() == [0.5] * 3
    assert calibrated["top15_observation_count"].tolist() == [120, 120, 120]


def test_calibration_does_not_publish_percentile_when_samples_are_insufficient(
    tmp_path: Path,
) -> None:
    feature_data = _write_archived_rankings(
        tmp_path,
        dates=["2026-06-01"],
        rows_per_date=10,
    )
    current = pd.DataFrame(
        {
            "date": ["2026-06-02"],
            "code": ["000001"],
            "up_prob": [0.99],
        }
    )

    calibrated, report = calibrate_ranking_probabilities(
        current,
        feature_data=feature_data,
        history_dir=tmp_path,
        model_name="chronos_bolt_small",
    )

    assert report["calibrated"] is False
    assert report["method"] == "unavailable"
    assert calibrated.loc[0, "calibrated"] == False
    assert pd.isna(calibrated.loc[0, "up_prob_calibrated"])


def test_daily_archives_are_included_incrementally_after_realization(
    tmp_path: Path,
) -> None:
    feature_data = _write_archived_rankings(
        tmp_path,
        dates=["2026-06-01", "2026-06-02"],
    )

    def report_for(signal_date: str) -> dict[str, object]:
        current = pd.DataFrame(
            {
                "date": [signal_date],
                "code": ["000020"],
                "up_prob": [0.9],
            }
        )
        _, report = calibrate_ranking_probabilities(
            current,
            feature_data=feature_data,
            history_dir=tmp_path,
            model_name="chronos_bolt_small",
            min_samples=1,
            min_positive=1,
            min_negative=1,
            min_unique_dates=1,
        )
        return report

    first_report = report_for("2026-06-02")
    second_report = report_for("2026-06-03")

    assert first_report["samples"] == 10
    assert first_report["unique_dates"] == 1
    assert first_report["end_date"] == "2026-06-01"
    assert second_report["samples"] == 20
    assert second_report["unique_dates"] == 2
    assert second_report["end_date"] == "2026-06-02"


def test_explicit_rank_defines_top15_even_when_score_order_differs(
    tmp_path: Path,
) -> None:
    prediction_rows = []
    price_rows = []
    for rank in range(1, 21):
        code = f"{rank:06d}"
        prediction_rows.append(
            {
                "date": "2026-06-01",
                "code": code,
                "rank": rank,
                "score": float(rank),
                "up_prob": float(rank / 20),
                "model_name": "chronos_bolt_small",
            }
        )
        price_rows.extend(
            [
                {"date": "2026-06-01", "code": code, "close": 100.0},
                {
                    "date": "2026-06-02",
                    "code": code,
                    "close": 101.0 if rank <= 15 else 99.0,
                },
            ]
        )
    pd.DataFrame(prediction_rows).to_csv(
        tmp_path / "ranking_20260601_chronos_bolt_small.csv",
        index=False,
    )
    current = pd.DataFrame(
        {
            "date": ["2026-06-02", "2026-06-02"],
            "code": ["000001", "000020"],
            "up_prob": [0.9, 0.8],
        }
    )

    calibrated, report = calibrate_ranking_probabilities(
        current,
        feature_data=pd.DataFrame(price_rows),
        history_dir=tmp_path,
        model_name="chronos_bolt_small",
        min_samples=1,
        min_positive=1,
        min_negative=1,
        min_unique_dates=1,
    )

    assert report["samples"] == 10
    assert calibrated["calibrated"].tolist() == [False, True]
    assert calibrated["calibration_sample_count"].tolist() == [0, 1]
