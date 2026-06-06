import os
import warnings
from datetime import datetime

import time
import random

import argparse


from config import DEFAULT_KLINE_MODEL


import akshare as ak
import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import accuracy_score, mean_squared_error, roc_auc_score

from config import (
    STOCK_POOL,
    START_DATE,
    PRED_HORIZON,
    ALPHA_WINDOWS,
    EPS,
    DATA_DIR,
    MODEL_DIR,
    OUTPUT_DIR,
    RAW_DATA_PATH,
    FEATURE_DATA_PATH,
    REG_MODEL_PATH,
    CLS_MODEL_PATH,
    METRICS_PATH,
    RANKING_LATEST_PATH,
    EVAL_METRICS_PATH,
)
from model_factory import create_kline_models

warnings.filterwarnings("ignore")


# ============================================================
# 1. 工具函数
# ============================================================

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def safe_div(a, b):
    return a / (b + EPS)


def rolling_slope(x):
    if np.any(np.isnan(x)):
        return np.nan
    n = len(x)
    t = np.arange(n)
    try:
        return np.polyfit(t, x, 1)[0]
    except Exception:
        return np.nan


def rolling_rsqr(x):
    if np.any(np.isnan(x)):
        return np.nan
    n = len(x)
    t = np.arange(n)
    try:
        coef = np.polyfit(t, x, 1)
        y_hat = coef[0] * t + coef[1]
        ss_res = np.sum((x - y_hat) ** 2)
        ss_tot = np.sum((x - np.mean(x)) ** 2)
        if ss_tot < EPS:
            return 0.0
        return 1 - ss_res / ss_tot
    except Exception:
        return np.nan


def rolling_resi(x):
    if np.any(np.isnan(x)):
        return np.nan
    n = len(x)
    t = np.arange(n)
    try:
        coef = np.polyfit(t, x, 1)
        y_hat_last = coef[0] * t[-1] + coef[1]
        return x[-1] - y_hat_last
    except Exception:
        return np.nan


def rolling_rank_last(x):
    if np.any(np.isnan(x)):
        return np.nan
    last = x[-1]
    return np.mean(x <= last)


def days_since_max(x):
    if np.any(np.isnan(x)):
        return np.nan
    return len(x) - 1 - int(np.argmax(x))


def days_since_min(x):
    if np.any(np.isnan(x)):
        return np.nan
    return len(x) - 1 - int(np.argmin(x))


def format_code(code):
    return str(code).zfill(6)


# ============================================================
# 2. 获取 A 股日线数据
# ============================================================

def clear_proxy_env():
    """
    清理可能影响 AkShare 请求的代理环境变量。
    单只股票能取，但批量失败时，也可能是代理或连接复用问题。
    """
    proxy_keys = [
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ]

    for key in proxy_keys:
        if key in os.environ:
            print(f"[Proxy] remove env proxy: {key}={os.environ.get(key)}")
            os.environ.pop(key, None)


def fetch_one_stock(code: str, name: str, max_retries: int = 5) -> pd.DataFrame:
    code = format_code(code)
    print(f"[Fetch] {code} {name}")

    clear_proxy_env()

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            end_date = datetime.today().strftime("%Y%m%d")

            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=START_DATE,
                end_date=end_date,
                adjust="qfq"
            )

            if df is None or df.empty:
                print(f"[Warning] {code} {name} empty data")
                return pd.DataFrame()

            rename_map = {
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "振幅": "amplitude",
                "涨跌幅": "pct_chg",
                "涨跌额": "change",
                "换手率": "turnover",
            }

            df = df.rename(columns=rename_map)

            needed_cols = [
                "date", "open", "close", "high", "low",
                "volume", "amount", "pct_chg", "turnover"
            ]

            df = df[[c for c in needed_cols if c in df.columns]].copy()

            df["date"] = pd.to_datetime(df["date"])
            df["code"] = code
            df["name"] = name

            numeric_cols = [
                "open", "close", "high", "low",
                "volume", "amount", "pct_chg", "turnover"
            ]

            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            if "amount" in df.columns and "volume" in df.columns:
                df["vwap"] = df["amount"] / (df["volume"] * 100 + EPS)
            else:
                df["vwap"] = df["close"]

            df = df.sort_values("date").reset_index(drop=True)

            print(f"[OK] {code} {name}, rows={len(df)}")
            return df

        except Exception as e:
            last_error = e
            wait_seconds = 2 + attempt * 2 + random.random() * 2

            print(
                f"[Retry {attempt}/{max_retries}] {code} {name} failed: {e}"
            )
            print(f"[Sleep] wait {wait_seconds:.1f}s then retry")

            time.sleep(wait_seconds)

    print(f"[Error] {code} {name} final failed: {last_error}")
    return pd.DataFrame()


