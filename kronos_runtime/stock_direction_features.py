from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


NON_FEATURE_COLUMNS = {
    "date",
    "code",
    "future_1d_ret",
    "label_up",
    "model_name",
    "model_backend",
    "model_version",
}


def _numeric(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")


def _rolling_by_code(
    frame: pd.DataFrame,
    column: str,
    window: int,
    *,
    shift: int = 0,
    statistic: str = "mean",
    minimum: int | None = None,
) -> pd.Series:
    values = frame.groupby("code", sort=False)[column]
    if shift:
        source = values.shift(shift)
        grouped = source.groupby(frame["code"], sort=False)
    else:
        grouped = values
    rolling = grouped.rolling(
        window,
        min_periods=minimum or max(3, window // 3),
    )
    result = getattr(rolling, statistic)().reset_index(level=0, drop=True)
    return result.reindex(frame.index)


def _prediction_features(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        dtype={"code": str},
        usecols=[
            "date",
            "code",
            "rank",
            "score",
            "up_prob",
            "pred_return",
            "future_1d_ret",
        ],
    )
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["code"] = frame["code"].astype(str).str.split(".").str[0].str.zfill(6)
    _numeric(
        frame,
        ["rank", "score", "up_prob", "pred_return", "future_1d_ret"],
    )
    frame = frame.dropna(subset=["date", "code", "pred_return"]).sort_values(
        ["code", "date"], kind="stable"
    )
    frame["label_up"] = (
        pd.to_numeric(frame["future_1d_ret"], errors="coerce").gt(0.0).astype(float)
    ).where(frame["future_1d_ret"].notna())
    frame["kronos_predicted_up"] = frame["pred_return"].gt(0.0).astype(float)

    by_date = frame.groupby("date", sort=False)
    frame["kronos_rank_pct"] = by_date["pred_return"].rank(
        method="average", ascending=False, pct=True
    )
    frame["existing_rank_pct"] = by_date["rank"].rank(
        method="average", ascending=True, pct=True
    )
    daily_mean = by_date["pred_return"].transform("mean")
    daily_std = by_date["pred_return"].transform("std").replace(0.0, np.nan)
    frame["kronos_pred_z"] = (frame["pred_return"] - daily_mean) / daily_std
    frame["kronos_daily_pred_mean"] = daily_mean
    frame["kronos_daily_pred_std"] = daily_std
    frame["kronos_daily_positive_fraction"] = by_date[
        "kronos_predicted_up"
    ].transform("mean")

    frame["prior_up"] = frame.groupby("code", sort=False)["label_up"].shift(1)
    frame["prior_realized_return"] = frame.groupby("code", sort=False)[
        "future_1d_ret"
    ].shift(1)
    frame["prior_direction_hit"] = (
        frame["prior_up"].eq(
            frame.groupby("code", sort=False)["kronos_predicted_up"].shift(1)
        )
    ).astype(float).where(frame["prior_up"].notna())
    previous_positive = frame.groupby("code", sort=False)[
        "kronos_predicted_up"
    ].shift(1)
    frame["prior_positive_correct"] = (
        previous_positive.mul(frame["prior_up"])
    ).where(frame["prior_up"].notna())

    for window in (5, 20, 60, 120, 250):
        if window <= 60:
            frame[f"stock_return_mean_{window}"] = _rolling_by_code(
                frame,
                "prior_realized_return",
                window,
                minimum=max(3, window // 3),
            )
        frame[f"stock_up_rate_{window}"] = _rolling_by_code(
            frame,
            "prior_up",
            window,
            minimum=max(3, window // 3),
        )
        if window in {20, 60, 120}:
            frame[f"stock_direction_accuracy_{window}"] = _rolling_by_code(
                frame,
                "prior_direction_hit",
                window,
                minimum=max(5, window // 3),
            )
            positive_count = _rolling_by_code(
                frame,
                "kronos_predicted_up",
                window,
                shift=1,
                statistic="sum",
                minimum=max(5, window // 3),
            )
            positive_correct = _rolling_by_code(
                frame,
                "prior_positive_correct",
                window,
                statistic="sum",
                minimum=max(5, window // 3),
            )
            frame[f"stock_positive_precision_{window}"] = (
                positive_correct.add(5.0) / positive_count.add(10.0)
            )

    daily_realized = frame.groupby("date", sort=True)["label_up"].mean()
    for window in (5, 20, 60):
        lagged = daily_realized.shift(1).rolling(
            window, min_periods=max(3, window // 2)
        ).mean()
        frame[f"market_prior_up_rate_{window}"] = frame["date"].map(lagged)

    frame["is_shanghai"] = frame["code"].str.startswith(("6", "9")).astype(float)
    frame["is_chinext"] = frame["code"].str.startswith(("300", "301")).astype(float)
    frame["is_star"] = frame["code"].str.startswith(("688", "689")).astype(float)
    frame["is_beijing"] = frame["code"].str.startswith(("4", "8")).astype(float)
    frame["month"] = frame["date"].dt.month.astype(float)
    frame["weekday"] = frame["date"].dt.weekday.astype(float)
    return frame


def _technical_features(path: str | Path) -> pd.DataFrame:
    columns = [
        "stock_code",
        "trade_date",
        "qfq_open",
        "qfq_high",
        "qfq_low",
        "qfq_close",
        "volume",
        "amount",
    ]
    frame = pd.read_csv(path, dtype={"stock_code": str, "trade_date": str}, usecols=columns)
    frame = frame.rename(columns={"stock_code": "code"})
    frame["code"] = frame["code"].astype(str).str.split(".").str[0].str.zfill(6)
    frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
    _numeric(frame, columns[2:])
    frame = frame.dropna(subset=["date", "code", "qfq_close"]).sort_values(
        ["code", "date"], kind="stable"
    )
    grouped = frame.groupby("code", sort=False)
    previous_close = grouped["qfq_close"].shift(1)
    frame["tech_ret_1"] = frame["qfq_close"] / previous_close - 1.0
    for window in (2, 5, 10, 20, 60, 120):
        frame[f"tech_ret_{window}"] = (
            frame["qfq_close"] / grouped["qfq_close"].shift(window) - 1.0
        )
    for window in (5, 10, 20, 60):
        frame[f"tech_volatility_{window}"] = _rolling_by_code(
            frame,
            "tech_ret_1",
            window,
            statistic="std",
            minimum=max(3, window // 2),
        )
        close_average = _rolling_by_code(
            frame,
            "qfq_close",
            window,
            minimum=max(3, window // 2),
        )
        volume_average = _rolling_by_code(
            frame,
            "volume",
            window,
            minimum=max(3, window // 2),
        )
        frame[f"tech_close_to_ma_{window}"] = frame["qfq_close"] / close_average - 1.0
        frame[f"tech_volume_ratio_{window}"] = frame["volume"] / volume_average
    frame["tech_intraday_return"] = frame["qfq_close"] / frame["qfq_open"] - 1.0
    frame["tech_overnight_gap"] = frame["qfq_open"] / previous_close - 1.0
    frame["tech_range"] = (frame["qfq_high"] - frame["qfq_low"]) / frame["qfq_close"]
    frame["tech_close_position"] = (
        (frame["qfq_close"] - frame["qfq_low"])
        / (frame["qfq_high"] - frame["qfq_low"]).replace(0.0, np.nan)
    )
    frame["tech_log_amount"] = np.log1p(frame["amount"].clip(lower=0.0))
    close = frame["qfq_close"]
    open_ = frame["qfq_open"]
    high = frame["qfq_high"]
    low = frame["qfq_low"]
    volume = frame["volume"]
    price_change = close.diff().where(frame["code"].eq(frame["code"].shift(1)))
    volume_change = volume.diff().where(frame["code"].eq(frame["code"].shift(1)))
    price_abs = price_change.abs()
    volume_abs = volume_change.abs()
    price_up = price_change.clip(lower=0.0)
    price_down = (-price_change).clip(lower=0.0)
    volume_up = volume_change.clip(lower=0.0)
    volume_down = (-volume_change).clip(lower=0.0)
    frame["_alpha_positive"] = close.gt(grouped["qfq_close"].shift(1)).astype(float)
    frame["_alpha_negative"] = close.lt(grouped["qfq_close"].shift(1)).astype(float)
    frame["_alpha_price_abs"] = price_abs
    frame["_alpha_price_up"] = price_up
    frame["_alpha_price_down"] = price_down
    frame["_alpha_volume_abs"] = volume_abs
    frame["_alpha_volume_up"] = volume_up
    frame["_alpha_volume_down"] = volume_down
    frame["_alpha_log_volume"] = np.log1p(volume.clip(lower=0.0))
    frame["_alpha_return"] = frame["tech_ret_1"]
    frame["_alpha_log_volume_change"] = frame.groupby("code", sort=False)[
        "_alpha_log_volume"
    ].diff()
    frame["_alpha_return_volume"] = (
        frame["_alpha_return"] * frame["_alpha_log_volume_change"]
    )
    frame["_alpha_close_log_volume"] = close * frame["_alpha_log_volume"]
    frame["_alpha_weighted_move"] = frame["_alpha_return"].abs() * volume
    frame["_alpha_time"] = frame.groupby("code", sort=False).cumcount().astype(float)
    frame["_alpha_time_squared"] = frame["_alpha_time"].pow(2)
    frame["_alpha_time_close"] = frame["_alpha_time"] * close
    high_low_range = (high - low).replace(0.0, np.nan)
    maximum_oc = pd.concat([open_, close], axis=1).max(axis=1)
    minimum_oc = pd.concat([open_, close], axis=1).min(axis=1)
    alpha: dict[str, pd.Series] = {
        "alpha_kmid": (close - open_) / open_.replace(0.0, np.nan),
        "alpha_klen": (high - low) / open_.replace(0.0, np.nan),
        "alpha_kmid2": (close - open_) / high_low_range,
        "alpha_kup": (high - maximum_oc) / open_.replace(0.0, np.nan),
        "alpha_kup2": (high - maximum_oc) / high_low_range,
        "alpha_klow": (minimum_oc - low) / open_.replace(0.0, np.nan),
        "alpha_klow2": (minimum_oc - low) / high_low_range,
        "alpha_ksft": (2.0 * close - high - low) / open_.replace(0.0, np.nan),
        "alpha_ksft2": (2.0 * close - high - low) / high_low_range,
        "alpha_open0": open_ / close.replace(0.0, np.nan),
        "alpha_high0": high / close.replace(0.0, np.nan),
        "alpha_low0": low / close.replace(0.0, np.nan),
    }
    for window in (5, 10, 20, 30, 60):
        close_group = close.groupby(frame["code"], sort=False)
        high_group = high.groupby(frame["code"], sort=False)
        low_group = low.groupby(frame["code"], sort=False)
        volume_group = volume.groupby(frame["code"], sort=False)
        close_rolling = close_group.rolling(window, min_periods=window)
        high_rolling = high_group.rolling(window, min_periods=window)
        low_rolling = low_group.rolling(window, min_periods=window)
        volume_rolling = volume_group.rolling(window, min_periods=window)
        reset = lambda values: values.reset_index(level=0, drop=True).reindex(frame.index)
        rolling_low = reset(low_rolling.min())
        rolling_high = reset(high_rolling.max())
        alpha[f"alpha_roc_{window}"] = (
            close_group.shift(window) / close.replace(0.0, np.nan)
        )
        alpha[f"alpha_ma_{window}"] = reset(close_rolling.mean()) / close.replace(
            0.0, np.nan
        )
        alpha[f"alpha_std_{window}"] = reset(close_rolling.std()) / close.replace(
            0.0, np.nan
        )
        alpha[f"alpha_max_{window}"] = rolling_high / close.replace(0.0, np.nan)
        alpha[f"alpha_min_{window}"] = rolling_low / close.replace(0.0, np.nan)
        alpha[f"alpha_q80_{window}"] = reset(close_rolling.quantile(0.8)) / close.replace(
            0.0, np.nan
        )
        alpha[f"alpha_q20_{window}"] = reset(close_rolling.quantile(0.2)) / close.replace(
            0.0, np.nan
        )
        alpha[f"alpha_rsv_{window}"] = (close - rolling_low) / (
            rolling_high - rolling_low
        ).replace(0.0, np.nan)
        alpha[f"alpha_rank_{window}"] = reset(
            close_rolling.apply(
                lambda values: float(np.mean(values <= values[-1])), raw=True
            )
        )
        index_max = reset(
            high_rolling.apply(lambda values: float(np.argmax(values) + 1), raw=True)
        )
        index_min = reset(
            low_rolling.apply(lambda values: float(np.argmin(values) + 1), raw=True)
        )
        alpha[f"alpha_imax_{window}"] = index_max / float(window)
        alpha[f"alpha_imin_{window}"] = index_min / float(window)
        alpha[f"alpha_imxd_{window}"] = (index_max - index_min) / float(window)
        alpha[f"alpha_cntp_{window}"] = _rolling_by_code(
            frame, "_alpha_positive", window, minimum=window
        )
        alpha[f"alpha_cntn_{window}"] = _rolling_by_code(
            frame, "_alpha_negative", window, minimum=window
        )
        alpha[f"alpha_cntd_{window}"] = (
            alpha[f"alpha_cntp_{window}"] - alpha[f"alpha_cntn_{window}"]
        )
        price_total = _rolling_by_code(
            frame,
            "_alpha_price_abs",
            window,
            statistic="sum",
            minimum=window,
        ).replace(0.0, np.nan)
        price_up_sum = _rolling_by_code(
            frame,
            "_alpha_price_up",
            window,
            statistic="sum",
            minimum=window,
        )
        price_down_sum = _rolling_by_code(
            frame,
            "_alpha_price_down",
            window,
            statistic="sum",
            minimum=window,
        )
        alpha[f"alpha_sump_{window}"] = price_up_sum / price_total
        alpha[f"alpha_sumn_{window}"] = price_down_sum / price_total
        alpha[f"alpha_sumd_{window}"] = (price_up_sum - price_down_sum) / price_total
        alpha[f"alpha_vma_{window}"] = reset(volume_rolling.mean()) / volume.replace(
            0.0, np.nan
        )
        alpha[f"alpha_vstd_{window}"] = reset(volume_rolling.std()) / volume.replace(
            0.0, np.nan
        )
        weighted_mean = _rolling_by_code(
            frame, "_alpha_weighted_move", window, minimum=window
        )
        weighted_std = _rolling_by_code(
            frame,
            "_alpha_weighted_move",
            window,
            statistic="std",
            minimum=window,
        )
        alpha[f"alpha_wvma_{window}"] = weighted_std / weighted_mean.replace(
            0.0, np.nan
        )

        mean_close = reset(close_rolling.mean())
        std_close = reset(close_rolling.std())
        mean_time = _rolling_by_code(frame, "_alpha_time", window, minimum=window)
        mean_time_squared = _rolling_by_code(
            frame, "_alpha_time_squared", window, minimum=window
        )
        mean_time_close = _rolling_by_code(
            frame, "_alpha_time_close", window, minimum=window
        )
        time_variance = (mean_time_squared - mean_time.pow(2)).replace(0.0, np.nan)
        time_close_covariance = mean_time_close - mean_time * mean_close
        slope = time_close_covariance / time_variance
        alpha[f"alpha_beta_{window}"] = slope / close.replace(0.0, np.nan)
        close_variance = std_close.pow(2)
        alpha[f"alpha_rsqr_{window}"] = time_close_covariance.pow(2) / (
            time_variance * close_variance
        ).replace(0.0, np.nan)
        fitted_current = mean_close + slope * (frame["_alpha_time"] - mean_time)
        alpha[f"alpha_resi_{window}"] = (close - fitted_current) / close.replace(
            0.0, np.nan
        )

        mean_log_volume = _rolling_by_code(
            frame, "_alpha_log_volume", window, minimum=window
        )
        std_log_volume = _rolling_by_code(
            frame,
            "_alpha_log_volume",
            window,
            statistic="std",
            minimum=window,
        )
        mean_close_log_volume = _rolling_by_code(
            frame, "_alpha_close_log_volume", window, minimum=window
        )
        alpha[f"alpha_corr_{window}"] = (
            mean_close_log_volume - mean_close * mean_log_volume
        ) / (std_close * std_log_volume).replace(0.0, np.nan)
        mean_return = _rolling_by_code(
            frame, "_alpha_return", window, minimum=window
        )
        std_return = _rolling_by_code(
            frame,
            "_alpha_return",
            window,
            statistic="std",
            minimum=window,
        )
        mean_volume_change = _rolling_by_code(
            frame, "_alpha_log_volume_change", window, minimum=window
        )
        std_volume_change = _rolling_by_code(
            frame,
            "_alpha_log_volume_change",
            window,
            statistic="std",
            minimum=window,
        )
        mean_return_volume = _rolling_by_code(
            frame, "_alpha_return_volume", window, minimum=window
        )
        alpha[f"alpha_cord_{window}"] = (
            mean_return_volume - mean_return * mean_volume_change
        ) / (std_return * std_volume_change).replace(0.0, np.nan)
        volume_total = _rolling_by_code(
            frame,
            "_alpha_volume_abs",
            window,
            statistic="sum",
            minimum=window,
        ).replace(0.0, np.nan)
        volume_up_sum = _rolling_by_code(
            frame,
            "_alpha_volume_up",
            window,
            statistic="sum",
            minimum=window,
        )
        volume_down_sum = _rolling_by_code(
            frame,
            "_alpha_volume_down",
            window,
            statistic="sum",
            minimum=window,
        )
        alpha[f"alpha_vsump_{window}"] = volume_up_sum / volume_total
        alpha[f"alpha_vsumn_{window}"] = volume_down_sum / volume_total
        alpha[f"alpha_vsumd_{window}"] = (
            volume_up_sum - volume_down_sum
        ) / volume_total
    frame = pd.concat([frame, pd.DataFrame(alpha, index=frame.index)], axis=1)
    keep = ["date", "code"] + [
        column
        for column in frame.columns
        if column.startswith("tech_") or column.startswith("alpha_")
    ]
    return frame.loc[:, keep]


def _daily_basic_features(path: str | Path) -> pd.DataFrame:
    columns = [
        "ts_code",
        "trade_date",
        "close",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe_ttm",
        "pb",
        "ps_ttm",
        "dv_ttm",
        "total_mv",
        "circ_mv",
    ]
    frame = pd.read_csv(path, dtype={"ts_code": str, "trade_date": str}, usecols=columns)
    frame["code"] = frame["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
    values = columns[2:]
    _numeric(frame, values)
    frame = frame.rename(columns={column: f"basic_{column}" for column in values})
    frame["basic_log_total_mv"] = np.log1p(frame["basic_total_mv"].clip(lower=0.0))
    frame["basic_log_circ_mv"] = np.log1p(frame["basic_circ_mv"].clip(lower=0.0))
    by_date = frame.groupby("date", sort=False)
    for column in (
        "basic_turnover_rate",
        "basic_turnover_rate_f",
        "basic_volume_ratio",
        "basic_pe_ttm",
        "basic_pb",
        "basic_ps_ttm",
        "basic_dv_ttm",
        "basic_total_mv",
        "basic_circ_mv",
    ):
        frame[f"{column}_pct"] = by_date[column].rank(pct=True, method="average")
    keep = ["date", "code"] + [column for column in frame.columns if column.startswith("basic_")]
    return frame.loc[:, keep].drop_duplicates(["date", "code"], keep="last")


def _moneyflow_features(path: str | Path) -> pd.DataFrame:
    amount_columns = [
        "buy_sm_amount",
        "sell_sm_amount",
        "buy_md_amount",
        "sell_md_amount",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
        "net_mf_amount",
    ]
    frame = pd.read_csv(
        path,
        dtype={"ts_code": str, "trade_date": str},
        usecols=["ts_code", "trade_date", *amount_columns],
    )
    frame["code"] = frame["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
    _numeric(frame, amount_columns)
    gross = sum(
        frame[column].clip(lower=0.0)
        for column in amount_columns
        if column != "net_mf_amount"
    ).replace(0.0, np.nan)
    frame["flow_net_ratio"] = frame["net_mf_amount"] / gross
    frame["flow_institutional_ratio"] = (
        frame["buy_lg_amount"]
        - frame["sell_lg_amount"]
        + frame["buy_elg_amount"]
        - frame["sell_elg_amount"]
    ) / gross
    frame["flow_retail_ratio"] = (
        frame["buy_sm_amount"] - frame["sell_sm_amount"]
    ) / gross
    frame["flow_medium_ratio"] = (
        frame["buy_md_amount"] - frame["sell_md_amount"]
    ) / gross
    frame = frame.sort_values(["code", "date"], kind="stable")
    for column in (
        "flow_net_ratio",
        "flow_institutional_ratio",
        "flow_retail_ratio",
        "flow_medium_ratio",
    ):
        for window in (5, 20):
            frame[f"{column}_mean_{window}"] = _rolling_by_code(
                frame,
                column,
                window,
                minimum=max(3, window // 2),
            )
        frame[f"{column}_pct"] = frame.groupby("date", sort=False)[column].rank(
            pct=True, method="average"
        )
    keep = ["date", "code"] + [column for column in frame.columns if column.startswith("flow_")]
    return frame.loc[:, keep].drop_duplicates(["date", "code"], keep="last")


def _margin_features(path: str | Path) -> pd.DataFrame:
    value_columns = [
        "rzye",
        "rqye",
        "rzmre",
        "rqyl",
        "rzche",
        "rqchl",
        "rqmcl",
        "rzrqye",
    ]
    frame = pd.read_csv(
        path,
        dtype={"ts_code": str, "trade_date": str},
        usecols=["ts_code", "trade_date", *value_columns],
    )
    frame["code"] = frame["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
    _numeric(frame, value_columns)
    frame = frame.sort_values(["code", "date"], kind="stable")
    frame["margin_financing_net_buy_ratio"] = (
        frame["rzmre"] - frame["rzche"]
    ) / frame["rzye"].replace(0.0, np.nan)
    frame["margin_short_to_financing"] = frame["rqye"] / frame["rzye"].replace(
        0.0,
        np.nan,
    )
    frame["margin_total_log"] = np.log1p(frame["rzrqye"].clip(lower=0.0))
    grouped = frame.groupby("code", sort=False)
    frame["margin_financing_balance_change"] = grouped["rzye"].pct_change(
        fill_method=None
    )
    frame["margin_short_balance_change"] = grouped["rqye"].pct_change(fill_method=None)
    for column in (
        "margin_financing_net_buy_ratio",
        "margin_short_to_financing",
        "margin_financing_balance_change",
        "margin_short_balance_change",
    ):
        for window in (5, 20):
            frame[f"{column}_mean_{window}"] = _rolling_by_code(
                frame,
                column,
                window,
                minimum=max(3, window // 2),
            )
        frame[f"{column}_pct"] = frame.groupby("date", sort=False)[column].rank(
            pct=True,
            method="average",
        )
    keep = ["date", "code"] + [
        column for column in frame.columns if column.startswith("margin_")
    ]
    return frame.loc[:, keep].drop_duplicates(["date", "code"], keep="last")


def _index_market_features(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"ts_code": str, "trade_date": str})
    frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
    frame["index_code"] = frame["ts_code"].astype(str).str.split(".").str[0]
    _numeric(frame, ["pct_chg", "vol", "amount"])
    wide = frame.pivot(index="date", columns="index_code", values=["pct_chg", "vol", "amount"])
    wide.columns = [
        f"market_index_{index_code}_{metric}" for metric, index_code in wide.columns
    ]
    wide = wide.reset_index().sort_values("date")
    additions: dict[str, pd.Series] = {}
    for column in [value for value in wide.columns if value.endswith("_pct_chg")]:
        for window in (5, 10, 20, 30, 60):
            additions[f"{column}_mean_{window}"] = wide[column].rolling(
                window,
                min_periods=max(3, window // 2),
            ).mean()
        additions[f"{column}_volatility_20"] = wide[column].rolling(
            20,
            min_periods=10,
        ).std()
    for column in [
        value
        for value in wide.columns
        if value.endswith(("_amount", "_vol"))
    ]:
        for window in (5, 10, 20, 30, 60):
            rolling_mean = wide[column].rolling(
                window, min_periods=max(3, window // 2)
            ).mean()
            rolling_std = wide[column].rolling(
                window, min_periods=max(3, window // 2)
            ).std()
            additions[f"{column}_mean_ratio_{window}"] = (
                wide[column] / rolling_mean.replace(0.0, np.nan)
            )
            additions[f"{column}_std_ratio_{window}"] = (
                rolling_std / rolling_mean.replace(0.0, np.nan)
            )
    return pd.concat([wide, pd.DataFrame(additions, index=wide.index)], axis=1)


def _hsgt_market_features(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"trade_date": str})
    frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
    columns = ["hgt", "sgt", "north_money", "south_money"]
    _numeric(frame, columns)
    frame = frame.sort_values("date")
    additions: dict[str, pd.Series] = {}
    for column in columns:
        frame[f"market_hsgt_{column}"] = frame[column]
        for window in (5, 20, 60):
            additions[f"market_hsgt_{column}_mean_{window}"] = frame[column].rolling(
                window,
                min_periods=max(3, window // 2),
            ).mean()
    keep = ["date"] + [column for column in frame.columns if column.startswith("market_hsgt_")]
    return pd.concat(
        [frame.loc[:, keep], pd.DataFrame(additions, index=frame.index)],
        axis=1,
    )


def _read_event_file(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 1:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _event_keys(frame: pd.DataFrame, date_column: str) -> pd.DataFrame:
    result = frame.copy()
    result["code"] = result["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    result["event_date"] = pd.to_datetime(
        result[date_column].astype(str), format="%Y%m%d", errors="coerce"
    )
    return result.dropna(subset=["code", "event_date"])


def _merge_asof_events(
    base: pd.DataFrame,
    events: pd.DataFrame,
    *,
    feature_columns: list[str],
    prefix: str,
) -> pd.DataFrame:
    if events.empty:
        return base
    right = events.loc[:, ["code", "event_date", *feature_columns]].copy()
    right["code"] = right["code"].astype("string")
    right = right.sort_values(["event_date", "code"], kind="stable").drop_duplicates(
        ["code", "event_date"], keep="last"
    )
    left_keys = base.loc[:, ["date", "code"]].copy()
    left_keys["code"] = left_keys["code"].astype("string")
    left_keys["_event_row"] = np.arange(len(left_keys), dtype=np.int64)
    left_keys = left_keys.sort_values(["date", "code"], kind="stable")
    matched = pd.merge_asof(
        left_keys,
        right,
        by="code",
        left_on="date",
        right_on="event_date",
        direction="backward",
        allow_exact_matches=True,
    )
    matched = matched.sort_values("_event_row", kind="stable")
    additions = matched.loc[:, feature_columns].reset_index(drop=True)
    additions[f"{prefix}_days_since"] = (
        matched["date"].reset_index(drop=True)
        - matched["event_date"].reset_index(drop=True)
    ).dt.days.astype("float32")
    additions.index = base.index
    overlapping = [column for column in additions.columns if column in base.columns]
    if overlapping:
        base = base.drop(columns=overlapping)
    return pd.concat([base, additions], axis=1)


def _daily_event_features(event_dir: Path) -> list[pd.DataFrame]:
    results: list[pd.DataFrame] = []
    top_list = _read_event_file(event_dir / "top_list.csv")
    if not top_list.empty:
        top_list = _event_keys(top_list, "trade_date")
        numeric = [
            "turnover_rate",
            "amount",
            "l_sell",
            "l_buy",
            "l_amount",
            "net_amount",
            "net_rate",
            "amount_rate",
            "float_values",
        ]
        _numeric(top_list, numeric)
        grouped = top_list.groupby(["event_date", "code"], sort=False)
        daily = grouped.agg(
            event_top_list_count=("ts_code", "size"),
            event_top_list_net_amount=("net_amount", "sum"),
            event_top_list_net_rate=("net_rate", "mean"),
            event_top_list_amount_rate=("amount_rate", "mean"),
            event_top_list_turnover=("turnover_rate", "mean"),
            event_top_list_buy=("l_buy", "sum"),
            event_top_list_sell=("l_sell", "sum"),
        ).reset_index().rename(columns={"event_date": "date"})
        results.append(daily)

    block = _read_event_file(event_dir / "block_trade.csv")
    if not block.empty:
        block = _event_keys(block, "trade_date")
        _numeric(block, ["price", "vol", "amount"])
        grouped = block.groupby(["event_date", "code"], sort=False)
        daily = grouped.agg(
            event_block_count=("ts_code", "size"),
            event_block_amount=("amount", "sum"),
            event_block_volume=("vol", "sum"),
            event_block_price=("price", "mean"),
        ).reset_index().rename(columns={"event_date": "date"})
        results.append(daily)

    top_inst = _read_event_file(event_dir / "top_inst.csv")
    if not top_inst.empty:
        top_inst = _event_keys(top_inst, "trade_date")
        _numeric(top_inst, ["buy", "buy_rate", "sell", "sell_rate", "net_buy"])
        grouped = top_inst.groupby(["event_date", "code"], sort=False)
        daily = grouped.agg(
            event_top_inst_count=("ts_code", "size"),
            event_top_inst_buy=("buy", "sum"),
            event_top_inst_sell=("sell", "sum"),
            event_top_inst_net_buy=("net_buy", "sum"),
            event_top_inst_buy_rate=("buy_rate", "mean"),
            event_top_inst_sell_rate=("sell_rate", "mean"),
        ).reset_index().rename(columns={"event_date": "date"})
        results.append(daily)

    repurchase = _read_event_file(event_dir / "repurchase.csv")
    if not repurchase.empty:
        repurchase = _event_keys(repurchase, "ann_date")
        _numeric(repurchase, ["vol", "amount", "high_limit", "low_limit"])
        grouped = repurchase.groupby(["event_date", "code"], sort=False)
        daily = grouped.agg(
            event_repurchase_count=("ts_code", "size"),
            event_repurchase_volume=("vol", "sum"),
            event_repurchase_amount=("amount", "sum"),
            event_repurchase_high_limit=("high_limit", "mean"),
            event_repurchase_low_limit=("low_limit", "mean"),
        ).reset_index().rename(columns={"event_date": "date"})
        results.append(daily)
    return results


def _merge_event_features(base: pd.DataFrame, event_dir: Path) -> pd.DataFrame:
    frame = base
    for daily in _daily_event_features(event_dir):
        frame = frame.merge(daily, on=["date", "code"], how="left")
        event_columns = [
            column for column in daily.columns if column not in {"date", "code"}
        ]
        for column in event_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        count_column = next(
            (column for column in event_columns if column.endswith("_count")), None
        )
        if count_column:
            frame = frame.sort_values(["code", "date"], kind="stable")
            for window in (5, 20, 60):
                frame[f"{count_column}_{window}d"] = _rolling_by_code(
                    frame, count_column, window, statistic="sum", minimum=1
                )

    broker = _read_event_file(event_dir / "broker_recommend.csv")
    if not broker.empty and {"ts_code", "month"}.issubset(broker.columns):
        broker["code"] = broker["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
        month = pd.to_datetime(
            broker["month"].astype(str) + "01", format="%Y%m%d", errors="coerce"
        )
        # The monthly list is conservatively exposed only after that month ends.
        broker["event_date"] = month + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1)
        broker = broker.dropna(subset=["event_date", "code"])
        aggregated = (
            broker.groupby(["code", "event_date"], sort=False)
            .agg(event_broker_recommend_count=("ts_code", "size"))
            .reset_index()
        )
        frame = _merge_asof_events(
            frame,
            aggregated,
            feature_columns=["event_broker_recommend_count"],
            prefix="event_broker_recommend",
        )

    specifications = [
        (
            "fina_indicator.csv",
            "ann_date",
            "event_fina",
            [
                "eps", "dt_eps", "profit_dedt", "gross_margin", "current_ratio",
                "quick_ratio", "inv_turn", "ar_turn", "assets_turn", "ocfps",
                "netprofit_margin", "grossprofit_margin", "roe", "roa", "roic",
                "debt_to_assets", "ocf_to_debt", "q_eps", "q_netprofit_margin",
                "q_roe", "basic_eps_yoy", "dt_eps_yoy", "op_yoy", "netprofit_yoy",
                "dt_netprofit_yoy", "ocf_yoy", "assets_yoy", "eqt_yoy", "tr_yoy",
                "q_sales_yoy", "q_op_yoy", "q_netprofit_yoy", "rd_exp",
            ],
        ),
        (
            "forecast.csv",
            "ann_date",
            "event_forecast",
            ["p_change_min", "p_change_max", "net_profit_min", "net_profit_max", "last_parent_net"],
        ),
        (
            "express.csv",
            "ann_date",
            "event_express",
            [
                "revenue", "operate_profit", "total_profit", "n_income", "total_assets",
                "total_hldr_eqy_exc_min_int", "diluted_eps", "diluted_roe",
                "yoy_net_profit", "bps", "yoy_sales", "yoy_op", "yoy_tp", "yoy_dedu_np",
            ],
        ),
        (
            "stk_holdernumber.csv",
            "ann_date",
            "event_holder",
            ["holder_num"],
        ),
        (
            "dividend.csv",
            "ann_date",
            "event_dividend",
            ["stk_div", "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax"],
        ),
        (
            "share_float.csv",
            "ann_date",
            "event_share_float",
            ["float_share", "float_ratio"],
        ),
    ]
    for filename, date_column, prefix, wanted in specifications:
        events = _read_event_file(event_dir / filename)
        if events.empty or date_column not in events.columns or "ts_code" not in events.columns:
            continue
        events = _event_keys(events, date_column)
        available = [column for column in wanted if column in events.columns]
        if not available:
            continue
        _numeric(events, available)
        renamed = {column: f"{prefix}_{column}" for column in available}
        events = events.rename(columns=renamed)
        event_features = list(renamed.values())
        if prefix == "event_holder" and "event_holder_holder_num" in events.columns:
            events = events.sort_values(["code", "event_date"], kind="stable")
            events["event_holder_change"] = events.groupby("code", sort=False)[
                "event_holder_holder_num"
            ].pct_change(fill_method=None)
            event_features.append("event_holder_change")
        frame = _merge_asof_events(
            frame,
            events,
            feature_columns=event_features,
            prefix=prefix,
        )
    if "event_block_price" in frame.columns and "basic_close" in frame.columns:
        frame["event_block_price_premium"] = (
            frame["event_block_price"] / frame["basic_close"].replace(0.0, np.nan) - 1.0
        )
    return frame


def _stock_industries(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        dtype={"ts_code": str, "list_date": str},
        usecols=["ts_code", "industry", "market", "list_date"],
    )
    frame["code"] = frame["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    frame["industry"] = frame["industry"].fillna("unknown").astype(str)
    frame["listing_market"] = frame["market"].fillna("unknown").astype(str)
    frame["list_date"] = pd.to_datetime(
        frame["list_date"], format="%Y%m%d", errors="coerce"
    )
    return frame.loc[:, ["code", "industry", "listing_market", "list_date"]].drop_duplicates(
        "code",
        keep="first",
    )


def build_stock_direction_dataset(
    *,
    prediction_history_path: str | Path,
    market_history_path: str | Path,
    tushare_feature_dir: str | Path,
) -> tuple[pd.DataFrame, list[str]]:
    feature_dir = Path(tushare_feature_dir)
    frame = _prediction_features(prediction_history_path)
    frame = frame.merge(_technical_features(market_history_path), on=["date", "code"], how="left")
    frame = frame.merge(
        _daily_basic_features(feature_dir / "daily_basic.csv"),
        on=["date", "code"],
        how="left",
    )
    frame = frame.merge(
        _moneyflow_features(feature_dir / "moneyflow.csv"),
        on=["date", "code"],
        how="left",
    )
    margin_path = feature_dir / "margin_detail.csv"
    if margin_path.exists():
        frame = frame.merge(
            _margin_features(margin_path),
            on=["date", "code"],
            how="left",
        )
    frame = frame.merge(
        _index_market_features(feature_dir / "index_daily.csv"),
        on="date",
        how="left",
    )
    frame = frame.merge(
        _hsgt_market_features(feature_dir / "moneyflow_hsgt.csv"),
        on="date",
        how="left",
    )
    stock_basic_path = feature_dir / "stock_basic.csv"
    if stock_basic_path.exists():
        frame = frame.merge(_stock_industries(stock_basic_path), on="code", how="left")
        frame["listing_age_days"] = (
            frame["date"] - frame["list_date"]
        ).dt.days.clip(lower=0).astype("float32")
        frame["listing_age_log"] = np.log1p(frame["listing_age_days"])
        frame["industry"] = frame["industry"].fillna("unknown")
        industry_current = frame.groupby(["date", "industry"], sort=False)
        frame["industry_current_return_mean"] = industry_current["tech_ret_1"].transform(
            "mean"
        )
        frame["industry_current_breadth"] = industry_current["tech_ret_1"].transform(
            lambda values: values.gt(0.0).mean()
        )
        frame["industry_current_net_flow_mean"] = industry_current[
            "flow_net_ratio"
        ].transform("mean")
        frame["relative_return_to_industry"] = (
            frame["tech_ret_1"] - frame["industry_current_return_mean"]
        )
        industry_daily = (
            frame.groupby(["date", "industry"], sort=True)["label_up"]
            .mean()
            .rename("industry_up_rate")
            .reset_index()
            .sort_values(["industry", "date"])
        )
        for window in (20, 60, 120):
            industry_daily[f"industry_prior_up_rate_{window}"] = (
                industry_daily.groupby("industry", sort=False)["industry_up_rate"]
                .shift(1)
                .groupby(industry_daily["industry"], sort=False)
                .rolling(window, min_periods=max(5, window // 3))
                .mean()
                .reset_index(level=0, drop=True)
            )
        frame = frame.merge(
            industry_daily.drop(columns="industry_up_rate"),
            on=["date", "industry"],
            how="left",
        )
    event_dir = feature_dir.parent / "tushare_events"
    if event_dir.exists():
        frame = _merge_event_features(frame, event_dir)
    by_date = frame.groupby("date", sort=False)
    frame["market_current_return_mean"] = by_date["tech_ret_1"].transform("mean")
    frame["market_current_return_std"] = by_date["tech_ret_1"].transform("std")
    frame["market_current_breadth"] = by_date["tech_ret_1"].transform(
        lambda values: values.gt(0.0).mean()
    )
    frame["market_current_net_flow_mean"] = by_date["flow_net_ratio"].transform("mean")
    frame["market_current_institutional_flow_mean"] = by_date[
        "flow_institutional_ratio"
    ].transform("mean")
    frame["market_current_turnover_mean"] = by_date["basic_turnover_rate"].transform(
        "mean"
    )
    frame["relative_return_1"] = (
        frame["tech_ret_1"] - frame["market_current_return_mean"]
    )
    frame["relative_net_flow"] = (
        frame["flow_net_ratio"] - frame["market_current_net_flow_mean"]
    )
    percentile_columns = [
        "prior_realized_return",
        "stock_return_mean_5",
        "stock_return_mean_20",
        "stock_return_mean_60",
        "stock_up_rate_20",
        "stock_up_rate_60",
        "stock_up_rate_120",
        "stock_up_rate_250",
        "stock_positive_precision_20",
        "stock_positive_precision_60",
        "stock_positive_precision_120",
        "tech_ret_1",
        "tech_ret_2",
        "tech_ret_5",
        "tech_ret_10",
        "tech_ret_20",
        "tech_ret_60",
        "tech_volatility_20",
        "tech_close_to_ma_20",
        "tech_volume_ratio_20",
        "tech_intraday_return",
        "tech_overnight_gap",
        "tech_close_position",
        "flow_net_ratio",
        "flow_institutional_ratio",
        "flow_retail_ratio",
        "margin_financing_net_buy_ratio",
        "margin_short_to_financing",
        "margin_financing_balance_change",
        "margin_short_balance_change",
        "event_top_list_net_rate",
        "event_top_list_amount_rate",
        "event_block_amount",
        "event_block_price_premium",
        "event_fina_roe",
        "event_fina_q_roe",
        "event_fina_netprofit_yoy",
        "event_fina_q_netprofit_yoy",
        "event_holder_change",
        "event_share_float_float_ratio",
    ]
    for column in percentile_columns:
        if column in frame.columns:
            frame[f"cross_pct_{column}"] = by_date[column].rank(
                pct=True,
                method="average",
            )
    broad_rank_prefixes = (
        "alpha_",
        "basic_",
        "event_",
        "flow_",
        "industry_current_",
        "margin_",
        "prior_",
        "relative_",
        "stock_",
        "tech_",
    )
    broad_rank_columns = [
        column
        for column in frame.columns
        if column.startswith(broad_rank_prefixes)
        and not column.startswith("cross_pct_")
        and pd.api.types.is_numeric_dtype(frame[column])
        and f"cross_all_pct_{column}" not in frame.columns
    ]
    if broad_rank_columns:
        broad_ranks = by_date[broad_rank_columns].rank(
            pct=True,
            method="average",
        )
        broad_ranks.columns = [
            f"cross_all_pct_{column}" for column in broad_rank_columns
        ]
        frame = pd.concat([frame, broad_ranks.astype("float32")], axis=1)
    if "industry" in frame.columns:
        industry_rank_columns = [
            column
            for column in broad_rank_columns
            if column.startswith(("alpha_", "flow_", "tech_"))
        ]
        if industry_rank_columns:
            industry_ranks = frame.groupby(
                ["date", "industry"], sort=False
            )[industry_rank_columns].rank(pct=True, method="average")
            industry_ranks.columns = [
                f"industry_pct_{column}" for column in industry_rank_columns
            ]
            frame = pd.concat([frame, industry_ranks.astype("float32")], axis=1)
    feature_columns = [
        column
        for column in frame.columns
        if column not in NON_FEATURE_COLUMNS
        and pd.api.types.is_numeric_dtype(frame[column])
    ]
    for column in feature_columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        values = values.mask(np.isinf(values), np.nan)
        frame[column] = values.astype("float32")
    return frame.sort_values(["date", "code"], kind="stable").reset_index(drop=True), feature_columns


__all__ = ["NON_FEATURE_COLUMNS", "build_stock_direction_dataset"]
