from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


CALIBRATION_TARGET = "future_1d_ret_gt_0"
CALIBRATION_HORIZON_DAYS = 1
CALIBRATION_TOP_K_PER_DATE = 15
DEFAULT_MIN_SAMPLES = 300
DEFAULT_MIN_POSITIVE = 30
DEFAULT_MIN_NEGATIVE = 30
DEFAULT_MIN_UNIQUE_DATES = 5


def _unavailable_report(reason: str, **details: Any) -> dict[str, Any]:
    return {
        "calibrated": False,
        "method": "unavailable",
        "reason": reason,
        "target": CALIBRATION_TARGET,
        "horizon_trading_days": CALIBRATION_HORIZON_DAYS,
        **details,
    }


def _read_prediction_source(
    path: Path,
    *,
    model_name: str,
    source_priority: int,
) -> pd.DataFrame:
    try:
        frame = pd.read_csv(
            path,
            dtype={"code": str},
            usecols=lambda column: column
            in {
                "date",
                "code",
                "rank",
                "score",
                "up_prob",
                "model_name",
                "model_backend",
                "future_1d_ret",
                "t1_ret",
                "t1_up",
            },
        )
    except Exception:
        return pd.DataFrame()

    required = {"date", "code", "up_prob"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    if "model_name" in frame.columns:
        frame = frame[frame["model_name"].astype(str).eq(model_name)]
    elif "model_backend" in frame.columns:
        frame = frame[
            frame["model_backend"].astype(str).eq(f"zoo:{model_name}")
        ]
    elif model_name not in path.stem:
        return pd.DataFrame()
    if frame.empty:
        return pd.DataFrame()

    for column in ("rank", "score", "future_1d_ret", "t1_ret", "t1_up"):
        if column not in frame.columns:
            frame[column] = np.nan
    future_return = pd.to_numeric(
        frame["future_1d_ret"],
        errors="coerce",
    ).where(
        pd.to_numeric(frame["future_1d_ret"], errors="coerce").notna(),
        pd.to_numeric(frame["t1_ret"], errors="coerce"),
    )
    source_up = pd.to_numeric(frame["t1_up"], errors="coerce")
    source_up = source_up.where(source_up.notna(), (future_return > 0.0).astype(float))
    source_up = source_up.where(future_return.notna() | frame["t1_up"].notna())
    frame = frame.loc[:, ["date", "code", "rank", "score", "up_prob"]].copy()
    frame["realized_up"] = source_up
    frame["_source_priority"] = int(source_priority)
    frame["_source_file"] = str(path)
    return frame


def _load_archived_predictions(
    history_dir: str | Path,
    *,
    model_name: str,
    before_date: pd.Timestamp,
    top_k_per_date: int,
) -> tuple[pd.DataFrame, int]:
    directory = Path(history_dir)
    if not directory.exists():
        return pd.DataFrame(), 0

    frames: list[pd.DataFrame] = []

    t1_history = sorted(
        (directory / "backtests" / "predictions").glob(
            f"*_{model_name}_t1_predictions.csv"
        )
    )
    if t1_history:
        frame = _read_prediction_source(
            t1_history[-1],
            model_name=model_name,
            source_priority=10,
        )
        if not frame.empty:
            frames.append(frame)

    standard_backtest = directory / "backtest_daily_predictions.csv"
    if standard_backtest.exists():
        frame = _read_prediction_source(
            standard_backtest,
            model_name=model_name,
            source_priority=20,
        )
        if not frame.empty:
            frames.append(frame)

    for path in sorted(directory.glob("ranking_*.csv")):
        if path.name == "ranking_latest.csv":
            continue
        frame = _read_prediction_source(
            path,
            model_name=model_name,
            source_priority=30,
        )
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame(), 0

    history = pd.concat(frames, ignore_index=True, sort=False)
    source_files = int(history["_source_file"].nunique())
    history["date"] = pd.to_datetime(history["date"], errors="coerce")
    history["code"] = history["code"].astype(str).str.extract(
        r"(\d{1,6})",
        expand=False,
    ).str.zfill(6)
    history["up_prob"] = pd.to_numeric(
        history["up_prob"],
        errors="coerce",
    )
    history["rank"] = pd.to_numeric(history["rank"], errors="coerce")
    history["score"] = pd.to_numeric(history["score"], errors="coerce")
    history = history.dropna(subset=["date", "code", "up_prob"])
    history = history[
        history["date"].lt(before_date)
        & history["up_prob"].between(0.0, 1.0)
    ]
    history = history.sort_values(
        ["_source_priority", "_source_file", "date", "code"],
        kind="stable",
    ).drop_duplicates(["date", "code"], keep="last")
    has_explicit_rank = history.groupby("date", sort=False)["rank"].transform(
        lambda values: values.notna().any()
    )
    history["_rank_sort"] = history["rank"].where(
        has_explicit_rank,
        np.inf,
    )
    history["_fallback_score"] = history["score"].where(
        history["score"].notna(),
        history["up_prob"],
    )
    history = history.sort_values(
        ["date", "_rank_sort", "_fallback_score", "up_prob", "code"],
        ascending=[True, True, False, False, True],
        kind="stable",
    )
    history = history.groupby("date", sort=True, group_keys=False).head(
        max(int(top_k_per_date), 1)
    )
    history["top_position"] = history.groupby("date", sort=False).cumcount() + 1
    return history.loc[
        :, ["date", "code", "up_prob", "realized_up", "top_position"]
    ], source_files


def _realized_labels(feature_data: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "code", "close"}
    if feature_data is None or feature_data.empty:
        return pd.DataFrame()
    if not required.issubset(feature_data.columns):
        return pd.DataFrame()

    labels = feature_data.loc[:, ["date", "code", "close"]].copy()
    labels["date"] = pd.to_datetime(labels["date"], errors="coerce")
    labels["code"] = labels["code"].astype(str).str.extract(
        r"(\d{1,6})",
        expand=False,
    ).str.zfill(6)
    labels["close"] = pd.to_numeric(
        labels["close"],
        errors="coerce",
    ).replace([np.inf, -np.inf], np.nan)
    labels = labels.dropna(subset=["date", "code", "close"])
    labels = labels.drop_duplicates(["date", "code"], keep="last")
    labels = labels.sort_values(["code", "date"], kind="stable")
    next_close = labels.groupby("code", sort=False)["close"].shift(-1)
    labels["future_1d_ret"] = next_close / labels["close"] - 1.0
    labels["future_1d_ret"] = labels["future_1d_ret"].replace(
        [np.inf, -np.inf],
        np.nan,
    )
    labels = labels.dropna(subset=["future_1d_ret"])
    labels["fallback_realized_up"] = (labels["future_1d_ret"] > 0.0).astype(int)
    return labels.loc[:, ["date", "code", "fallback_realized_up"]]


def calibrate_ranking_probabilities(
    ranking: pd.DataFrame,
    *,
    feature_data: pd.DataFrame,
    history_dir: str | Path,
    model_name: str,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    min_positive: int = DEFAULT_MIN_POSITIVE,
    min_negative: int = DEFAULT_MIN_NEGATIVE,
    min_unique_dates: int = DEFAULT_MIN_UNIQUE_DATES,
    top_k_per_date: int = CALIBRATION_TOP_K_PER_DATE,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Calibrate ranking strength with realized next-trading-day outcomes.

    Archived daily rankings are point-in-time model outputs.  Only archives
    strictly earlier than the ranking being calibrated and only labels whose
    next available trading close is already known are eligible.
    """

    calibration_columns = [
        "up_prob_calibrated",
        "calibrated",
        "calibration_method",
        "calibration_sample_count",
        "calibration_positive_count",
        "calibration_positive_rate",
        "calibration_start_date",
        "calibration_end_date",
        "calibration_target",
        "calibration_horizon_days",
        "calibration_top_k",
        "calibration_brier_score",
        "calibration_log_loss",
        "top5_daily_average_up_rate",
        "top10_daily_average_up_rate",
        "top15_daily_average_up_rate",
        "top15_observation_days",
        "top15_complete_days",
        "top15_observation_count",
        "top15_rise_count",
        "top15_start_date",
        "top15_end_date",
    ]
    out = ranking.drop(columns=calibration_columns, errors="ignore").copy()
    out["up_prob_calibrated"] = np.nan
    out["calibrated"] = False
    out["calibration_method"] = "unavailable"

    if out.empty or not {"date", "code", "up_prob"}.issubset(out.columns):
        report = _unavailable_report("ranking_missing_date_code_or_strength")
        out.attrs["probability_calibration"] = report
        return out, report

    ranking_dates = pd.to_datetime(out["date"], errors="coerce").dropna()
    if ranking_dates.empty:
        report = _unavailable_report("ranking_date_unavailable")
        out.attrs["probability_calibration"] = report
        return out, report
    before_date = pd.Timestamp(ranking_dates.max()).normalize()

    history, source_files = _load_archived_predictions(
        history_dir,
        model_name=model_name,
        before_date=before_date,
        top_k_per_date=top_k_per_date,
    )
    labels = _realized_labels(feature_data)
    if history.empty:
        report = _unavailable_report(
            "historical_predictions_unavailable",
            source_files=source_files,
            samples=0,
            top_k_per_date=int(top_k_per_date),
        )
        out.attrs["probability_calibration"] = report
        return out, report

    samples = history.copy()
    if not labels.empty:
        samples = samples.merge(
            labels,
            on=["date", "code"],
            how="left",
            validate="one_to_one",
        )
    else:
        samples["fallback_realized_up"] = np.nan
    samples["up"] = pd.to_numeric(samples["realized_up"], errors="coerce")
    samples["up"] = samples["up"].where(
        samples["up"].notna(),
        pd.to_numeric(samples["fallback_realized_up"], errors="coerce"),
    )
    samples = samples.dropna(subset=["up_prob", "up"])
    samples["up"] = (samples["up"] > 0.0).astype(int)

    # A daily top-15 hit rate is meaningful only after every member of that
    # day's top 15 has a realized next-trading-day label.  In particular, this
    # prevents the most recent, not-yet-realized archive from entering either
    # the global daily average or the per-stock empirical rates.
    observations_by_date = samples.groupby("date", sort=True)["up"].size()
    complete_dates = observations_by_date[
        observations_by_date >= int(top_k_per_date)
    ].index
    samples = samples[samples["date"].isin(complete_dates)].copy()

    sample_count = int(len(samples))
    positive_count = int(samples["up"].sum()) if sample_count else 0
    negative_count = sample_count - positive_count
    unique_dates = int(samples["date"].nunique()) if sample_count else 0
    sample_details = {
        "source_files": source_files,
        "samples": sample_count,
        "positive": positive_count,
        "negative": negative_count,
        "positive_rate": (
            float(positive_count / sample_count)
            if sample_count
            else None
        ),
        "unique_dates": unique_dates,
        "top_k_per_date": int(top_k_per_date),
        "history_mode": "all_available_incremental",
        "start_date": (
            samples["date"].min().strftime("%Y-%m-%d")
            if sample_count
            else ""
        ),
        "end_date": (
            samples["date"].max().strftime("%Y-%m-%d")
            if sample_count
            else ""
        ),
    }
    if unique_dates < int(min_unique_dates):
        report = _unavailable_report(
            "not_enough_unique_realized_dates",
            **sample_details,
        )
        out.attrs["probability_calibration"] = report
        return out, report

    if (
        sample_count < int(min_samples)
        or positive_count < int(min_positive)
        or negative_count < int(min_negative)
    ):
        report = _unavailable_report(
            "not_enough_balanced_realized_samples",
            **sample_details,
        )
        out.attrs["probability_calibration"] = report
        return out, report

    daily_stats = samples.groupby("date", sort=True)["up"].agg(
        observation_count="size",
        rise_count="sum",
    )
    daily_stats["up_rate"] = (
        daily_stats["rise_count"] / daily_stats["observation_count"]
    )
    daily_average_up_rate = float(daily_stats["up_rate"].mean())
    tier_daily_average_up_rates: dict[int, float] = {}
    for tier in (5, 10, int(top_k_per_date)):
        tier_samples = samples[samples["top_position"] <= tier]
        tier_daily_average_up_rates[tier] = float(
            tier_samples.groupby("date", sort=True)["up"].mean().mean()
        )
    complete_days = int(len(daily_stats))

    stock_stats = samples.groupby("code", sort=False)["up"].agg(
        calibration_sample_count="size",
        calibration_positive_count="sum",
    )
    stock_stats["up_prob_calibrated"] = (
        stock_stats["calibration_positive_count"]
        / stock_stats["calibration_sample_count"]
    )
    current_codes = out["code"].astype(str).str.extract(
        r"(\d{1,6})",
        expand=False,
    ).str.zfill(6)
    out["calibration_sample_count"] = current_codes.map(
        stock_stats["calibration_sample_count"]
    ).fillna(0).astype(int)
    out["calibration_positive_count"] = current_codes.map(
        stock_stats["calibration_positive_count"]
    ).fillna(0).astype(int)
    out["up_prob_calibrated"] = current_codes.map(
        stock_stats["up_prob_calibrated"]
    )
    out["calibrated"] = out["calibration_sample_count"] > 0
    method_name = "empirical_stock_top15_next_day_hit_rate"
    out["calibration_method"] = method_name
    out["calibration_positive_rate"] = out["up_prob_calibrated"]
    out["calibration_start_date"] = sample_details["start_date"]
    out["calibration_end_date"] = sample_details["end_date"]
    out["calibration_target"] = CALIBRATION_TARGET
    out["calibration_horizon_days"] = CALIBRATION_HORIZON_DAYS
    out["calibration_top_k"] = int(top_k_per_date)
    out["top5_daily_average_up_rate"] = tier_daily_average_up_rates[5]
    out["top10_daily_average_up_rate"] = tier_daily_average_up_rates[10]
    out["top15_daily_average_up_rate"] = daily_average_up_rate
    out["top15_observation_days"] = int(len(daily_stats))
    out["top15_complete_days"] = complete_days
    out["top15_observation_count"] = sample_count
    out["top15_rise_count"] = positive_count
    out["top15_start_date"] = sample_details["start_date"]
    out["top15_end_date"] = sample_details["end_date"]
    report = {
        **sample_details,
        "calibrated": True,
        "method": method_name,
        "target": CALIBRATION_TARGET,
        "horizon_trading_days": CALIBRATION_HORIZON_DAYS,
        "source": "daily_top15_archives_and_realized_returns",
        "daily_average_up_rate": daily_average_up_rate,
        "daily_average_up_rates": {
            "top5": tier_daily_average_up_rates[5],
            "top10": tier_daily_average_up_rates[10],
            "top15": daily_average_up_rate,
        },
        "complete_days": complete_days,
        "stock_count": int(len(stock_stats)),
    }
    out.attrs["probability_calibration"] = report
    return out, report