def fetch_all_data() -> pd.DataFrame:
    clear_proxy_env()

    all_data = []

    for i, (code, name) in enumerate(STOCK_POOL.items(), start=1):
        print(f"[Progress] {i}/{len(STOCK_POOL)}")

        df = fetch_one_stock(code, name)

        if not df.empty:
            all_data.append(df)

            # 每只股票单独保存一份缓存，后面某一只失败时也能复用
            single_cache_dir = os.path.join(DATA_DIR, "single_stock_cache")
            os.makedirs(single_cache_dir, exist_ok=True)

            single_cache_path = os.path.join(
                single_cache_dir,
                f"{format_code(code)}.csv"
            )

            df.to_csv(single_cache_path, index=False, encoding="utf-8-sig")

        else:
            # 单只股票失败时，尝试使用该股票本地缓存
            single_cache_path = os.path.join(
                DATA_DIR,
                "single_stock_cache",
                f"{format_code(code)}.csv"
            )

            if os.path.exists(single_cache_path):
                print(f"[Cache] use cached data for {code} {name}")
                cache_df = pd.read_csv(single_cache_path, dtype={"code": str})
                cache_df["code"] = cache_df["code"].astype(str).str.zfill(6)
                cache_df["date"] = pd.to_datetime(cache_df["date"])
                all_data.append(cache_df)

        # 重点：批量请求时必须放慢，避免被接口断开
        sleep_seconds = 2.0 + random.random() * 2.0
        print(f"[Sleep] {sleep_seconds:.1f}s before next stock")
        time.sleep(sleep_seconds)

    if all_data:
        data = pd.concat(all_data, ignore_index=True)
        data = data.sort_values(["code", "date"]).reset_index(drop=True)

        data.to_csv(RAW_DATA_PATH, index=False, encoding="utf-8-sig")
        print(f"[Save] raw data -> {RAW_DATA_PATH}, shape={data.shape}")
        print(f"[Info] stock count = {data['code'].nunique()}")

        return data

    # 如果今天全失败，但之前成功过，就用全量缓存
    if os.path.exists(RAW_DATA_PATH):
        print("[Warning] 今日在线获取失败，使用本地缓存 raw_stock_data.csv")
        data = pd.read_csv(RAW_DATA_PATH, dtype={"code": str})
        data["code"] = data["code"].astype(str).str.zfill(6)
        data["date"] = pd.to_datetime(data["date"])
        return data

    raise RuntimeError(
        "没有获取到任何股票数据，并且本地没有缓存。"
        "单只股票测试可用时，通常是批量请求过快或网络临时失败。"
        "请稍后重试，或减少股票池数量。"
    )


# ============================================================
# 3. Alpha158 因子
# ============================================================

