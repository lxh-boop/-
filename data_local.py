import os
from datetime import datetime

import pandas as pd

from config import (
    LOCAL_TRAIN_CSV_PATH,
    QLIB_PROVIDER_URI,
    RAW_DATA_PATH,
    START_DATE,
)
from universe import get_stock_pool


def format_code(code) -> str:
    return str(code).zfill(6)


def to_qlib_instrument(code: str) -> str:
    code = format_code(code)

    if code.startswith(("0", "2", "3")):
        return f"SZ{code}"

    if code.startswith(("5", "6", "9")):
        return f"SH{code}"

    if code.startswith(("4", "8")):
        return f"BJ{code}"

    raise ValueError(f"无法识别交易所的股票代码：{code}")


def from_qlib_instrument(instrument: str) -> str:
    instrument = str(instrument)

    if instrument.startswith(("SZ", "SH", "BJ")):
        return instrument[2:]

    return instrument


def load_local_qlib_data() -> pd.DataFrame:
    """
    使用本地 Qlib 数据读取训练行情。
    这个函数不需要 Tushare Token，也不依赖 APP。
    """

    try:
        import qlib
        from qlib.data import D
    except ImportError as exc:
        raise ImportError("当前环境没有安装 pyqlib，请先运行：pip install pyqlib") from exc

    print(f"[Qlib] init provider_uri = {QLIB_PROVIDER_URI}")

    qlib.init(
        provider_uri=QLIB_PROVIDER_URI,
        region="cn",
    )

    instruments = []
    name_map = {}

    stock_pool = get_stock_pool(token=None, enrich_name=False)

    for code, name in stock_pool.items():
        code = format_code(code)
        inst = to_qlib_instrument(code)
        instruments.append(inst)
        name_map[inst] = name

    fields = [
        "$open",
        "$high",
        "$low",
        "$close",
        "$volume",
        "$amount",
    ]

    start_time = pd.to_datetime(START_DATE).strftime("%Y-%m-%d")
    end_time = datetime.today().strftime("%Y-%m-%d")

    print(f"[Qlib] fetch from {start_time} to {end_time}")
    print(f"[Qlib] instruments = {instruments}")

    df = D.features(
        instruments=instruments,
        fields=fields,
        start_time=start_time,
        end_time=end_time,
        freq="day",
    )

    if df is None or df.empty:
        raise RuntimeError(
            "Qlib 没有读取到任何数据。\n"
            f"请检查 QLIB_PROVIDER_URI 是否正确：{QLIB_PROVIDER_URI}"
        )

    df = df.reset_index()

    rename_map = {
        "instrument": "instrument",
        "datetime": "date",
        "$open": "open",
        "$high": "high",
        "$low": "low",
        "$close": "close",
        "$volume": "volume",
        "$amount": "amount",
    }

    df = df.rename(columns=rename_map)

    if "date" not in df.columns and "datetime" in df.columns:
        df = df.rename(columns={"datetime": "date"})

    needed_cols = [
        "instrument",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]

    df = df[[c for c in needed_cols if c in df.columns]].copy()

    df["date"] = pd.to_datetime(df["date"])
    df["code"] = df["instrument"].map(from_qlib_instrument)
    df["name"] = df["instrument"].map(lambda x: name_map.get(x, x))

    numeric_cols = ["open", "high", "low", "close", "volume", "amount"]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Qlib amount / volume 单位可能不同，第一版直接用 close 近似 vwap
    df["vwap"] = df["close"]

    # 当前 Alpha158 不依赖 turnover
    df["turnover"] = 0.0

    df = df[
        [
            "date",
            "code",
            "name",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "vwap",
            "turnover",
        ]
    ].copy()

    df = df.dropna(subset=["open", "close", "high", "low"])
    df = df.sort_values(["code", "date"]).reset_index(drop=True)

    df.to_csv(RAW_DATA_PATH, index=False, encoding="utf-8-sig")

    print(f"[Save] local train raw data -> {RAW_DATA_PATH}, shape={df.shape}")
    print(f"[Info] stock count = {df['code'].nunique()}")
    print(f"[Info] latest date = {df['date'].max().date()}")

    return df


def load_local_csv_data(csv_path: str = LOCAL_TRAIN_CSV_PATH) -> pd.DataFrame:
    """
    如果你后续不用 Qlib，也可以直接读取本地 CSV。
    CSV 至少要包含：
    date, code, name, open, close, high, low, volume, amount
    """

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"本地 CSV 不存在：{csv_path}")

    df = pd.read_csv(csv_path, dtype={"code": str})

    df["code"] = df["code"].astype(str).str.zfill(6)
    df["date"] = pd.to_datetime(df["date"])

    required_cols = [
        "date",
        "code",
        "name",
        "open",
        "close",
        "high",
        "low",
        "volume",
        "amount",
    ]

    missing = [c for c in required_cols if c not in df.columns]

    if missing:
        raise ValueError(f"本地 CSV 缺少字段：{missing}")

    if "vwap" not in df.columns:
        df["vwap"] = df["close"]

    if "turnover" not in df.columns:
        df["turnover"] = 0.0

    df = df.sort_values(["code", "date"]).reset_index(drop=True)

    return df


def load_local_train_data(source: str = "qlib") -> pd.DataFrame:
    """
    初始训练统一入口。
    不需要 Tushare Token。
    """

    source = source.lower().strip()

    if source == "qlib":
        return load_local_qlib_data()

    if source == "csv":
        return load_local_csv_data()

    raise ValueError(f"不支持的本地训练数据源：{source}")
