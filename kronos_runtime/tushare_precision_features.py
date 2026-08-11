from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from config import KRONOS_STOCK_DIRECTION_FEATURE_DIR
from data_tushare import init_tushare_pro, to_ts_code


INDEX_CODES = ("000001.SH", "399001.SZ", "399006.SZ", "000300.SH", "000905.SH")
DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
    "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,"
    "free_share,total_mv,circ_mv"
)
MONEYFLOW_FIELDS = (
    "ts_code,trade_date,buy_sm_vol,buy_sm_amount,sell_sm_vol,sell_sm_amount,"
    "buy_md_vol,buy_md_amount,sell_md_vol,sell_md_amount,buy_lg_vol,"
    "buy_lg_amount,sell_lg_vol,sell_lg_amount,buy_elg_vol,buy_elg_amount,"
    "sell_elg_vol,sell_elg_amount,net_mf_vol,net_mf_amount"
)
INDEX_FIELDS = "ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount"


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    os.replace(temporary, path)


def _read(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"ts_code": str, "trade_date": str})


def _has_date(path: Path, trade_date: str) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        dates = pd.read_csv(path, usecols=["trade_date"], dtype=str)["trade_date"]
    except Exception:
        return False
    return bool(dates.astype(str).str[:8].eq(trade_date).any())


def _upsert(path: Path, current: pd.DataFrame, keys: list[str]) -> int:
    existing = _read(path)
    combined = pd.concat([existing, current], ignore_index=True, sort=False)
    if combined.empty:
        _atomic_csv(combined, path)
        return 0
    combined["trade_date"] = combined["trade_date"].astype(str).str[:8]
    combined = combined.sort_values(["trade_date", *[key for key in keys if key != "trade_date"]])
    combined = combined.drop_duplicates(keys, keep="last")
    _atomic_csv(combined, path)
    return int(len(current))


def _model_universe(feature_dir: Path, current_codes: set[str]) -> set[str]:
    path = feature_dir / "daily_basic.csv"
    if not path.exists():
        return {to_ts_code(code) for code in current_codes}
    try:
        values = pd.read_csv(path, usecols=["ts_code"], dtype=str)["ts_code"]
        historical = set(values.dropna().astype(str))
    except Exception:
        historical = set()
    return historical | {to_ts_code(code) for code in current_codes}


def refresh_precision_features_for_date(
    *,
    token: str,
    signal_date: str,
    stock_codes: set[str] | list[str],
    feature_dir: str | Path = KRONOS_STOCK_DIRECTION_FEATURE_DIR,
) -> dict[str, Any]:
    trade_date = str(signal_date).replace("-", "")[:8]
    if len(trade_date) != 8:
        raise ValueError("signal_date必须是YYYY-MM-DD或YYYYMMDD")
    directory = Path(feature_dir)
    directory.mkdir(parents=True, exist_ok=True)
    pro = init_tushare_pro(token)
    universe = _model_universe(directory, {str(code).zfill(6) for code in stock_codes})
    report: dict[str, Any] = {
        "ready": True,
        "trade_date": trade_date,
        "universe_size": len(universe),
        "endpoints": {},
    }

    daily_basic_path = directory / "daily_basic.csv"
    if _has_date(daily_basic_path, trade_date):
        report["endpoints"]["daily_basic"] = {"cached": True}
    else:
        daily_basic = pro.daily_basic(trade_date=trade_date, fields=DAILY_BASIC_FIELDS)
        daily_basic = pd.DataFrame() if daily_basic is None else daily_basic
        if not daily_basic.empty:
            daily_basic = daily_basic[daily_basic["ts_code"].astype(str).isin(universe)]
        written = _upsert(daily_basic_path, daily_basic, ["ts_code", "trade_date"])
        report["endpoints"]["daily_basic"] = {"cached": False, "rows": written}

    moneyflow_path = directory / "moneyflow.csv"
    if _has_date(moneyflow_path, trade_date):
        report["endpoints"]["moneyflow"] = {"cached": True}
    else:
        moneyflow = pro.moneyflow(trade_date=trade_date, fields=MONEYFLOW_FIELDS)
        moneyflow = pd.DataFrame() if moneyflow is None else moneyflow
        if not moneyflow.empty:
            moneyflow = moneyflow[moneyflow["ts_code"].astype(str).isin(universe)]
        written = _upsert(moneyflow_path, moneyflow, ["ts_code", "trade_date"])
        report["endpoints"]["moneyflow"] = {"cached": False, "rows": written}

    index_path = directory / "index_daily.csv"
    if _has_date(index_path, trade_date):
        report["endpoints"]["index_daily"] = {"cached": True}
    else:
        frames = [
            pro.index_daily(ts_code=code, trade_date=trade_date, fields=INDEX_FIELDS)
            for code in INDEX_CODES
        ]
        index_daily = pd.concat(
            [frame for frame in frames if frame is not None and not frame.empty],
            ignore_index=True,
            sort=False,
        ) if any(frame is not None and not frame.empty for frame in frames) else pd.DataFrame()
        written = _upsert(index_path, index_daily, ["ts_code", "trade_date"])
        report["endpoints"]["index_daily"] = {"cached": False, "rows": written}

    hsgt_path = directory / "moneyflow_hsgt.csv"
    if _has_date(hsgt_path, trade_date):
        report["endpoints"]["moneyflow_hsgt"] = {"cached": True}
    else:
        hsgt = pro.moneyflow_hsgt(trade_date=trade_date)
        hsgt = pd.DataFrame() if hsgt is None else hsgt
        written = _upsert(hsgt_path, hsgt, ["trade_date"])
        report["endpoints"]["moneyflow_hsgt"] = {"cached": False, "rows": written}

    for endpoint in report["endpoints"].values():
        if not endpoint.get("cached") and int(endpoint.get("rows") or 0) <= 0:
            report["ready"] = False
    return report


__all__ = ["refresh_precision_features_for_date"]
