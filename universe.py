#universe
import os
from datetime import datetime, timedelta

import pandas as pd

from config import (
    CSI300_POOL_CACHE_PATH,
    QLIB_PROVIDER_URI,
    STOCK_POOL,
    UNIVERSE,
    USE_TUSHARE_INDEX_WEIGHT_FALLBACK,
)


def format_code(code) -> str:
    return str(code).zfill(6)


def qlib_inst_to_code(inst: str) -> str:
    inst = str(inst).strip()

    if inst.startswith(("SH", "SZ", "BJ", "sh", "sz", "bj")):
        return inst[2:].zfill(6)

    return inst.zfill(6)


def code_to_ts_code(code: str) -> str:
    code = format_code(code)

    if code.startswith(("0", "2", "3")):
        return f"{code}.SZ"

    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"

    if code.startswith(("4", "8")):
        return f"{code}.BJ"

    raise ValueError(f"无法识别交易所：{code}")


def ts_code_to_code(ts_code: str) -> str:
    return str(ts_code).split(".")[0].zfill(6)


def read_csi300_from_qlib_instruments() -> dict:
    """
    从 Qlib instruments/csi300.txt 读取 CSI300 股票池。

    常见文件：
    D:/qlib_data/cn_data/instruments/csi300.txt
    """
    candidates = [
        os.path.join(QLIB_PROVIDER_URI, "instruments", "csi300.txt"),
        os.path.join(QLIB_PROVIDER_URI, "instruments", "CSI300.txt"),
    ]

    inst_path = None

    for path in candidates:
        if os.path.exists(path):
            inst_path = path
            break

    if inst_path is None:
        raise FileNotFoundError(
            "没有找到 Qlib CSI300 股票池文件。已尝试：\n"
            + "\n".join(candidates)
        )

    raw_rows = []

    with open(inst_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            parts = line.split()
            inst = parts[0]
            code = qlib_inst_to_code(inst)

            raw_rows.append(
                {
                    "inst": inst,
                    "code": code,
                    "ts_code": code_to_ts_code(code),
                    "name": code,
                    "start": parts[1] if len(parts) >= 2 else None,
                    "end": parts[2] if len(parts) >= 3 else None,
                }
            )

    df_all = pd.DataFrame(raw_rows)

    if df_all.empty:
        raise RuntimeError(f"Qlib CSI300 股票池文件为空：{inst_path}")

    if df_all["start"].notna().any() and df_all["end"].notna().any():
        today = datetime.today().strftime("%Y-%m-%d")

        active = df_all[
            (df_all["start"].fillna("") <= today)
            & (df_all["end"].fillna("9999-12-31") >= today)
        ].copy()

        if active.empty:
            effective_date = str(df_all["end"].dropna().max())
            active = df_all[
                (df_all["start"].fillna("") <= effective_date)
                & (df_all["end"].fillna("9999-12-31") >= effective_date)
            ].copy()
        else:
            effective_date = today
    else:
        active = df_all.copy()
        effective_date = "all"

    df = active.drop_duplicates(subset=["code"]).copy()
    df["source"] = f"qlib_csi300_{effective_date}"
    df = df[["code", "ts_code", "name", "source"]]
    df = df.sort_values("code").reset_index(drop=True)

    os.makedirs(os.path.dirname(CSI300_POOL_CACHE_PATH), exist_ok=True)
    df.to_csv(CSI300_POOL_CACHE_PATH, index=False, encoding="utf-8-sig")

    print(f"[Universe] CSI300 from Qlib: {len(df)} stocks, effective_date={effective_date}")
    print(f"[Universe] saved -> {CSI300_POOL_CACHE_PATH}")

    return dict(zip(df["code"], df["name"]))


def enrich_names_with_tushare(token: str, stock_pool: dict) -> dict:
    """
    用 Tushare stock_basic 补充股票名称。
    如果失败，不影响主流程，仍使用代码作为名称。
    """
    try:
        import tushare as ts

        ts.set_token(token)
        pro = ts.pro_api(token)

        basic = pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name"
        )

        if basic is None or basic.empty:
            return stock_pool

        basic["symbol"] = basic["symbol"].astype(str).str.zfill(6)
        name_map = dict(zip(basic["symbol"], basic["name"]))

        out = {}

        for code, old_name in stock_pool.items():
            code = format_code(code)
            out[code] = name_map.get(code, old_name)

        df = pd.DataFrame(
            [
                {
                    "code": code,
                    "ts_code": code_to_ts_code(code),
                    "name": name,
                    "source": "qlib_csi300_tushare_name",
                }
                for code, name in out.items()
            ]
        )

        os.makedirs(os.path.dirname(CSI300_POOL_CACHE_PATH), exist_ok=True)
        df.to_csv(CSI300_POOL_CACHE_PATH, index=False, encoding="utf-8-sig")

        print(f"[Universe] enriched names with Tushare: {len(out)} stocks")
        return out

    except Exception as e:
        print(f"[Universe] enrich names failed, use code as name: {e}")
        return stock_pool