def add_alpha158_for_one_stock(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").copy()

    close = g["close"]
    open_ = g["open"]
    high = g["high"]
    low = g["low"]
    volume = g["volume"]
    vwap = g["vwap"]

    max_oc = pd.concat([open_, close], axis=1).max(axis=1)
    min_oc = pd.concat([open_, close], axis=1).min(axis=1)
    high_low_range = high - low

    # --------------------------------------------------------
    # A. K 线形态因子：9 个
    # --------------------------------------------------------

    g["KMID"] = safe_div(close - open_, open_)
    g["KLEN"] = safe_div(high - low, open_)
    g["KMID2"] = safe_div(close - open_, high_low_range)
    g["KUP"] = safe_div(high - max_oc, open_)
    g["KUP2"] = safe_div(high - max_oc, high_low_range)
    g["KLOW"] = safe_div(min_oc - low, open_)
    g["KLOW2"] = safe_div(min_oc - low, high_low_range)
    g["KSFT"] = safe_div(2 * close - high - low, open_)
    g["KSFT2"] = safe_div(2 * close - high - low, high_low_range)

    # --------------------------------------------------------
    # B. 当日相对价格因子：4 个
    # --------------------------------------------------------

    g["OPEN0"] = safe_div(open_, close)
    g["HIGH0"] = safe_div(high, close)
    g["LOW0"] = safe_div(low, close)
    g["VWAP0"] = safe_div(vwap, close)

    # --------------------------------------------------------
    # C. 滚动因子：29 类 × 5 窗口 = 145 个
    # 总计 9 + 4 + 145 = 158 个
    # --------------------------------------------------------

    ret_1 = close.pct_change(1)

    price_diff = close.diff()
    price_abs_chg = price_diff.abs()

    up_price = price_diff.clip(lower=0)
    down_price = (-price_diff).clip(lower=0)

    volume_diff = volume.diff()
    volume_abs_chg = volume_diff.abs()

    up_volume = volume_diff.clip(lower=0)
    down_volume = (-volume_diff).clip(lower=0)

    price_ratio = safe_div(close, close.shift(1))
    volume_ratio_log = np.log(safe_div(volume, volume.shift(1)) + 1)

    weighted_abs_ret_volume = ret_1.abs() * volume

    for d in ALPHA_WINDOWS:
        # 1. ROC
        g[f"ROC{d}"] = safe_div(close.shift(d), close)

        # 2. MA
        g[f"MA{d}"] = safe_div(close.rolling(d).mean(), close)

        # 3. STD
        g[f"STD{d}"] = safe_div(close.rolling(d).std(), close)

        # 4. BETA
        g[f"BETA{d}"] = safe_div(
            close.rolling(d).apply(rolling_slope, raw=True),
            close
        )

        # 5. RSQR
        g[f"RSQR{d}"] = close.rolling(d).apply(rolling_rsqr, raw=True)

        # 6. RESI
        g[f"RESI{d}"] = safe_div(
            close.rolling(d).apply(rolling_resi, raw=True),
            close
        )

        # 7. MAX
        g[f"MAX{d}"] = safe_div(high.rolling(d).max(), close)

        # 8. MIN
        g[f"MIN{d}"] = safe_div(low.rolling(d).min(), close)

        # 9. QTLU
        g[f"QTLU{d}"] = safe_div(close.rolling(d).quantile(0.8), close)

        # 10. QTLD
        g[f"QTLD{d}"] = safe_div(close.rolling(d).quantile(0.2), close)

        # 11. RANK
        g[f"RANK{d}"] = close.rolling(d).apply(rolling_rank_last, raw=True)

        # 12. RSV
        rolling_low = low.rolling(d).min()
        rolling_high = high.rolling(d).max()
        g[f"RSV{d}"] = safe_div(close - rolling_low, rolling_high - rolling_low)

        # 13. IMAX
        g[f"IMAX{d}"] = high.rolling(d).apply(days_since_max, raw=True) / d

        # 14. IMIN
        g[f"IMIN{d}"] = low.rolling(d).apply(days_since_min, raw=True) / d

        # 15. IMXD
        g[f"IMXD{d}"] = g[f"IMAX{d}"] - g[f"IMIN{d}"]

        # 16. CORR
        g[f"CORR{d}"] = close.rolling(d).corr(np.log(volume + 1))

        # 17. CORD
        g[f"CORD{d}"] = price_ratio.rolling(d).corr(volume_ratio_log)

        # 18. CNTP
        g[f"CNTP{d}"] = (close > close.shift(1)).astype(float).rolling(d).mean()

        # 19. CNTN
        g[f"CNTN{d}"] = (close < close.shift(1)).astype(float).rolling(d).mean()

        # 20. CNTD
        g[f"CNTD{d}"] = g[f"CNTP{d}"] - g[f"CNTN{d}"]

        # 21. SUMP
        g[f"SUMP{d}"] = safe_div(up_price.rolling(d).sum(), price_abs_chg.rolling(d).sum())

        # 22. SUMN
        g[f"SUMN{d}"] = safe_div(down_price.rolling(d).sum(), price_abs_chg.rolling(d).sum())

        # 23. SUMD
        g[f"SUMD{d}"] = safe_div(
            up_price.rolling(d).sum() - down_price.rolling(d).sum(),
            price_abs_chg.rolling(d).sum()
        )

        # 24. VMA
        g[f"VMA{d}"] = safe_div(volume.rolling(d).mean(), volume)

        # 25. VSTD
        g[f"VSTD{d}"] = safe_div(volume.rolling(d).std(), volume)

        # 26. WVMA
        g[f"WVMA{d}"] = safe_div(
            weighted_abs_ret_volume.rolling(d).std(),
            weighted_abs_ret_volume.rolling(d).mean()
        )

        # 27. VSUMP
        g[f"VSUMP{d}"] = safe_div(up_volume.rolling(d).sum(), volume_abs_chg.rolling(d).sum())

        # 28. VSUMN
        g[f"VSUMN{d}"] = safe_div(down_volume.rolling(d).sum(), volume_abs_chg.rolling(d).sum())

        # 29. VSUMD
        g[f"VSUMD{d}"] = safe_div(
            up_volume.rolling(d).sum() - down_volume.rolling(d).sum(),
            volume_abs_chg.rolling(d).sum()
        )

    # --------------------------------------------------------
    # D. 标签
    # --------------------------------------------------------

    g["future_5d_ret"] = close.shift(-PRED_HORIZON) / close - 1
    g["future_5d_up"] = (g["future_5d_ret"] > 0).astype(int)

    # --------------------------------------------------------
    # E. 展示辅助字段
    # --------------------------------------------------------

    g["ret_5"] = close.pct_change(5)
    g["ret_20"] = close.pct_change(20)
    g["vol_20"] = close.pct_change(1).rolling(20).std()
    g["drawdown_20"] = close / close.rolling(20).max() - 1

    return g


def add_alpha158_features(df: pd.DataFrame) -> pd.DataFrame:
    results = []

    for code, g in df.groupby("code"):
        print(f"[Alpha158] {code}")
        out = add_alpha158_for_one_stock(g)
        results.append(out)

    data = pd.concat(results, ignore_index=True)
    data = data.replace([np.inf, -np.inf], np.nan)

    data.to_csv(FEATURE_DATA_PATH, index=False, encoding="utf-8-sig")
    print(f"[Save] feature data -> {FEATURE_DATA_PATH}, shape={data.shape}")

    return data


def get_alpha158_feature_cols(df: pd.DataFrame):
    exclude_cols = {
        "date", "code", "name",
        "open", "close", "high", "low",
        "volume", "amount", "pct_chg", "turnover", "vwap",
        "future_5d_ret", "future_5d_up",
        "ret_5", "ret_20", "vol_20", "drawdown_20",
    }

    feature_cols = [
        c for c in df.columns
        if c not in exclude_cols and pd.api.types.is_numeric_dtype(df[c])
    ]

    return feature_cols


def prepare_model_data(data: pd.DataFrame, feature_cols):
    model_df = data.copy()

    model_df = model_df.dropna(
        subset=feature_cols + ["future_5d_ret", "future_5d_up"]
    ).copy()

    # 防止极端涨跌影响第一版模型
    model_df["future_5d_ret"] = model_df["future_5d_ret"].clip(-0.3, 0.3)

    return model_df


# ============================================================
# 4. 模型训练
# ============================================================

def train_models(model_df: pd.DataFrame, feature_cols, model_name: str):
    dates = sorted(model_df["date"].unique())

    if len(dates) < 200:
        raise RuntimeError("可用交易日太少，建议扩大时间范围或检查数据。")

    split_idx = int(len(dates) * 0.8)
    split_date = dates[split_idx]

    train_df = model_df[model_df["date"] < split_date].copy()
    test_df = model_df[model_df["date"] >= split_date].copy()

    X_train = train_df[feature_cols]
    y_train_reg = train_df["future_5d_ret"]
    y_train_cls = train_df["future_5d_up"]

    X_test = test_df[feature_cols]
    y_test_reg = test_df["future_5d_ret"]
    y_test_cls = test_df["future_5d_up"]

    print(f"[Model] create model: {model_name}")
    reg_model, cls_model = create_kline_models(model_name)

    print(f"[Train] {model_name} regressor")
    reg_model.fit(X_train, y_train_reg)

    print(f"[Train] {model_name} classifier")
    cls_model.fit(X_train, y_train_cls)

    test_df["pred_5d_ret"] = reg_model.predict(X_test)

    if hasattr(cls_model, "predict_proba"):
        test_df["up_prob"] = cls_model.predict_proba(X_test)[:, 1]
    else:
        pred_cls_raw = cls_model.predict(X_test)
        test_df["up_prob"] = pred_cls_raw.astype(float)

    test_df["pred_cls"] = (test_df["up_prob"] >= 0.5).astype(int)

    rmse = mean_squared_error(y_test_reg, test_df["pred_5d_ret"]) ** 0.5
    acc = accuracy_score(y_test_cls, test_df["pred_cls"])

    try:
        auc = roc_auc_score(y_test_cls, test_df["up_prob"])
    except Exception:
        auc = np.nan

    eval_metrics = evaluate_predictions(test_df)

    metrics = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "latest_data_date": str(model_df["date"].max().date()),
        "split_date": str(pd.to_datetime(split_date).date()),
        "model_name": model_name,
        "train_samples": int(len(train_df)),
        "test_samples": int(len(test_df)),
        "feature_type": "Alpha158",
        "feature_count": int(len(feature_cols)),
        "rmse": float(rmse),
        "accuracy": float(acc),
        "auc": float(auc) if not pd.isna(auc) else None,
        "ic_mean": eval_metrics.get("ic_mean"),
        "icir": eval_metrics.get("icir"),
        "rankic_mean": eval_metrics.get("rankic_mean"),
        "rankicir": eval_metrics.get("rankicir"),
        "top5_mean_ret": eval_metrics.get("top5_mean_ret"),
        "top10_mean_ret": eval_metrics.get("top10_mean_ret"),
        "features": feature_cols,
    }

    save_model_bundle(
        model_name=model_name,
        reg_model=reg_model,
        cls_model=cls_model,
        feature_cols=feature_cols,
        metrics=metrics,
    )

    # 兼容旧 app.py 的 metrics.pkl
    joblib.dump(metrics, METRICS_PATH)

    print("[Metrics]", metrics)

    return reg_model, cls_model, metrics, test_df


# ============================================================
# 5. IC / RankIC / TopK 评估
# ============================================================

def calc_ic(x, y):
    if len(x) < 3:
        return np.nan
    if np.std(x) < EPS or np.std(y) < EPS:
        return np.nan
    return np.corrcoef(x, y)[0, 1]


def calc_rankic(x, y):
    if len(x) < 3:
        return np.nan
    try:
        value = spearmanr(x, y).correlation
        return value
    except Exception:
        return np.nan


def evaluate_predictions(test_df: pd.DataFrame):
    daily_results = []

    for date, g in test_df.groupby("date"):
        g = g.dropna(subset=["pred_5d_ret", "future_5d_ret"]).copy()

        if len(g) < 3:
            continue

        ic = calc_ic(g["pred_5d_ret"].values, g["future_5d_ret"].values)
        rankic = calc_rankic(g["pred_5d_ret"].values, g["future_5d_ret"].values)

        top5_ret = g.sort_values("pred_5d_ret", ascending=False).head(5)["future_5d_ret"].mean()
        top10_ret = g.sort_values("pred_5d_ret", ascending=False).head(10)["future_5d_ret"].mean()

        daily_results.append({
            "date": date,
            "ic": ic,
            "rankic": rankic,
            "top5_ret": top5_ret,
            "top10_ret": top10_ret,
        })

    eval_df = pd.DataFrame(daily_results)

    if eval_df.empty:
        eval_df.to_csv(EVAL_METRICS_PATH, index=False, encoding="utf-8-sig")
        return {
            "ic_mean": None,
            "icir": None,
            "rankic_mean": None,
            "rankicir": None,
            "top5_mean_ret": None,
            "top10_mean_ret": None,
        }

    eval_df.to_csv(EVAL_METRICS_PATH, index=False, encoding="utf-8-sig")
    print(f"[Save] evaluation metrics -> {EVAL_METRICS_PATH}")

    ic_mean = eval_df["ic"].mean()
    ic_std = eval_df["ic"].std()
    rankic_mean = eval_df["rankic"].mean()
    rankic_std = eval_df["rankic"].std()

    metrics = {
        "ic_mean": float(ic_mean) if not pd.isna(ic_mean) else None,
        "icir": float(ic_mean / ic_std) if ic_std and not pd.isna(ic_std) and ic_std > EPS else None,
        "rankic_mean": float(rankic_mean) if not pd.isna(rankic_mean) else None,
        "rankicir": float(rankic_mean / rankic_std) if rankic_std and not pd.isna(rankic_std) and rankic_std > EPS else None,
        "top5_mean_ret": float(eval_df["top5_ret"].mean()),
        "top10_mean_ret": float(eval_df["top10_ret"].mean()),
    }

    return metrics