def read_csi300_from_tushare_index_weight(token: str) -> dict:
    """
    备选方案：从 Tushare index_weight 获取最近一期 CSI300 成分股。
    注意：该接口可能需要相应积分权限。
    """
    import tushare as ts

    ts.set_token(token)
    pro = ts.pro_api(token)

    today = datetime.today()
    start_date = (today - timedelta(days=120)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")

    df = pro.index_weight(
        index_code="000300.SH",
        start_date=start_date,
        end_date=end_date,
        fields="index_code,con_code,trade_date,weight"
    )

    if df is None or df.empty:
        raise RuntimeError("Tushare index_weight 没有返回 CSI300 成分股。")

    latest_date = df["trade_date"].max()
    latest = df[df["trade_date"] == latest_date].copy()

    latest["code"] = latest["con_code"].map(ts_code_to_code)
    latest["ts_code"] = latest["con_code"]
    latest["name"] = latest["code"]

    pool = dict(zip(latest["code"], latest["name"]))

    pool = enrich_names_with_tushare(token, pool)

    out_df = pd.DataFrame(
        [
            {
                "code": code,
                "ts_code": code_to_ts_code(code),
                "name": name,
                "source": f"tushare_index_weight_{latest_date}",
            }
            for code, name in pool.items()
        ]
    )

    os.makedirs(os.path.dirname(CSI300_POOL_CACHE_PATH), exist_ok=True)
    out_df.to_csv(CSI300_POOL_CACHE_PATH, index=False, encoding="utf-8-sig")

    print(f"[Universe] CSI300 from Tushare index_weight: {len(pool)} stocks")
    print(f"[Universe] saved -> {CSI300_POOL_CACHE_PATH}")

    return pool


def load_cached_csi300_pool() -> dict:
    if not os.path.exists(CSI300_POOL_CACHE_PATH):
        raise FileNotFoundError(CSI300_POOL_CACHE_PATH)

    df = pd.read_csv(
        CSI300_POOL_CACHE_PATH,
        dtype={"code": str, "ts_code": str, "name": str, "source": str},
    )
    df["code"] = df["code"].astype(str).str.zfill(6)

    if "name" not in df.columns:
        df["name"] = df["code"]
    else:
        df["name"] = df["name"].astype(str)
        numeric_name = df["name"].str.fullmatch(r"\d+")
        df.loc[numeric_name, "name"] = df.loc[numeric_name, "name"].str.zfill(6)

    if not 250 <= len(df) <= 350:
        raise ValueError(
            f"CSI300 缓存数量异常：{len(df)}，将尝试从 Qlib 或 Tushare 重建。"
        )

    return dict(zip(df["code"], df["name"]))


def get_stock_pool(token: str | None = None, enrich_name: bool = False) -> dict:
    """
    统一股票池入口。

    - daily_incremental_update.py 用这个读取 CSI300；
    - APP 展示和外部模型更新也用这个读取 CSI300；
    - APP 展示 TopK 也基于这个股票池生成的结果。
    """
    universe = UNIVERSE.lower().strip()

    if universe == "manual":
        return STOCK_POOL

    if universe != "csi300":
        raise ValueError(f"不支持的 UNIVERSE：{UNIVERSE}")

    # 优先用缓存
    if os.path.exists(CSI300_POOL_CACHE_PATH):
        try:
            pool = load_cached_csi300_pool()

            if enrich_name and token:
                pool = enrich_names_with_tushare(token, pool)

            print(f"[Universe] CSI300 from cache: {len(pool)} stocks")
            return pool
        except Exception as e:
            print(f"[Universe] cached CSI300 invalid: {e}")

    # 第二优先：Qlib instruments/csi300.txt
    try:
        pool = read_csi300_from_qlib_instruments()

        if enrich_name and token:
            pool = enrich_names_with_tushare(token, pool)

        return pool

    except Exception as e:
        print(f"[Universe] read Qlib CSI300 failed: {e}")

    # 第三优先：Tushare index_weight
    if USE_TUSHARE_INDEX_WEIGHT_FALLBACK and token:
        return read_csi300_from_tushare_index_weight(token)

    raise RuntimeError(
        "无法获取 CSI300 股票池。\n"
        "请检查：\n"
        f"1. Qlib 路径是否正确：{QLIB_PROVIDER_URI}\n"
        "2. 是否存在 instruments/csi300.txt\n"
        "3. 或者在 APP 中填写 Tushare Token 后再尝试。"
    )