# ============================================================
# 6. 每日排名
# ============================================================

def risk_level(row):
    vol = row.get("vol_20", np.nan)
    dd = row.get("drawdown_20", np.nan)

    if pd.isna(vol) or pd.isna(dd):
        return "未知"

    if vol > 0.035 or dd < -0.15:
        return "高"
    elif vol > 0.025 or dd < -0.10:
        return "中"
    else:
        return "低"


def confidence_level(row):
    prob = row["up_prob"]
    vol = row.get("vol_20", np.nan)

    distance = abs(prob - 0.5)

    if pd.isna(vol):
        return "中"

    if distance > 0.18 and vol < 0.03:
        return "高"
    elif distance > 0.10 and vol < 0.04:
        return "中"
    else:
        return "低"


def make_latest_ranking(data: pd.DataFrame, reg_model, cls_model, feature_cols, model_name: str):
    latest_rows = []

    for code, g in data.groupby("code"):
        g = g.sort_values("date").copy()
        latest = g.dropna(subset=feature_cols).tail(1)
        if not latest.empty:
            latest_rows.append(latest)

    if not latest_rows:
        raise RuntimeError("没有可用于预测的最新样本。")

    latest_df = pd.concat(latest_rows, ignore_index=True)
    X_latest = latest_df[feature_cols]

    latest_df["pred_5d_ret"] = reg_model.predict(X_latest)

    if hasattr(cls_model, "predict_proba"):
        latest_df["up_prob"] = cls_model.predict_proba(X_latest)[:, 1]
    else:
        pred_cls_raw = cls_model.predict(X_latest)
        latest_df["up_prob"] = pred_cls_raw.astype(float)

    latest_df["score"] = (
        latest_df["pred_5d_ret"].rank(pct=True) * 0.50
        + latest_df["up_prob"].rank(pct=True) * 0.40
        + latest_df["drawdown_20"].rank(pct=True) * 0.10
    )

    latest_df["risk_level"] = latest_df.apply(risk_level, axis=1)
    latest_df["confidence"] = latest_df.apply(confidence_level, axis=1)
    latest_df["model_name"] = model_name

    result = latest_df[
        [
            "date", "code", "name", "close",
            "pred_5d_ret", "up_prob", "score",
            "confidence", "risk_level", "model_name",
            "ret_5", "ret_20", "vol_20", "drawdown_20",
        ]
    ].copy()

    result = result.sort_values("score", ascending=False).reset_index(drop=True)
    result.insert(0, "rank", np.arange(1, len(result) + 1))

    result["code"] = result["code"].astype(str).str.zfill(6)

    result.to_csv(RANKING_LATEST_PATH, index=False, encoding="utf-8-sig")

    dated_path = os.path.join(
        OUTPUT_DIR,
        f"ranking_{datetime.today().strftime('%Y%m%d')}_{model_name}.csv"
    )
    result.to_csv(dated_path, index=False, encoding="utf-8-sig")

    print(f"[Save] latest ranking -> {RANKING_LATEST_PATH}")
    print(f"[Save] dated ranking -> {dated_path}")

    return result


# ============================================================
# 7. 主流程
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        type=str,
        default="retrain",
        choices=["retrain", "predict"],
        help="retrain：重新训练模型；predict：读取已有模型，只生成最新排名"
    )

    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_KLINE_MODEL,
        choices=["torch_mlp"],
        help="选择 K 线/Alpha158 模型"
    )

    parser.add_argument(
        "--version",
        type=str,
        default="latest",
        help="predict 模式下读取哪个模型版本，默认 latest"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    ensure_dirs()

    model_name = args.model.lower().strip()
    mode = args.mode.lower().strip()

    print("=" * 80)
    print("[Daily Update Start]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print(f"[Mode] {mode}")
    print(f"[Model] {model_name}")
    print("=" * 80)

    # 每次都获取最新数据并计算最新因子。
    # retrain 模式：用这些数据重新训练模型；
    # predict 模式：用这些数据配合已有模型生成排名。
    raw_data = fetch_all_data()
    data_with_features = add_alpha158_features(raw_data)
    feature_cols_current = get_alpha158_feature_cols(data_with_features)

    print(f"[Feature] current Alpha158 feature count = {len(feature_cols_current)}")

    if len(feature_cols_current) != 158:
        print(f"[Warning] 当前特征数量不是 158，而是 {len(feature_cols_current)}。请检查字段。")

    if mode == "retrain":
        model_df = prepare_model_data(data_with_features, feature_cols_current)

        if model_df.empty:
            raise RuntimeError("模型训练数据为空，请检查 Alpha158 因子构造。")

        reg_model, cls_model, metrics, test_df = train_models(
            model_df=model_df,
            feature_cols=feature_cols_current,
            model_name=model_name,
        )

        feature_cols_for_predict = feature_cols_current

    else:
        bundle = load_model_bundle(model_name=model_name, version=args.version)

        reg_model = bundle["reg_model"]
        cls_model = bundle["cls_model"]
        feature_cols_for_predict = bundle["feature_cols"]
        metrics = bundle["metrics"]

        # 兼容旧 app.py 的 metrics.pkl
        joblib.dump(metrics, METRICS_PATH)

        missing_features = [
            c for c in feature_cols_for_predict
            if c not in data_with_features.columns
        ]

        if missing_features:
            raise ValueError(
                f"当前特征数据缺少模型训练时使用的特征：{missing_features[:20]}"
            )

    ranking = make_latest_ranking(
        data=data_with_features,
        reg_model=reg_model,
        cls_model=cls_model,
        feature_cols=feature_cols_for_predict,
        model_name=model_name,
    )

    print("[Top 5]")
    print(
        ranking.head(5)[
            [
                "rank", "code", "name",
                "pred_5d_ret", "up_prob", "score",
                "confidence", "risk_level", "model_name"
            ]
        ]
    )

    print("=" * 80)
    print("[Daily Update Finished]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)


if __name__ == "__main__":
    main()