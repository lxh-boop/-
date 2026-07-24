import os

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx



import json
import time
from pathlib import Path

from client.api.dashboard import (
    ANNOUNCEMENT_CACHE_PATH,
    AGENT_QUANT_DB_PATH,
    A_SHARE_DAILY_DATA_READY_TIME,
    BACKTEST_DAILY_PREDICTIONS_PATH,
    BACKTEST_DISCLAIMER,
    BACKTEST_MASTER_TABLE_PATH,
    BACKTEST_METRICS_PATH,
    BACKTEST_NAV_PATH,
    BACKTEST_TRADES_PATH,
    BASE_DIR,
    DEFAULT_DFT_UNET_CHECKPOINT_PATH,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    ENABLE_LLM_EXPLAINER,
    ENABLE_NEWS_FEATURES,
    ENABLE_RAG,
    LATEST_FEATURE_DATA_PATH,
    LATEST_RAW_DATA_PATH,
    LLM_API_KEY_ENV,
    LLM_BASE_URL_ENV,
    LLM_MODEL_ENV,
    LOG_DIR,
    LLMService,
    MARKET_CONTEXT_FEATURE_CACHE_PATH,
    MARKET_CONTEXT_INDEX_DAILY_CACHE_PATH,
    METRICS_PATH,
    MODEL_CANDIDATES_PATH,
    MODEL_SEARCH_RESULTS_PATH,
    NEWS_CACHE_PATH,
    OLLAMA_PROJECT_MODEL,
    OLLAMA_PROJECT_MODELFILE_NAME,
    OUTPUT_DIR,
    PROGRESS_HISTORY_PATH,
    RAG_DOCUMENTS_PATH,
    RAG_INDEX_PATH,
    RANKING_LATEST_PATH,
    RECOMMENDED_BASE_MODEL,
    ROLLING_UPDATE_LOG_PATH,
    ROLLING_UPDATE_SCRIPT,
    RUN_CWD,
    SELECTED_STRATEGY_PATH,
    UNIVERSE,
    build_display_date_options,
    classify_event_title,
    build_mcp_context_from_local_config,
    calculate_topk_rebalance,
    build_stock_explanation_prompt,
    create_project_model,
    create_scheduler,
    dashboard_service,
    discover_mcp_tools,
    downloaded_zoo_backends,
    ensure_runtime_directories,
    explain_prompt_with_llm,
    get_ollama_version,
    get_scheduler_jobs,
    is_frozen_app,
    is_prediction_only_date,
    is_zoo_backend,
    list_local_models,
    list_model_names,
    load_cached_ai_explanation,
    load_daily_returns_for_strategy,
    load_local_config,
    load_selected_strategy,
    mcp_sdk_version,
    pull_model,
    read_auto_retrain_log,
    registered_zoo_backends,
    reset_discovery_cache,
    resolve_active_llm_settings,
    run_latest_t1_backtest,
    save_local_config,
    set_daily_retrain_job,
    validate_local_model,
    validate_tushare_token,
    zoo_model_name_from_backend,
)

APP_TOP_LEVEL_PAGES = ["首页 / 预测排名", "AI 模拟盘", "AI Agent", "系统监控"]


def get_app_top_level_pages() -> list[str]:
    return list(APP_TOP_LEVEL_PAGES)


if get_script_run_ctx(suppress_warning=True) is None and __name__ == "__main__":
    print("Run this app with: streamlit run app.py  (not: python app.py)")
    raise SystemExit(0)

ensure_runtime_directories()

DATA_CACHE_TTL_SECONDS = 300
NEWS_CACHE_TTL_SECONDS = 600
RAG_CACHE_TTL_SECONDS = 600
MODEL_METADATA_CACHE_TTL_SECONDS = 600


def _path_cache_version(path: str | Path) -> tuple[str, int, int]:
    return dashboard_service.path_cache_version(path)


@st.cache_resource
def _get_ai_agent_page_renderer():
    from app.pages.ai_agent import render_ai_agent_page
    return render_ai_agent_page


@st.cache_resource
def _get_ai_paper_trading_page_renderer():
    from app.pages.ai_paper_trading import render_ai_paper_trading_page
    return render_ai_paper_trading_page


@st.cache_resource
def _get_model_search_page_renderer():
    from app.pages.model_search import render_model_search_page
    return render_model_search_page


@st.cache_resource
def _get_system_monitor_page_renderer():
    from app.pages.system_monitor import render_system_monitor_page
    return render_system_monitor_page


def load_event_cache():
    return dashboard_service.load_event_cache()


def retrieve_stock_context(*args, **kwargs):
    return dashboard_service.retrieve_stock_context(*args, **kwargs)


@st.cache_data(ttl=RAG_CACHE_TTL_SECONDS)
def _cached_retrieve_stock_context(
    code: str,
    query: str,
    top_k: int,
    rag_index_version: tuple[str, int, int],
    rag_documents_version: tuple[str, int, int],
) -> pd.DataFrame:
    del rag_index_version, rag_documents_version
    return retrieve_stock_context(code=code, query=query, top_k=int(top_k))


def cached_retrieve_stock_context(*, code: str, query: str, top_k: int) -> pd.DataFrame:
    return _cached_retrieve_stock_context(
        str(code).zfill(6),
        str(query or ""),
        int(top_k),
        _path_cache_version(RAG_INDEX_PATH),
        _path_cache_version(RAG_DOCUMENTS_PATH),
    )


from datetime import datetime, time as datetime_time

st.set_page_config(
    page_title="A股每日股票评分系统",
    page_icon="📈",
    layout="wide"
)

@st.cache_resource
def get_app_scheduler():
    return create_scheduler()


scheduler = get_app_scheduler()
local_cfg = load_local_config()


def normalize_page_zoom(value) -> int:
    try:
        zoom = int(value)
    except (TypeError, ValueError):
        zoom = 100
    return max(80, min(150, zoom))


def apply_page_zoom(percent: int) -> None:
    zoom = normalize_page_zoom(percent) / 100.0
    st.markdown(
        f"""
        <style>
        [data-testid="stAppViewContainer"] .main .block-container {{
            zoom: {zoom:.2f};
        }}
        section[data-testid="stSidebar"] > div {{
            zoom: {zoom:.2f};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


page_zoom_percent = normalize_page_zoom(
    st.session_state.get("page_zoom_percent", local_cfg.get("page_zoom_percent", 100))
)
apply_page_zoom(page_zoom_percent)

def load_time_estimate(default_seconds: int = 300) -> int:
    return dashboard_service.load_time_estimate(default_seconds)

def save_time_cost(seconds: float):
    dashboard_service.save_time_cost(seconds)

def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    sec = seconds % 60

    if minutes <= 0:
        return f"{sec} 秒"

    return f"{minutes} 分 {sec} 秒"


def get_stage_by_progress(
    progress_value: float,
    elapsed: float,
    estimated_seconds: int,
) -> str:
    """
    按时间进度显示当前阶段，不依赖控制台输出。
    """
    if elapsed > estimated_seconds:
        return "已超过预计时间，后台任务仍在运行，请等待或查看日志"

    if progress_value < 0.10:
        return "准备任务，读取模型库配置"
    elif progress_value < 0.30:
        return "正在拉取最新行情数据"
    elif progress_value < 0.45:
        return "正在构造 Alpha158 因子"
    elif progress_value < 0.80:
        return "正在检查是否存在新增可监督样本"
    else:
        return "正在保存模型并生成预测排名"


def read_log_tail(path: Path, max_chars: int = 2000) -> str:
    return dashboard_service.read_log_tail(path, max_chars=max_chars)

def get_ranking_file_snapshot(path: str | Path = RANKING_LATEST_PATH) -> dict:
    return dashboard_service.get_ranking_file_snapshot(path)

def format_ranking_file_snapshot(snapshot: dict) -> str:
    if not snapshot.get("exists"):
        return "ranking_latest.csv 不存在"
    parts = [
        f"文件时间：{snapshot.get('mtime_text')}",
        f"行数：{snapshot.get('rows', 0)}",
    ]
    if snapshot.get("signal_date"):
        parts.append(f"信号日期：{snapshot.get('signal_date')}")
    if snapshot.get("prediction_date"):
        parts.append(f"预测日期：{snapshot.get('prediction_date')}")
    if snapshot.get("read_error"):
        parts.append(f"读取提示：{snapshot.get('read_error')}")
    return " ｜ ".join(parts)


def run_rolling_update_with_time_progress(
    token: str,
    base_version: str = "latest",
    model_backend: str = "zoo:chronos_bolt_small",
    checkpoint_path: str | None = None,
    default_estimate_seconds: int = 300,
    timeout_seconds: int = 3600,
):
    """
    按预计耗时显示进度条，不打印控制台输出。

    重点：
    1. stdout/stderr 不使用 PIPE，避免子进程输出过多导致卡死；
    2. 输出写入 logs/rolling_update_app.log；
    3. 进度条按时间推进，脚本未结束前最多到 95%；
    4. 超过 timeout_seconds 自动终止。
    """

    estimated_seconds = load_time_estimate(default_seconds=default_estimate_seconds)

    progress_bar = st.progress(0)
    status_box = st.empty()
    time_box = st.empty()

    start_time = time.time()
    ranking_before = get_ranking_file_snapshot()

    job = dashboard_service.start_rolling_update_job(
        token=token,
        base_version=base_version,
        model_backend=model_backend,
        checkpoint_path=checkpoint_path,
    )

    try:
        last_progress = 0.0

        while job.poll() is None:
            elapsed = time.time() - start_time

            if elapsed > timeout_seconds:
                job.kill()
                progress_bar.progress(min(int(last_progress * 100), 95))
                status_box.error("滚动更新超时，已自动终止。")
                time_box.caption(
                    f"已运行：{format_seconds(elapsed)} ｜ "
                    f"超时时间：{format_seconds(timeout_seconds)}"
                )

                job.write_log("\n[APP Error] rolling update timeout, process killed.\n")

                return False, read_log_tail(ROLLING_UPDATE_LOG_PATH)

            progress_value = min(elapsed / estimated_seconds, 0.95)
            progress_value = max(progress_value, last_progress)
            last_progress = progress_value

            percent = int(progress_value * 100)
            remaining = max(estimated_seconds - elapsed, 0)

            progress_bar.progress(percent)
            stage = get_stage_by_progress(
                progress_value=progress_value,
                elapsed=elapsed,
                estimated_seconds=estimated_seconds,
            )
            status_box.info(f"{stage}：预计进度 {percent}%")

            time_box.caption(
                f"预计总耗时：{format_seconds(estimated_seconds)} ｜ "
                f"已运行：{format_seconds(elapsed)} ｜ "
                f"预计剩余：{format_seconds(remaining)}"
            )

            time.sleep(1)

        return_code = job.returncode
        elapsed = time.time() - start_time

        job.write_log("\n" + "=" * 100 + "\n")
        job.write_log(f"[APP Rolling Update Finished] {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        job.write_log(f"[Return Code] {return_code}\n")
        job.write_log(f"[Elapsed Seconds] {elapsed:.2f}\n")
        job.write_log("=" * 100 + "\n")
    finally:
        job.close()

    if return_code == 0:
        save_time_cost(elapsed)

        progress_bar.progress(100)
        metrics = load_selected_model_metrics(model_backend) or {}
        ranking_after = get_ranking_file_snapshot()
        ranking_status_text = format_ranking_file_snapshot(ranking_after)
        if str(metrics.get("status") or "").startswith("prediction_skipped"):
            status_box.warning("每日数据缓存已更新，但预测阶段被跳过，ranking_latest.csv 没有刷新。")
            time_box.caption(
                f"本次实际耗时：{format_seconds(elapsed)} ｜ "
                f"{ranking_status_text} ｜ 详情请查看模型指标或更新日志。"
            )
            return False, read_log_tail(ROLLING_UPDATE_LOG_PATH)
        if not ranking_after.get("exists"):
            status_box.error("每日更新进程结束，但没有生成 ranking_latest.csv。")
            time_box.caption(f"本次实际耗时：{format_seconds(elapsed)}")
            return False, read_log_tail(ROLLING_UPDATE_LOG_PATH)
        if ranking_after.get("mtime", 0.0) <= ranking_before.get("mtime", 0.0):
            status_box.warning("每日更新进程结束，但未检测到 ranking_latest.csv 被改写。")
            time_box.caption(
                f"本次实际耗时：{format_seconds(elapsed)} ｜ "
                f"{ranking_status_text} ｜ 请查看更新日志确认原因。"
            )
            return False, read_log_tail(ROLLING_UPDATE_LOG_PATH)
        status_box.success("每日更新完成，预测排名已生成：100%")
        time_box.caption(
            f"本次实际耗时：{format_seconds(elapsed)} ｜ "
            f"{ranking_status_text} ｜ 下次将根据本次耗时自动估计进度"
        )

        return True, ""

    progress_bar.progress(min(int(last_progress * 100), 95))
    status_box.error("每日更新失败。")

    return False, read_log_tail(ROLLING_UPDATE_LOG_PATH)



def render_top_level_page_selector() -> str | None:
    """Render the top-level page selector for prediction / AI 模拟盘 / AI Agent."""
    selected = st.radio("页面", options=APP_TOP_LEVEL_PAGES, horizontal=True)
    return None if selected == "首页 / 预测排名" else selected


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS)
def _load_ranking_cached(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    del mtime_ns, size
    frame = dashboard_service.load_ranking(path)
    return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()

def load_ranking():
    path, mtime_ns, size = _path_cache_version(RANKING_LATEST_PATH)
    if not mtime_ns:
        return None

    return _load_ranking_cached(path, mtime_ns, size)


@st.cache_data(ttl=MODEL_METADATA_CACHE_TTL_SECONDS)
def _load_metrics_cached(path: str, mtime_ns: int, size: int):
    del mtime_ns, size
    return dashboard_service.load_metrics(path)

def load_metrics():
    path, mtime_ns, size = _path_cache_version(METRICS_PATH)
    if not mtime_ns:
        return None

    return _load_metrics_cached(path, mtime_ns, size)


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS)
def _load_json_file_cached(path: str, mtime_ns: int, size: int) -> dict | None:
    del mtime_ns, size
    return dashboard_service.load_json_file(path)

def load_json_file(path: str | Path) -> dict | None:
    path_text, mtime_ns, size = _path_cache_version(path)
    if not mtime_ns:
        return None
    return _load_json_file_cached(path_text, mtime_ns, size)


def backend_display_name(model_backend: str) -> str:
    if model_backend == "dft_unet_external":
        return "DFT_UNET"
    if is_zoo_backend(model_backend):
        return f"Model Zoo - {zoo_model_name_from_backend(model_backend)}"
    return str(model_backend or "未知")


def load_selected_model_metrics(model_backend: str) -> dict | None:
    if model_backend == "dft_unet_external":
        data = load_json_file(Path(OUTPUT_DIR) / "external_dft_unet_latest_metrics.json")
        if data:
            return data
        return {
            "model_name": "dft_unet_external",
            "model_backend": model_backend,
            "status": "暂无 DFT_UNET 每日更新指标，请先运行每日更新。",
        }

    if is_zoo_backend(model_backend):
        zoo_model_name = zoo_model_name_from_backend(model_backend)
        data = load_json_file(Path(OUTPUT_DIR) / "model_zoo_latest_metrics.json")
        if data and data.get("model_backend") == model_backend:
            return data

        zoo_table = load_model_zoo_table()
        row = pd.DataFrame()
        if not zoo_table.empty and "name" in zoo_table.columns:
            row = zoo_table[zoo_table["name"].astype(str) == zoo_model_name].tail(1)
        fallback = {
            "model_name": zoo_model_name,
            "model_backend": model_backend,
            "status": "暂无该模型的每日更新指标，请先运行每日更新。",
        }
        if not row.empty:
            fallback.update(row.iloc[0].to_dict())
        return fallback

    return None


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS)
def _load_backtest_outputs_cached(
    nav_version: tuple[str, int, int],
    trades_version: tuple[str, int, int],
    metrics_version: tuple[str, int, int],
    predictions_version: tuple[str, int, int],
):
    del nav_version, trades_version, metrics_version, predictions_version
    return dashboard_service.load_backtest_outputs()

def load_backtest_outputs():
    return _load_backtest_outputs_cached(
        _path_cache_version(BACKTEST_NAV_PATH),
        _path_cache_version(BACKTEST_TRADES_PATH),
        _path_cache_version(BACKTEST_METRICS_PATH),
        _path_cache_version(BACKTEST_DAILY_PREDICTIONS_PATH),
    )


@st.cache_data(ttl=MODEL_METADATA_CACHE_TTL_SECONDS)
def load_model_zoo_table() -> pd.DataFrame:
    return dashboard_service.load_model_zoo_table()

def _load_external_backtest_summary_cached(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    del path, mtime_ns, size
    return dashboard_service.load_external_backtest_summary()

def load_external_backtest_summary() -> pd.DataFrame:
    return dashboard_service.load_external_backtest_summary()


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS)
def _load_external_daily_returns_cached(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    del path, mtime_ns, size
    return pd.DataFrame()

def load_external_daily_returns(model_name: str, topk: int) -> pd.DataFrame:
    return dashboard_service.load_external_daily_returns(model_name, topk)

def calc_drawdown_series(nav_series: pd.Series) -> pd.Series:
    nav = pd.to_numeric(nav_series, errors="coerce")
    running_max = nav.cummax()
    return nav / running_max - 1.0


def build_topk_comparison(
    predictions_df: pd.DataFrame | None,
    topk_options=(10, 20, 30, 50),
    buy_cost: float = 0.0003,
    sell_cost: float = 0.0003,
    stamp_tax: float = 0.0005,
):
    if predictions_df is None or predictions_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    required_cols = {"date", "code", "score", "t1_ret"}
    if not required_cols.issubset(set(predictions_df.columns)):
        return pd.DataFrame(), pd.DataFrame()

    data = predictions_df.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["score"] = pd.to_numeric(data["score"], errors="coerce")
    data["t1_ret"] = pd.to_numeric(data["t1_ret"], errors="coerce")
    data = data.dropna(subset=["date", "code", "score", "t1_ret"])

    compare_rows = []
    metric_rows = []

    for topk in topk_options:
        nav = 1.0
        previous_holdings: set[str] = set()
        rows = []

        for date, g in data.groupby("date"):
            selected = g.sort_values("score", ascending=False).head(int(topk)).copy()

            if selected.empty:
                continue

            rebalance = calculate_topk_rebalance(previous_holdings, selected["code"].astype(str).tolist())
            current_holdings = rebalance.current_codes
            selected_count = len(selected)
            period_ret = float(selected["t1_ret"].mean())
            net_ret = period_ret - (
                rebalance.buy_turnover * buy_cost
                + rebalance.sell_turnover * (sell_cost + stamp_tax)
            )
            nav *= 1.0 + net_ret

            row = {
                "date": date,
                "topk": f"Top{int(topk)}",
                "nav": nav,
                "period_ret": period_ret,
                "net_ret": net_ret,
                "turnover": rebalance.turnover,
                "buy_turnover": rebalance.buy_turnover,
                "sell_turnover": rebalance.sell_turnover,
                "selected_count": selected_count,
            }
            compare_rows.append(row)
            rows.append(row)
            previous_holdings = current_holdings

        topk_df = pd.DataFrame(rows)

        if topk_df.empty:
            continue

        drawdown = calc_drawdown_series(topk_df["nav"])
        returns = topk_df["net_ret"]
        sharpe = None

        if len(returns) > 1 and returns.std() > 1e-12:
            sharpe = float(returns.mean() / returns.std() * (252 ** 0.5))

        metric_rows.append(
            {
                "TopK": f"Top{int(topk)}",
                "累计收益": float(topk_df["nav"].iloc[-1] - 1.0),
                "最大回撤": float(drawdown.min()),
                "胜率": float((returns > 0).mean()),
                "平均换手": float(topk_df["turnover"].mean()),
                "夏普比率": sharpe,
            }
        )

    return pd.DataFrame(compare_rows), pd.DataFrame(metric_rows)


@st.cache_data(ttl=300)
def load_news_events_for_app():
    return dashboard_service.load_news_events_for_app()

def format_percent_columns(df, cols):
    out = df.copy()

    for col in cols:
        if col in out.columns:
            out[col] = out[col].map(lambda x: f"{x:.2%}" if pd.notna(x) else "")

    return out


def format_tushare_pct_chg(value) -> str:
    """Tushare pct_chg is already expressed in percentage points, e.g. 7.04 means 7.04%."""
    numeric = pd.to_numeric(value, errors="coerce")
    return f"{numeric:.2f}%" if pd.notna(numeric) else ""


def parse_detail_json(value):
    if not isinstance(value, str) or not value.strip():
        return {}

    try:
        return json.loads(value)
    except Exception:
        return {"raw": value}


def format_metric_float(value, digits: int = 4) -> str:
    if value is None:
        return "N/A"

    try:
        numeric = float(value)
    except Exception:
        return str(value)

    return f"{numeric:.{digits}f}"


def build_daily_data_cutoff_notice(now: datetime | None = None) -> str:
    now = now or datetime.now()
    ready_text = A_SHARE_DAILY_DATA_READY_TIME.strftime("%H:%M")
    if now.time() < A_SHARE_DAILY_DATA_READY_TIME:
        return (
            f"行情截止规则：当前未到 {ready_text}，每日更新默认只使用最近一个已完成交易日"
            "（通常是昨天或上一个交易日）的收盘数据，并用它预测下一交易日排名。"
        )
    return (
        f"行情截止规则：当前已到 {ready_text} 之后，每日更新会优先使用今天收盘数据"
        "预测下一交易日；如果今天不是交易日或 Tushare 尚未发布日线，则自动回落到最近可获取的已完成交易日。"
    )


def get_ranking_signal_date_text(ranking_df: pd.DataFrame) -> str:
    if ranking_df is None or ranking_df.empty or "date" not in ranking_df.columns:
        return "未知"

    dates = pd.to_datetime(ranking_df["date"], errors="coerce").dropna()
    if dates.empty:
        return "未知"

    return str(dates.max().date())


def infer_next_trade_date_text(signal_date_text: str) -> str:
    if not signal_date_text or signal_date_text == "未知":
        return "未知"

    try:
        signal_date = pd.to_datetime(signal_date_text)
    except Exception:
        return "未知"

    next_business_day = signal_date + pd.offsets.BDay(1)
    return str(next_business_day.date())


def build_prediction_scope_text(ranking_df: pd.DataFrame) -> tuple[str, str, str]:
    signal_date = get_ranking_signal_date_text(ranking_df)
    prediction_date = infer_next_trade_date_text(signal_date)

    if signal_date == "未知":
        return signal_date, prediction_date, (
            "当前排名文件没有可识别的信号日期；请先重新执行每日更新。"
        )

    return signal_date, prediction_date, (
        f"当前排名的信号日期是 {signal_date}，使用 {signal_date} 收盘后的可用数据生成；"
        f"预测对象是下一交易日 {prediction_date} 的可用排序信号，"
        "回测页面使用 T+1 单日收益评估同一类信号。"
    )


def load_external_model_status(checkpoint_path: str, ranking_df: pd.DataFrame | None = None) -> dict:
    return dashboard_service.load_external_model_status(checkpoint_path, ranking_df)


RANKING_TABLE_COLUMNS = [
    "rank",
    "date",
    "code",
    "name",
    "close",
    "pct_chg",
    "pred_score",
    "raw_score",
    "pred_5d_ret",
    "up_prob",
    "up_prob_calibrated",
    "score",
    "confidence_score",
    "confidence",
    "risk_score",
    "risk_level",
    "model_name",
    "ret_5",
    "ret_20",
    "vol_20",
    "drawdown_20",
]


def run_external_backend_ranking(
    model_backend: str,
    checkpoint_path: str,
    token: str | None = None,
):
    return dashboard_service.run_external_backend_ranking(
        model_backend=model_backend,
        checkpoint_path=checkpoint_path,
        token=token,
    )

def run_external_dft_unet_ranking(checkpoint_path: str, token: str | None = None):
    return run_external_backend_ranking(
        model_backend="dft_unet_external",
        checkpoint_path=checkpoint_path,
        token=token,
    )


st.title(" A股每日股票评分系统")
st.caption(
    "训练与 APP 已分离：初始训练由脚本完成；APP 只读取模型库、触发每日更新并展示下一交易日预测排名。"
)

st.warning(
    "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。"
)
st.info(build_daily_data_cutoff_notice())

selected_strategy = load_selected_strategy()
if selected_strategy:
    st.info(
        "当前默认回测方案："
        f"{selected_strategy.get('model_name', '未知模型')}，"
        f"TopK={selected_strategy.get('topk', '未知')}，"
        f"持有期={selected_strategy.get('holding_days', '未知')}。"
    )

# ============================================================
# 侧边栏：用户
# ============================================================

st.sidebar.header("用户设置")

page_zoom_percent = st.sidebar.slider(
    "页面缩放",
    min_value=80,
    max_value=150,
    value=page_zoom_percent,
    step=5,
    key="page_zoom_percent",
)
if st.sidebar.button("保存页面缩放"):
    local_cfg["page_zoom_percent"] = int(page_zoom_percent)
    save_local_config(local_cfg)
    st.sidebar.success("页面缩放已保存。")

default_current_user_id = str(
    local_cfg.get("current_user_id") or local_cfg.get("user_id") or "default"
).strip() or "default"

current_user_id = st.sidebar.text_input(
    "当前用户 ID",
    value=default_current_user_id,
    help="AI 模拟盘和 AI Agent 会使用该用户的模拟账户、持仓和偏好配置。",
).strip() or "default"

if st.sidebar.button("保存用户 ID"):
    local_cfg["current_user_id"] = current_user_id
    save_local_config(local_cfg)
    st.sidebar.success("用户 ID 已保存。")

# ============================================================
# 侧边栏：Tushare Token
# ============================================================

# ============================================================
# 侧边栏：Tushare Token
# ============================================================

st.sidebar.header("Tushare 连接")

default_token = local_cfg.get("tushare_token") or os.environ.get("TUSHARE_TOKEN", "")

token_input = st.sidebar.text_input(
    "填写 Tushare Token",
    value="",
    type="password",
    placeholder="已配置时可留空；输入新 Token 才会覆盖",
    help="Token 可保存到本地 local_app_config.json，请不要上传到 GitHub。",
)
token = token_input.strip() or default_token
st.sidebar.caption("Token 状态：已配置" if default_token else "Token 状态：未配置")

col_token_1, col_token_2 = st.sidebar.columns(2)

with col_token_1:
    validate_button = st.button("验证连接")

with col_token_2:
    save_token_button = st.button("保存 Token")

if "token_valid" not in st.session_state:
    st.session_state["token_valid"] = False

if "token_message" not in st.session_state:
    st.session_state["token_message"] = ""

if validate_button:
    ok, msg = validate_tushare_token(token)
    st.session_state["token_valid"] = ok
    st.session_state["token_message"] = msg

if save_token_button:
    if token_input.strip():
        local_cfg["tushare_token"] = token_input.strip()
    save_local_config(local_cfg)
    st.sidebar.success("Token 已保存到本地配置。" if token_input.strip() else "未输入新 Token，已保留现有配置。")

if st.session_state["token_message"]:
    if st.session_state["token_valid"]:
        st.sidebar.success(st.session_state["token_message"])
    else:
        st.sidebar.error(st.session_state["token_message"])


# ============================================================
# 侧边栏：AI 接口
# ============================================================

st.sidebar.header("AI 接口设置")
active_llm_settings = resolve_active_llm_settings(local_config=local_cfg)
mode_options = {"远程 API": "api", "本地模型": "local"}
selected_mode_label = st.sidebar.radio(
    "当前模型来源（仅手动切换）",
    options=list(mode_options),
    index=0 if active_llm_settings.mode == "api" else 1,
    horizontal=True,
    key="llm_mode_selector",
)
selected_llm_mode = mode_options[selected_mode_label]
st.sidebar.info(
    f"当前已应用：{'远程 API' if active_llm_settings.mode == 'api' else '本地模型'} / {active_llm_settings.model}"
)
st.sidebar.caption("切换只会在“保存并应用”且验证成功后影响下一次 Agent 运行；不会自动回退到另一种模型。")

candidate_llm_settings = active_llm_settings
if selected_llm_mode == "api":
    default_llm_api_key = local_cfg.get("llm_api_key") or os.environ.get(LLM_API_KEY_ENV, "") or os.environ.get("OPENAI_API_KEY", "")
    api_key_input = st.sidebar.text_input(
        "AI API Key",
        value="",
        type="password",
        placeholder="已配置时可留空；输入新 Key 才会覆盖",
        help="仅用于远程 OpenAI-compatible API；不会写入本地 Ollama 配置。",
    )
    st.sidebar.caption("AI Key 状态：已配置" if default_llm_api_key else "AI Key 状态：未配置")
    api_base_url = st.sidebar.text_input("Base URL", value=str(local_cfg.get("llm_api_base_url") or DEFAULT_LLM_BASE_URL))
    api_model = st.sidebar.text_input("Model", value=str(local_cfg.get("llm_api_model") or DEFAULT_LLM_MODEL))
    candidate_llm_settings = resolve_active_llm_settings(
        local_config={**local_cfg, "llm_mode": "api", "llm_api_base_url": api_base_url, "llm_api_model": api_model},
        mode="api",
        api_key=api_key_input.strip() or None,
        base_url=api_base_url,
        model=api_model,
    )
    verify_button, save_button = st.sidebar.columns(2)
    validate_ai_button = verify_button.button("验证 AI", key="validate_remote_ai")
    save_ai_button = save_button.button("保存并应用", key="save_remote_ai")
    if validate_ai_button:
        ok, message = LLMService(candidate_llm_settings).validate_connection()
        (st.sidebar.success if ok else st.sidebar.error)(message)
    if save_ai_button:
        ok, message = LLMService(candidate_llm_settings).validate_connection()
        if not ok:
            st.sidebar.error(f"保存失败，仍使用原来的模型配置：{message}")
        else:
            if api_key_input.strip():
                local_cfg["llm_api_key"] = api_key_input.strip()
            local_cfg.update({
                "llm_mode": "api",
                "llm_api_base_url": api_base_url.strip(),
                "llm_api_model": api_model.strip(),
                "llm_api_profile_id": candidate_llm_settings.profile_id,
            })
            save_local_config(local_cfg)
            st.sidebar.success("远程 API 配置已验证并应用；本地配置已保留。")
            st.rerun()
else:
    local_base_url = st.sidebar.text_input(
        "本地 Base URL",
        value="http://127.0.0.1:11434/v1",
        disabled=True,
        help="本地模式固定为本机 Ollama 回环地址，不会改为远程 API。",
    )
    status_col, refresh_col = st.sidebar.columns(2)
    if status_col.button("检查 Ollama", key="check_ollama"):
        version = get_ollama_version()
        (st.sidebar.success if version.success else st.sidebar.error)(version.message)
    models_result = list_local_models()
    if refresh_col.button("刷新模型列表", key="refresh_ollama_models"):
        models_result = list_local_models()
    models = list(models_result.data.get("models") or []) if models_result.success else []
    st.sidebar.caption("Ollama 状态：连接正常" if models_result.success else models_result.message)
    local_model = st.sidebar.selectbox(
        "已安装本地模型",
        options=models or [str(local_cfg.get("llm_local_model") or OLLAMA_PROJECT_MODEL)],
        index=0 if not models else (models.index(str(local_cfg.get("llm_local_model") or OLLAMA_PROJECT_MODEL)) if str(local_cfg.get("llm_local_model") or OLLAMA_PROJECT_MODEL) in models else 0),
    )
    st.sidebar.caption(f"推荐模型：{OLLAMA_PROJECT_MODEL}（基础模型：{RECOMMENDED_BASE_MODEL}）")
    install_col, validate_col, apply_col = st.sidebar.columns(3)
    if install_col.button("下载推荐模型", key="install_ollama_model"):
        with st.sidebar.spinner("正在下载并创建本地模型，请勿关闭页面…"):
            pulled = pull_model()
            created = create_project_model(Path("models") / "ollama" / OLLAMA_PROJECT_MODELFILE_NAME) if pulled.success else pulled
        (st.sidebar.success if created.success else st.sidebar.error)(created.message)
    candidate_llm_settings = resolve_active_llm_settings(
        local_config={**local_cfg, "llm_mode": "local", "llm_local_base_url": local_base_url, "llm_local_model": local_model},
        mode="local",
    )
    if validate_col.button("验证本地模型", key="validate_local_ai"):
        ok, message = LLMService(candidate_llm_settings).validate_connection()
        (st.sidebar.success if ok else st.sidebar.error)(message)
    if apply_col.button("保存并应用", key="save_local_ai"):
        ok, message = LLMService(candidate_llm_settings).validate_connection()
        if not ok:
            st.sidebar.error(f"保存失败，仍使用原来的模型配置：{message}")
        else:
            local_cfg.update({
                "llm_mode": "local",
                "llm_local_base_url": local_base_url.strip(),
                "llm_local_model": local_model.strip(),
                "llm_local_disable_thinking": True,
                "llm_local_profile_id": candidate_llm_settings.profile_id,
            })
            save_local_config(local_cfg)
            st.sidebar.success("本地模型配置已验证并应用；远程 API 配置已保留。")
            st.rerun()

active_llm_settings = resolve_active_llm_settings(local_config=local_cfg)
llm_available = active_llm_settings.is_configured


# ============================================================
# 侧边栏：Neo4j 金融事实图
# ============================================================
st.sidebar.divider()
st.sidebar.header("Neo4j 金融事实图")
st.sidebar.caption("GraphRef、实体标识、新闻证据、事实声明和持仓影响路径的唯一权威层。")
neo4j_uri_input = st.sidebar.text_input(
    "Neo4j URI",
    value=str(local_cfg.get("neo4j_uri") or "bolt://127.0.0.1:7687"),
    key="neo4j_uri_input",
)
neo4j_username_input = st.sidebar.text_input(
    "Neo4j Username",
    value=str(local_cfg.get("neo4j_username") or "neo4j"),
    key="neo4j_username_input",
)
neo4j_password_input = st.sidebar.text_input(
    "Neo4j Password",
    value="",
    type="password",
    placeholder="已配置时可留空；输入新密码才会覆盖",
    key="neo4j_password_input",
)
neo4j_database_input = st.sidebar.text_input(
    "Neo4j Database",
    value=str(local_cfg.get("neo4j_database") or "neo4j"),
    key="neo4j_database_input",
)
neo4j_cols = st.sidebar.columns(2)
check_neo4j_button = neo4j_cols[0].button("检查图数据库", key="check_neo4j")
save_neo4j_button = neo4j_cols[1].button("保存图配置", key="save_neo4j")

if save_neo4j_button:
    local_cfg.update({
        "neo4j_uri": neo4j_uri_input.strip(),
        "neo4j_username": neo4j_username_input.strip(),
        "neo4j_database": neo4j_database_input.strip() or "neo4j",
    })
    if neo4j_password_input.strip():
        local_cfg["neo4j_password"] = neo4j_password_input.strip()
    save_local_config(local_cfg)
    st.sidebar.success("Neo4j 配置已保存。")
    st.rerun()

if check_neo4j_button:
    check_local_cfg = dict(local_cfg)
    check_local_cfg.update({
        "neo4j_uri": neo4j_uri_input.strip(),
        "neo4j_username": neo4j_username_input.strip(),
        "neo4j_database": neo4j_database_input.strip() or "neo4j",
    })
    if neo4j_password_input.strip():
        check_local_cfg["neo4j_password"] = neo4j_password_input.strip()
    try:
        graph_result = dashboard_service.test_neo4j_connection(check_local_cfg)
        st.sidebar.success(
            f"Neo4j 连接正常，当前节点数：{int(graph_result.get('node_count') or 0)}"
        )
    except Exception as exc:
        st.sidebar.error(f"Neo4j 不可用：{type(exc).__name__}: {exc}")


# ============================================================
# Sidebar: MCP read-only evidence tools
# ============================================================

st.sidebar.divider()
st.sidebar.header("MCP Evidence Tools")
st.sidebar.caption("Read-only financial evidence for Agent planning; write tools are blocked.")
mcp_example_enabled = st.sidebar.checkbox(
    "Enable local read-only MCP example",
    value=bool(local_cfg.get("mcp_example_enabled", False)),
)
mcp_cols = st.sidebar.columns(2)
with mcp_cols[0]:
    save_mcp_button = st.button("Save MCP")
with mcp_cols[1]:
    check_mcp_button = st.button("Check MCP")

if save_mcp_button:
    local_cfg["mcp_example_enabled"] = bool(mcp_example_enabled)
    local_cfg["mcp_example_allowed_tools"] = ["market_risk_summary"]
    local_cfg["mcp_example_timeout_seconds"] = float(local_cfg.get("mcp_example_timeout_seconds") or 5.0)
    save_local_config(local_cfg)
    reset_discovery_cache()
    st.sidebar.success("MCP settings saved.")

if check_mcp_button:
    check_cfg = dict(local_cfg)
    check_cfg["mcp_example_enabled"] = bool(mcp_example_enabled)
    mcp_context = {"mcp": build_mcp_context_from_local_config(check_cfg)}
    results = discover_mcp_tools(mcp_context, force=True)
    usable_tools = [
        tool.to_dict()
        for result in results
        for tool in result.tools
        if tool.mapped
    ]
    if usable_tools:
        st.sidebar.success(f"MCP discovery OK: {len(usable_tools)} read-only tool(s).")
    else:
        st.sidebar.info("No enabled MCP read-only tool is currently available.")
    with st.sidebar.expander("MCP discovery details", expanded=True):
        st.json({
            "sdk_version": mcp_sdk_version(),
            "servers": [result.to_dict() for result in results],
        })


# ============================================================
# 侧边栏：模型库
# ============================================================

st.sidebar.header("模型库管理")
st.sidebar.caption("只管理本地模型文件、模型库选择和依赖状态；不会拉取行情，也不会刷新排名或模拟盘。")

backend_labels = {
    "DFT_UNET": "dft_unet_external",
}
downloaded_backend_labels = downloaded_zoo_backends()
backend_labels.update(downloaded_backend_labels or registered_zoo_backends())
default_backend_value = local_cfg.get("model_backend", "zoo:chronos_bolt_small")
if default_backend_value not in set(backend_labels.values()):
    default_backend_value = "zoo:chronos_bolt_small"
default_backend_label = next(
    (label for label, value in backend_labels.items() if value == default_backend_value),
    next((label for label, value in backend_labels.items() if value == "zoo:chronos_bolt_small"), next(iter(backend_labels))),
)

selected_backend_label = st.sidebar.selectbox(
    "选择模型",
    options=list(backend_labels.keys()),
    index=list(backend_labels.keys()).index(default_backend_label),
)
selected_backend = backend_labels[selected_backend_label]

selected_version = "latest"
refresh_button = False
zoo_table = load_model_zoo_table()
dft_checkpoint_path = (
    local_cfg.get("dft_unet_checkpoint_path")
    or DEFAULT_DFT_UNET_CHECKPOINT_PATH
)

if selected_backend == "dft_unet_external":
    dft_checkpoint_path = st.sidebar.text_input(
        "DFT_UNET checkpoint 路径",
        value=dft_checkpoint_path,
    )
elif is_zoo_backend(selected_backend):
    selected_model_name = zoo_model_name_from_backend(selected_backend)
    selected_row = pd.DataFrame()
    if not zoo_table.empty and "name" in zoo_table.columns:
        selected_row = zoo_table[zoo_table["name"].astype(str) == selected_model_name].tail(1)
    if selected_row.empty:
        st.sidebar.info("当前选择的是模型库模型；未找到 metadata 时，运行预测会给出具体原因。")
    else:
        selected_status = str(selected_row.iloc[0].get("status", "registered"))
        st.sidebar.caption(f"模型状态：{selected_status}")

save_model_settings_button = st.sidebar.button("保存模型选择")
check_model_button = st.sidebar.button("检查模型文件/依赖")

st.sidebar.divider()
st.sidebar.header("手动生成预测排名")
st.sidebar.caption("拉取最新行情并重写 outputs/ranking_latest.csv；不会执行 AI 模拟盘。")
refresh_button = st.sidebar.button(
    "每日更新并生成预测排名",
    type="primary",
)

if save_model_settings_button:
    local_cfg["model_backend"] = selected_backend
    local_cfg["dft_unet_checkpoint_path"] = dft_checkpoint_path
    save_local_config(local_cfg)
    st.sidebar.success("模型库设置已保存。")

if check_model_button:
    try:
        inspection = dashboard_service.inspect_model(
            selected_backend,
            dft_checkpoint_path,
            zoo_table,
        )
        if inspection.get("kind") == "dft_unet_external":
            report = inspection.get("report") or {}
            st.sidebar.success("DFT_UNET checkpoint 可读取，模型结构已识别并加载。")
            with st.sidebar.expander("模型检查结果", expanded=True):
                st.json({
                    "ok": report.get("ok"),
                    "checkpoint_type": report.get("checkpoint_type"),
                    "checkpoint_keys": report.get("checkpoint_keys", [])[:20],
                    "state_dict_first_20_keys": report.get("state_dict_first_20_keys", []),
                    "model_name": report.get("experiment_model_name"),
                    "best_epoch": report.get("best_epoch"),
                    "best_score": report.get("best_score"),
                    "input_spec": report.get("input_spec"),
                    "load_report": inspection.get("load_report") or {},
                })
        elif inspection.get("metadata") is None:
            st.sidebar.warning("没有找到该模型的 metadata。")
        else:
            st.sidebar.success("模型 metadata 可读取。")
            with st.sidebar.expander("模型检查结果", expanded=True):
                st.json(inspection.get("metadata"))
    except Exception as exc:
        st.sidebar.error(f"模型检查失败：{exc}")


# ============================================================
# 侧边栏：每日自动更新
# ============================================================

with st.sidebar.expander("查看模型库"):
    zoo_model_names = list_model_names()
    st.caption("所有注册模型都会出现在上方模型库下拉框中；未下载或缺少依赖时，运行预测会给出明确提示。")
    st.write("注册模型：", ", ".join(zoo_model_names))
    if zoo_table.empty:
        st.write("暂无模型库 metadata。")
    else:
        show_zoo_cols = [
            c
            for c in ["name", "provider", "status", "license", "file_format", "local_path"]
            if c in zoo_table.columns
        ]
        st.dataframe(zoo_table[show_zoo_cols], width="stretch")

st.sidebar.caption(
    "模型下载示例：python -m model_zoo.downloader --model chronos_bolt_small。"
)

st.sidebar.divider()
st.sidebar.header("每日自动任务")
st.sidebar.caption("只配置定时运行“每日更新并生成预测排名”；不会立即执行，也不会更新模拟盘。")
st.sidebar.info(build_daily_data_cutoff_notice())

auto_enabled = st.sidebar.checkbox(
    "开启定时预测排名更新",
    value=bool(local_cfg.get("auto_retrain_enabled", False)),
)

default_hour = int(local_cfg.get("auto_retrain_hour", 20))
default_minute = int(local_cfg.get("auto_retrain_minute", 0))

auto_time = st.sidebar.time_input(
    "定时运行时间",
    value=datetime_time(hour=default_hour, minute=default_minute),
)

save_auto_config_button = st.sidebar.button("保存定时任务设置")

if save_auto_config_button:
    local_cfg["tushare_token"] = token
    local_cfg["auto_retrain_enabled"] = auto_enabled
    local_cfg["auto_retrain_hour"] = auto_time.hour
    local_cfg["auto_retrain_minute"] = auto_time.minute
    local_cfg["model_version"] = selected_version
    local_cfg["model_backend"] = selected_backend
    local_cfg["dft_unet_checkpoint_path"] = dft_checkpoint_path

    save_local_config(local_cfg)

    set_daily_retrain_job(
        scheduler=scheduler,
        token=token,
        hour=auto_time.hour,
        minute=auto_time.minute,
        enabled=auto_enabled,
        model_backend=selected_backend,
        checkpoint_path=dft_checkpoint_path,
    )

    if auto_enabled:
        st.sidebar.success(f"已开启定时预测排名更新：{auto_time.strftime('%H:%M')}")
    else:
        st.sidebar.info("已关闭定时预测排名更新。")


# 每次 APP 刷新时，根据本地配置恢复调度任务
if local_cfg.get("auto_retrain_enabled", False) and local_cfg.get("tushare_token"):
    set_daily_retrain_job(
        scheduler=scheduler,
        token=local_cfg.get("tushare_token"),
        hour=int(local_cfg.get("auto_retrain_hour", 20)),
        minute=int(local_cfg.get("auto_retrain_minute", 0)),
        enabled=True,
        model_backend=local_cfg.get("model_backend", "zoo:chronos_bolt_small"),
        checkpoint_path=local_cfg.get("dft_unet_checkpoint_path") or DEFAULT_DFT_UNET_CHECKPOINT_PATH,
    )


manual_retrain_button = st.sidebar.button("立即运行一次定时更新流程")

if manual_retrain_button:
    if not token:
        st.error("请先填写 Tushare Token。")
    else:
        st.subheader("每日更新进度")
        ok, error_text = run_rolling_update_with_time_progress(
            token=token,
            base_version=selected_version,
            model_backend=selected_backend,
            checkpoint_path=dft_checkpoint_path,
            default_estimate_seconds=300,
        )
        if ok:
            st.success("定时更新流程执行完成，预测下一交易日排名已刷新。")
            time.sleep(1)
            st.rerun()
        else:
            st.error("定时更新流程执行失败。")
            if error_text:
                with st.expander("查看错误摘要"):
                    st.code(error_text)


with st.sidebar.expander("查看自动任务状态"):
    jobs = get_scheduler_jobs(scheduler)

    if jobs:
        st.write(jobs)
    else:
        st.write("当前没有启用自动更新任务。")

with st.sidebar.expander("查看自动更新日志"):
    log_text = read_auto_retrain_log()

    if log_text:
        st.code(log_text)
    else:
        st.write("暂无日志。")

# ============================================================
# 刷新预测
# ============================================================

if refresh_button:
    if not token:
        st.error("请先填写 Tushare Token。")
    else:
        st.subheader("每日更新进度")

        ok, error_text = run_rolling_update_with_time_progress(
            token=token,
            base_version=selected_version,
            model_backend=selected_backend,
            checkpoint_path=dft_checkpoint_path,
            default_estimate_seconds=300,
        )

        if ok:
            st.success("每日更新完成，预测下一交易日排名已刷新。")
            time.sleep(1)
            st.rerun()
        else:
            st.error("每日更新失败。")
            if error_text:
                with st.expander("查看错误摘要"):
                    st.code(error_text)

# ============================================================
# Page navigation dispatch
# ============================================================
selected_top_level_page = render_top_level_page_selector()
if selected_top_level_page == "AI 模拟盘":
    try:
        _get_ai_paper_trading_page_renderer()(
            user_id=current_user_id,
            output_dir=OUTPUT_DIR,
            db_path=AGENT_QUANT_DB_PATH,
            top_k=10,
        )
        st.stop()
    except (ImportError, Exception) as _page_err:
        st.warning(f"AI 模拟盘页面暂不可用: {_page_err}")
        st.stop()
if selected_top_level_page == "AI Agent":
    _get_ai_agent_page_renderer()(
        user_id=current_user_id,
        output_dir=OUTPUT_DIR,
        db_path=AGENT_QUANT_DB_PATH,
        default_topk=10,
        ranking=None,
        llm_settings=active_llm_settings,
    )
    st.stop()
if selected_top_level_page == "系统监控":
    _get_system_monitor_page_renderer()(
        user_id=current_user_id,
        output_dir=OUTPUT_DIR,
        db_path=AGENT_QUANT_DB_PATH,
    )
    st.stop()


# ============================================================
# 加载首页结果
# ============================================================


ranking = load_ranking()


metrics = load_selected_model_metrics(selected_backend)

if ranking is None:
    st.error(
        """
        当前还没有 ranking_latest.csv。

        请先完成两步：

        1. 选择模型：
        左侧选择模型版本

        2. 在 APP 中填写 Tushare Token，点击“每日更新并生成预测排名”。
        """
    )
    st.stop()

# ============================================================
# 一、模型状态
# ============================================================

st.sidebar.header("排名展示设置")

topk_option = st.sidebar.selectbox(
    "选择展示 TopK",
    options=[10, 20, 30, 50, 100, 300, "全部"],
    index=3,
)

if topk_option == "全部":
    ranking_display_source = ranking.copy()
else:
    ranking_display_source = ranking.head(int(topk_option)).copy()

signal_date_text, prediction_date_text, prediction_scope_text = build_prediction_scope_text(ranking)

ranking_model_names = []
if "model_name" in ranking.columns:
    ranking_model_names = ranking["model_name"].dropna().astype(str).unique().tolist()

if selected_backend == "dft_unet_external":
    expected_ranking_model_names = {"dft_unet_external", "dft_unet", "DFT_UNET"}
elif is_zoo_backend(selected_backend):
    expected_ranking_model_names = {zoo_model_name_from_backend(selected_backend)}
else:
    expected_ranking_model_names = set()

ranking_matches_selected_model = (
    not expected_ranking_model_names
    or not ranking_model_names
    or bool(expected_ranking_model_names & set(ranking_model_names))
)

col9, col10, col11, col12, col13, col14 = st.columns(6)

col9.metric("当前 Universe", UNIVERSE.upper())
col10.metric("当前模型", selected_backend_label)
col11.metric("信号日期", signal_date_text)
col12.metric("预测交易日", prediction_date_text)
col13.metric("当前预测股票数", len(ranking))
col14.metric("当前展示数量", len(ranking_display_source))

if not ranking_matches_selected_model:
    st.warning(
        "当前预测排名文件来自其他模型："
        f"{', '.join(ranking_model_names)}；当前选择：{selected_backend_label}。"
        "请点击“每日更新并生成预测排名”生成当前模型的结果。"
    )


HOME_SECTION_LABELS = [
    "\u9996\u9875 / \u9884\u6d4b\u6392\u540d",
    "\u4e2a\u80a1\u8be6\u60c5",
    "\u6a21\u578b\u6307\u6807",
    "\u6a21\u578b\u641c\u7d22\u4e0e\u56de\u6d4b",
    "\u56de\u6d4b\u5206\u6790",
    "\u65b0\u95fb\u4e8b\u4ef6",
    "\u7cfb\u7edf\u8bbe\u7f6e",
]
if st.session_state.get("home_section") not in HOME_SECTION_LABELS:
    st.session_state["home_section"] = HOME_SECTION_LABELS[0]
selected_home_section = st.radio(
    "\u9996\u9875\u6a21\u5757",
    options=HOME_SECTION_LABELS,
    horizontal=True,
    key="home_section",
)

if selected_home_section == "\u6a21\u578b\u6307\u6807":
    st.subheader("一、模型与数据状态")

    if selected_backend == "dft_unet_external":
        external_status = load_external_model_status(
            checkpoint_path=dft_checkpoint_path,
            ranking_df=ranking,
        )

        st.caption("当前页面展示的是所选 DFT_UNET 模型状态；不会混入其它模型指标。")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("模型名称", external_status.get("model_name", "DFT_UNET"))
        col2.metric("模型", selected_backend_label)
        col3.metric("输入维度", external_status.get("input_shape", "[N, 8, 221]"))
        col4.metric("排名股票数", external_status.get("ranking_rows", 0))

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("Best Epoch", external_status.get("best_epoch", "N/A"))
        col6.metric("Best Score", format_metric_float(external_status.get("best_score"), digits=4))
        col7.metric("股票因子数", external_status.get("stock_feature_count", 158))
        col8.metric("市场指标数", external_status.get("market_context_count", 63))

        col9, col10, col11, col12 = st.columns(4)
        col9.metric("预测信号日期", external_status.get("ranking_date", "未知"))
        col10.metric(
            "市场指标缓存",
            "已生成" if external_status["market_context_cache"].get("exists") else "未生成",
        )
        col11.metric(
            "指数日线缓存",
            "已生成" if external_status["market_index_cache"].get("exists") else "未生成",
        )
        col12.metric(
            "Checkpoint",
            "已找到" if external_status.get("checkpoint_exists") else "缺失",
        )

        cache_rows = [
            {
                "项目": "三个指数日线",
                "状态": "已生成" if external_status["market_index_cache"].get("exists") else "未生成",
                "行数": external_status["market_index_cache"].get("rows", 0),
                "日期范围": (
                    f"{external_status['market_index_cache'].get('date_min', '')} ~ "
                    f"{external_status['market_index_cache'].get('date_max', '')}"
                ),
                "路径": external_status["market_index_cache"].get("path", ""),
            },
            {
                "项目": "DFT_UNET 市场指标",
                "状态": "已生成" if external_status["market_context_cache"].get("exists") else "未生成",
                "行数": external_status["market_context_cache"].get("rows", 0),
                "日期范围": (
                    f"{external_status['market_context_cache'].get('date_min', '')} ~ "
                    f"{external_status['market_context_cache'].get('date_max', '')}"
                ),
                "路径": external_status["market_context_cache"].get("path", ""),
            },
        ]
        st.dataframe(pd.DataFrame(cache_rows), width="stretch")

        with st.expander("查看模型配置摘要"):
            st.json(external_status)

    elif is_zoo_backend(selected_backend):
        zoo_model_name = zoo_model_name_from_backend(selected_backend)
        zoo_row = pd.DataFrame()
        if not zoo_table.empty and "name" in zoo_table.columns:
            zoo_row = zoo_table[zoo_table["name"].astype(str) == zoo_model_name].tail(1)
        zoo_info = zoo_row.iloc[0].to_dict() if not zoo_row.empty else {}
        status_text = metrics.get("status") or zoo_info.get("status") or "未知"

        st.caption("当前页面展示的是所选 Model Zoo 模型状态；未下载或缺少依赖时，每日更新会给出明确错误。")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("模型名称", zoo_model_name)
        col2.metric("模型", selected_backend_label)
        col3.metric("状态", status_text)
        col4.metric("排名股票数", metrics.get("ranking_rows", "暂无"))

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("Provider", zoo_info.get("provider", "未知"))
        col6.metric("Family", zoo_info.get("family", "未知"))
        col7.metric("文件格式", zoo_info.get("file_format", "未知"))
        col8.metric("更新时间", metrics.get("update_time", zoo_info.get("updated_at", "未知")))

        with st.expander("查看模型指标 / metadata"):
            detail = dict(zoo_info)
            if metrics:
                detail.update(metrics)
            st.json(detail)

    elif metrics:
        col1, col2, col3, col4 = st.columns(4)

        col1.metric("模型名称", metrics.get("model_name", "未知"))
        col2.metric("训练设备", metrics.get("device", "未知"))
        col3.metric("特征数量", metrics.get("feature_count", "未知"))

        auc_value = metrics.get("auc")
        col4.metric("测试集 AUC", f"{auc_value:.3f}" if auc_value is not None else "N/A")

        col5, col6, col7, col8 = st.columns(4)

        col5.metric("训练数据最新日期", metrics.get("latest_data_date", "未知"))
        col6.metric("训练样本数", metrics.get("train_samples", "未知"))

        ic_value = metrics.get("ic_mean")
        col7.metric("测试集 IC", f"{ic_value:.4f}" if ic_value is not None else "N/A")

        rankic_value = metrics.get("rankic_mean")
        col8.metric("测试集 RankIC", f"{rankic_value:.4f}" if rankic_value is not None else "N/A")

        with st.expander("查看完整模型指标"):
            st.json({
                "model_name": metrics.get("model_name"),
                "feature_type": metrics.get("feature_type"),
                "feature_count": metrics.get("feature_count"),
                "split_date": metrics.get("split_date"),
                "train_samples": metrics.get("train_samples"),
                "test_samples": metrics.get("test_samples"),
                "rmse": metrics.get("rmse"),
                "accuracy": metrics.get("accuracy"),
                "auc": metrics.get("auc"),
                "best_valid_loss": metrics.get("best_valid_loss"),
                "device": metrics.get("device"),
                "ic_mean": metrics.get("ic_mean"),
                "icir": metrics.get("icir"),
                "rankic_mean": metrics.get("rankic_mean"),
                "rankicir": metrics.get("rankicir"),
                "top5_mean_ret": metrics.get("top5_mean_ret"),
                "top10_mean_ret": metrics.get("top10_mean_ret"),
            })
    else:
        st.warning("没有找到模型指标文件。")

    # ============================================================
    # 二、预测排名
    # ============================================================


if selected_home_section == "\u6a21\u578b\u641c\u7d22\u4e0e\u56de\u6d4b":
    _get_model_search_page_renderer()()

if selected_home_section == "\u9996\u9875 / \u9884\u6d4b\u6392\u540d":
    st.subheader("二、预测下一交易日股票排名")
    st.caption(prediction_scope_text)

    home_selected_strategy = load_selected_strategy()
    if home_selected_strategy:
        with st.expander("默认模型搜索方案", expanded=True):
            st.write(
                f"{home_selected_strategy.get('model_name', '未知模型')} ｜ "
                f"TopK={home_selected_strategy.get('topk', '未知')} ｜ "
                f"持有期={home_selected_strategy.get('holding_days', '未知')} ｜ "
                f"排序字段={home_selected_strategy.get('rank_by', 'score')}"
            )
            st.caption(BACKTEST_DISCLAIMER)
            strategy_returns = load_daily_returns_for_strategy(home_selected_strategy)
            if not strategy_returns.empty:
                latest_strategy_row = strategy_returns.tail(1).iloc[0]
                strategy_col1, strategy_col2, strategy_col3 = st.columns(3)
                strategy_col1.metric("历史区间天数", len(strategy_returns))
                strategy_col2.metric("最新 NAV", format_metric_float(latest_strategy_row.get("nav"), digits=4))
                strategy_col3.metric("累计收益", format_metric_float(latest_strategy_row.get("cum_return"), digits=4))
                fig_home_strategy_nav = px.line(
                    strategy_returns,
                    x="date",
                    y="nav" if "nav" in strategy_returns.columns else "cum_return",
                    title="默认方案历史净值曲线",
                )
                st.plotly_chart(fig_home_strategy_nav, width="stretch")
            else:
                st.info("默认方案的每日收益文件暂不可读取。")

    display_df = ranking_display_source.copy()
    display_cols = [col for col in RANKING_TABLE_COLUMNS if col in display_df.columns]
    display_df = display_df[display_cols].copy()

    percent_cols = [
        "up_prob",
        "up_prob_calibrated",
        "ret_5",
        "ret_20",
        "vol_20",
        "drawdown_20",
    ]

    display_df = format_percent_columns(display_df, percent_cols)

    if "pct_chg" in display_df.columns:
        display_df["pct_chg"] = display_df["pct_chg"].map(format_tushare_pct_chg)

    for col in ["pred_score", "raw_score", "score", "risk_score", "confidence_score"]:
        if col in display_df.columns:
            display_df[col] = display_df[col].map(
                lambda x: f"{x:.3f}" if pd.notna(x) else ""
            )

    display_df = display_df.rename(columns={
        "rank": "排名",
        "date": "日期",
        "code": "股票代码",
        "name": "股票名称",
        "close": "收盘价",
        "pct_chg": "当日涨跌",
        "pred_score": "模型分数",
        "raw_score": "原始分数",
        "pred_5d_ret": "预测分数",
        "up_prob": "上涨概率",
        "up_prob_calibrated": "校准上涨概率",
        "score": "排名分位",
        "confidence_score": "可信度分数",
        "confidence": "可信度",
        "risk_score": "风险分数",
        "risk_level": "风险等级",
        "model_name": "使用模型",
        "ret_5": "近5日收益",
        "ret_20": "近20日收益",
        "vol_20": "近20日波动率",
        "drawdown_20": "近20日回撤",
        "recent_news_count_1d": "当日新闻数",
        "recent_news_count_3d": "近3日新闻数",
        "recent_news_count_5d": "近5日新闻数",
        "positive_event_count_5d": "近5日正面事件",
        "negative_event_count_5d": "近5日负面事件",
        "risk_event_count_5d": "近5日风险事件",
        "has_earnings_positive": "业绩正面",
        "has_earnings_negative": "业绩负面",
        "has_shareholder_reduce": "股东减持",
        "has_shareholder_increase": "股东增持",
        "has_lawsuit": "诉讼仲裁",
        "has_penalty": "处罚监管",
        "has_merger": "并购重组",
        "has_buyback": "回购",
        "has_contract_win": "中标合同",
    })

    st.dataframe(display_df, width="stretch")

    # ============================================================
    # 三、图表
    # ============================================================

    st.subheader("三、综合评分图")

    signal_col = "pred_score" if "pred_score" in ranking_display_source.columns else "score"
    score_hover_cols = [
        c for c in [
            "code",
            "pred_score",
            "raw_score",
            "score",
            "up_prob",
            "up_prob_calibrated",
            "confidence_score",
            "confidence",
            "risk_score",
            "risk_level",
            "model_name",
            "recent_news_count_5d",
            "positive_event_count_5d",
            "negative_event_count_5d",
            "risk_event_count_5d",
        ]
        if c in ranking_display_source.columns
    ]

    fig_score = px.bar(
        ranking_display_source,
        x="name",
        y=signal_col,
        hover_data=score_hover_cols,
        title="预测下一交易日股票模型分数"
    )
    st.plotly_chart(fig_score, width="stretch")

    st.subheader("四、模型分数与上涨概率")

    fig_scatter = px.scatter(
        ranking_display_source,
        x="up_prob",
        y=signal_col,
        size="score",
        color="risk_level",
        hover_name="name",
        hover_data=[
            "code",
            "confidence",
            "ret_5",
            "ret_20",
            "vol_20",
            "drawdown_20",
        ],
        title="模型分数 vs 上涨概率"
    )
    st.plotly_chart(fig_scatter, width="stretch")

    # ============================================================
    # 四、个股走势
    # ============================================================

if selected_home_section == "\u4e2a\u80a1\u8be6\u60c5":
    st.subheader("五、个股走势查看")

    raw_data = dashboard_service.load_latest_raw_data()
    if not raw_data.empty:

        selected_name = st.selectbox("选择股票", ranking["name"].tolist())

        selected_code = ranking.loc[ranking["name"] == selected_name, "code"].iloc[0]
        selected_code = str(selected_code).zfill(6)

        stock_hist = raw_data[raw_data["code"] == selected_code].copy()

        if not stock_hist.empty:
            fig_line = px.line(
                stock_hist,
                x="date",
                y="close",
                title=f"{selected_name} 收盘价走势"
            )
            st.plotly_chart(fig_line, width="stretch")

            latest_info = ranking[ranking["code"] == selected_code].iloc[0]
            latest_signal_col = (
                "pred_score" if "pred_score" in latest_info.index else "score"
            )

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("模型分数", f"{latest_info[latest_signal_col]:.3f}")
            col2.metric("上涨概率", f"{latest_info['up_prob']:.2%}")
            col3.metric("可信度", latest_info["confidence"])
            col4.metric("风险等级", latest_info["risk_level"])

            score_col1, score_col2, score_col3 = st.columns(3)
            score_col1.metric(
                "校准上涨概率",
                f"{latest_info.get('up_prob_calibrated', latest_info['up_prob']):.2%}"
                if pd.notna(latest_info.get("up_prob_calibrated", latest_info["up_prob"]))
                else "N/A",
            )
            score_col2.metric(
                "可信度分数",
                f"{latest_info.get('confidence_score', 0):.3f}"
                if pd.notna(latest_info.get("confidence_score"))
                else "N/A",
            )
            score_col3.metric(
                "风险分数",
                f"{latest_info.get('risk_score', 0):.3f}"
                if pd.notna(latest_info.get("risk_score"))
                else "N/A",
            )

            st.markdown("#### 量化因子表现")
            factor_col1, factor_col2, factor_col3, factor_col4 = st.columns(4)
            factor_col1.metric(
                "近5日收益",
                f"{latest_info.get('ret_5', 0):.2%}"
                if pd.notna(latest_info.get("ret_5"))
                else "N/A",
            )
            factor_col2.metric(
                "近20日收益",
                f"{latest_info.get('ret_20', 0):.2%}"
                if pd.notna(latest_info.get("ret_20"))
                else "N/A",
            )
            factor_col3.metric(
                "近20日波动率",
                f"{latest_info.get('vol_20', 0):.2%}"
                if pd.notna(latest_info.get("vol_20"))
                else "N/A",
            )
            factor_col4.metric(
                "近20日回撤",
                f"{latest_info.get('drawdown_20', 0):.2%}"
                if pd.notna(latest_info.get("drawdown_20"))
                else "N/A",
            )

            event_factor_cols = [
                "recent_news_count_1d",
                "recent_news_count_3d",
                "recent_news_count_5d",
                "positive_event_count_5d",
                "negative_event_count_5d",
                "risk_event_count_5d",
            ]

            if any(col in latest_info.index for col in event_factor_cols):
                event_factor_df = pd.DataFrame(
                    [
                        {
                            "指标": "当日新闻/公告",
                            "数值": latest_info.get("recent_news_count_1d", 0),
                        },
                        {
                            "指标": "近3日新闻/公告",
                            "数值": latest_info.get("recent_news_count_3d", 0),
                        },
                        {
                            "指标": "近5日新闻/公告",
                            "数值": latest_info.get("recent_news_count_5d", 0),
                        },
                        {
                            "指标": "近5日正面事件",
                            "数值": latest_info.get("positive_event_count_5d", 0),
                        },
                        {
                            "指标": "近5日负面事件",
                            "数值": latest_info.get("negative_event_count_5d", 0),
                        },
                        {
                            "指标": "近5日风险事件",
                            "数值": latest_info.get("risk_event_count_5d", 0),
                        },
                    ]
                )
                event_factor_df["数值"] = pd.to_numeric(
                    event_factor_df["数值"],
                    errors="coerce",
                ).fillna(0).astype(int)
                st.dataframe(event_factor_df, width="stretch")

            if ENABLE_NEWS_FEATURES:
                st.markdown("#### 最近新闻/公告")
                events = load_news_events_for_app()

                if not events.empty:
                    stock_events = events[events["code"] == selected_code].copy()
                    stock_events = stock_events.sort_values(
                        ["publish_time", "date"],
                        ascending=False,
                    ).head(10)

                    if not stock_events.empty:
                        show_events = stock_events[["date", "title", "source"]].copy()
                        show_events["date"] = show_events["date"].dt.strftime("%Y-%m-%d")
                        show_events = show_events.rename(
                            columns={
                                "date": "日期",
                                "title": "标题",
                                "source": "来源",
                            }
                        )
                        st.dataframe(show_events, width="stretch")
                    else:
                        st.info("暂无该股票新闻/公告缓存。")
                else:
                    st.info("暂无新闻/公告缓存。")

                st.markdown("#### 相关新闻/公告检索")
                rag_query = st.text_input(
                    "检索问题",
                    value="近期有什么风险？",
                    key=f"rag_query_{selected_code}",
                )
                rag_top_k = st.selectbox(
                    "检索条数",
                    options=[3, 5, 10],
                    index=1,
                    key=f"rag_top_k_{selected_code}",
                )
                rag_state_key = f"rag_results_{selected_code}"

                if st.button("检索资料", key=f"rag_search_{selected_code}"):
                    try:
                        rag_results = cached_retrieve_stock_context(
                            code=selected_code,
                            query=rag_query,
                            top_k=int(rag_top_k),
                        )
                        st.session_state[rag_state_key] = rag_results

                        if rag_results.empty:
                            st.info("没有检索到该股票的相关资料。")
                        else:
                            show_rag = rag_results.copy()
                            show_rag["score"] = show_rag["score"].map(lambda x: f"{x:.3f}")
                            show_rag = show_rag.rename(
                                columns={
                                    "date": "日期",
                                    "title": "标题",
                                    "source": "来源",
                                    "url": "链接",
                                    "score": "匹配度",
                                    "content": "内容",
                                }
                            )
                            st.dataframe(show_rag, width="stretch")
                    except Exception as e:
                        st.error(f"资料检索失败：{e}")

                st.markdown("#### 生成 AI 解释")
                st.caption("调用已配置的 OpenAI-compatible 接口；解释仅用于机器学习和数据分析展示。")

                cached_explanation = load_cached_ai_explanation(latest_info)

                if cached_explanation:
                    with st.expander("查看上次 AI 解释缓存"):
                        st.markdown(cached_explanation)

                rag_results_for_prompt = st.session_state.get(rag_state_key)

                if rag_results_for_prompt is None:
                    rag_results_for_prompt = pd.DataFrame()

                risk_detail_for_prompt = {
                    "risk_detail": parse_detail_json(latest_info.get("risk_detail")),
                    "confidence_detail": parse_detail_json(latest_info.get("confidence_detail")),
                }
                prompt_state_key = f"editable_prompt_{selected_code}"

                if st.button("生成 Prompt", key=f"generate_prompt_{selected_code}"):
                    if rag_results_for_prompt.empty and ENABLE_RAG:
                        try:
                            rag_results_for_prompt = cached_retrieve_stock_context(
                                code=selected_code,
                                query=rag_query,
                                top_k=int(rag_top_k),
                            )
                            st.session_state[rag_state_key] = rag_results_for_prompt
                        except Exception as e:
                            st.warning(f"RAG data is unavailable in this runtime: {e}")
                            rag_results_for_prompt = pd.DataFrame()

                    st.session_state[prompt_state_key] = build_stock_explanation_prompt(
                        ranking_row=latest_info,
                        rag_results=rag_results_for_prompt,
                        model_metrics=metrics,
                        risk_detail=risk_detail_for_prompt,
                    )

                if prompt_state_key not in st.session_state:
                    st.session_state[prompt_state_key] = ""

                st.text_area(
                    "可编辑 Prompt",
                    height=420,
                    key=prompt_state_key,
                    placeholder="请先点击“生成 Prompt”，也可以直接在这里填写或修改 Prompt。",
                )

                if st.button("AI 解释", key=f"explain_ai_{selected_code}"):
                    if not llm_available:
                        st.error("请先在左侧 AI 接口设置中配置并验证模型。")
                    elif not str(st.session_state.get(prompt_state_key, "")).strip():
                        st.error("请先点击“生成 Prompt”，或在 Prompt 文本框中填写内容。")
                    else:
                        explanation = explain_prompt_with_llm(
                            stock_row=latest_info.to_dict(),
                            prompt_text=st.session_state.get(prompt_state_key, ""),
                            llm_settings=active_llm_settings,
                        )

                        if explanation.startswith("AI 解释生成失败"):
                            st.error(explanation)
                        else:
                            st.success("AI 解释已生成并缓存到本地。")
                            st.markdown(explanation)

        else:
            st.warning("没有找到该股票历史数据。")
    else:
        st.info("暂无最新原始行情数据。请先点击每日更新生成预测排名。")

    # ============================================================
    # 六、基础回测分析
    # ============================================================

if selected_home_section == "\u56de\u6d4b\u5206\u6790":
    st.subheader("六、基础 T+1 回测分析")
    st.warning(
        "本回测仅用于模型评估和项目展示，不构成投资建议，不用于实盘交易。"
    )
    st.info(
        "点击回测后，APP 会先检查本地最近行情；如果不足 60 个可回测交易日，会自动使用 Tushare 下载最近行情后再回测。"
    )

    bt_col1, bt_col2, bt_col3, bt_col4 = st.columns(4)

    with bt_col1:
        backtest_topk = st.selectbox(
            "回测 TopK",
            options=[10, 20, 30, 50],
            index=0,
        )

    with bt_col2:
        backtest_days = st.number_input(
            "回测天数",
            min_value=60,
            max_value=180,
            value=60,
            step=10,
        )

    with bt_col3:
        backtest_cost = st.number_input(
            "单边成本",
            min_value=0.0,
            max_value=0.01,
            value=0.0003,
            step=0.0001,
            format="%.4f",
        )

    with bt_col4:
        st.metric("回测模型", selected_backend_label)
        st.caption(selected_backend)

    run_backtest_button = st.button("检查数据并运行 T+1 回测")

    if run_backtest_button:
        try:
            with st.spinner("正在检查本地行情；如数据不足会自动联网下载，然后运行 T+1 回测..."):
                run_latest_t1_backtest(
                    token=token or None,
                    model_version=selected_version,
                    model_backend=selected_backend,
                    checkpoint_path=dft_checkpoint_path,
                    topk=int(backtest_topk),
                    backtest_days=int(backtest_days),
                    fetch_trade_days=max(int(backtest_days) + 80, 140),
                    buy_cost=float(backtest_cost),
                    sell_cost=float(backtest_cost),
                    stamp_tax=0.0005,
                )
            st.success(f"{selected_backend_label} T+1 回测已完成，数据检查和必要下载已由 APP 自动处理。")
        except Exception as e:
            st.error(f"基础回测失败：{e}")

    backtest_nav, backtest_metrics, backtest_trades, backtest_predictions = load_backtest_outputs()
    backtest_metrics_backend = ""
    if backtest_metrics:
        backtest_metrics_backend = backtest_metrics.get("model_backend", "")
        if not backtest_metrics_backend and backtest_metrics.get("model_name") == "dft_unet_external":
            backtest_metrics_backend = "dft_unet_external"
        if (
            not backtest_metrics_backend
            and str(backtest_metrics.get("model_name", "")) in list_model_names()
        ):
            backtest_metrics_backend = f"zoo:{backtest_metrics.get('model_name')}"
        if not backtest_metrics_backend:
            backtest_metrics_backend = str(backtest_metrics.get("model_name", ""))
    backtest_matches_current_backend = backtest_metrics_backend == selected_backend

    if backtest_nav is not None and backtest_metrics and backtest_matches_current_backend:
        backtest_model_backend = backtest_metrics.get("model_backend", selected_backend)
        backtest_model_label = backend_display_name(backtest_model_backend)
        backtest_model_name = backtest_metrics.get("model_name", backtest_model_label)
        metric_cols = st.columns(6)

        metric_cols[0].metric(
            "累计收益",
            f"{backtest_metrics.get('cumulative_return', 0):.2%}",
        )
        metric_cols[1].metric(
            "基准累计收益",
            f"{backtest_metrics.get('benchmark_cumulative_return', 0):.2%}",
        )
        metric_cols[2].metric(
            "最大回撤",
            f"{backtest_metrics.get('max_drawdown', 0):.2%}",
        )
        metric_cols[3].metric(
            "胜率",
            f"{backtest_metrics.get('win_rate', 0):.2%}",
        )
        metric_cols[4].metric(
            "夏普比率",
            f"{backtest_metrics.get('sharpe_ratio', 0):.3f}"
            if backtest_metrics.get("sharpe_ratio") is not None
            else "N/A",
        )
        metric_cols[5].metric(
            "平均换手",
            f"{backtest_metrics.get('average_turnover', 0):.2%}",
        )

        st.caption(
            f"回测区间：{backtest_metrics.get('start_date', '未知')} ~ "
            f"{backtest_metrics.get('end_date', '未知')} ｜ "
            f"回测模型：{backtest_model_label} ｜ "
            f"model_name：{backtest_model_name} ｜ "
            f"数据处理：{backtest_metrics.get('data_source_action', '未知')} ｜ "
            "每日收盘后生成信号，以 T+1 单日收益评估。"
        )

        fig_nav = px.line(
            backtest_nav,
            x="date",
            y=["nav", "benchmark_nav"],
            title="TopK 回测净值曲线",
        )
        st.plotly_chart(fig_nav, width="stretch")

        drawdown_df = backtest_nav.copy()
        drawdown_df["策略回撤"] = calc_drawdown_series(drawdown_df["nav"])
        drawdown_df["基准回撤"] = calc_drawdown_series(drawdown_df["benchmark_nav"])
        fig_drawdown = px.line(
            drawdown_df,
            x="date",
            y=["策略回撤", "基准回撤"],
            title="TopK 回测回撤曲线",
        )
        st.plotly_chart(fig_drawdown, width="stretch")

        compare_df, compare_metrics = build_topk_comparison(
            predictions_df=backtest_predictions,
            topk_options=(10, 20, 30, 50),
            buy_cost=float(backtest_metrics.get("buy_cost", 0.0003)),
            sell_cost=float(backtest_metrics.get("sell_cost", 0.0003)),
            stamp_tax=float(backtest_metrics.get("stamp_tax", 0.0005)),
        )

        if not compare_df.empty:
            fig_topk_compare = px.line(
                compare_df,
                x="date",
                y="nav",
                color="topk",
                title="不同 TopK 净值对比",
            )
            st.plotly_chart(fig_topk_compare, width="stretch")

        if not compare_metrics.empty:
            show_compare_metrics = compare_metrics.copy()

            for col in ["累计收益", "最大回撤", "胜率", "平均换手"]:
                show_compare_metrics[col] = show_compare_metrics[col].map(
                    lambda x: f"{x:.2%}" if pd.notna(x) else ""
                )

            show_compare_metrics["夏普比率"] = show_compare_metrics["夏普比率"].map(
                lambda x: f"{x:.3f}" if pd.notna(x) else "N/A"
            )
            st.dataframe(show_compare_metrics, width="stretch")

        with st.expander("查看回测指标"):
            st.json(backtest_metrics)

        if backtest_trades is not None and not backtest_trades.empty:
            trade_dates, latest_prediction_date = build_display_date_options(backtest_trades, ranking)
            selected_trade_date = st.selectbox(
                "选择展示日期",
                options=trade_dates,
                index=0,
            )

            if selected_trade_date == latest_prediction_date and is_prediction_only_date(selected_trade_date, backtest_trades):
                st.info(
                    f"{selected_trade_date} 是最新预测信号日期，当前还没有完整 T+1 真实收益，"
                    "下表展示的是最新预测排名；回测收益指标仍以已可评估交易日为准。"
                )
                show_trades = ranking[
                    pd.to_datetime(ranking["date"], errors="coerce").dt.strftime("%Y-%m-%d") == selected_trade_date
                ].copy()
                show_trades = show_trades.head(int(backtest_topk)).copy()
            else:
                show_trades = backtest_trades[
                    backtest_trades["date"].astype(str) == selected_trade_date
                ].copy()

            show_trades = show_trades.sort_values("rank").reset_index(drop=True)

            for col in [
                "weight",
                "day_ret",
                "up_prob",
                "t1_ret",
                "portfolio_ret",
                "net_portfolio_ret",
                "turnover",
                "buy_turnover",
                "sell_turnover",
                "ret_5",
                "ret_20",
                "vol_20",
                "drawdown_20",
            ]:
                if col in show_trades.columns:
                    show_trades[col] = show_trades[col].map(
                        lambda x: f"{x:.2%}" if pd.notna(x) else ""
                    )

            if "pct_chg" in show_trades.columns:
                show_trades["pct_chg"] = show_trades["pct_chg"].map(format_tushare_pct_chg)

            for col in ["pred_score", "score"]:
                if col in show_trades.columns:
                    show_trades[col] = show_trades[col].map(
                        lambda x: f"{x:.3f}" if pd.notna(x) else ""
                    )

            show_trades = show_trades.rename(columns={
                "date": "日期",
                "rank": "排名",
                "code": "股票代码",
                "name": "股票名称",
                "weight": "权重",
                "close": "收盘价",
                "day_ret": "当日涨跌",
                "pct_chg": "当日涨跌",
                "pred_score": "模型分数",
                "pred_5d_ret": "旧版预测收益",
                "up_prob": "上涨概率",
                "score": "排名分位",
                "t1_ret": "T+1单日收益",
                "portfolio_ret": "组合单日收益",
                "net_portfolio_ret": "扣费后组合收益",
                "turnover": "换手率",
                "buy_turnover": "买入换手",
                "sell_turnover": "卖出换手",
                "rebalance_action": "调仓动作",
                "ret_5": "近5日收益",
                "ret_20": "近20日收益",
                "vol_20": "近20日波动率",
                "drawdown_20": "近20日回撤",
            })

            display_trade_cols = [
                "日期",
                "排名",
                "股票代码",
                "股票名称",
                "收盘价",
                "调仓动作",
                "当日涨跌",
                "模型分数",
                "上涨概率",
                "排名分位",
                "T+1单日收益",
                "换手率",
                "买入换手",
                "卖出换手",
                "近5日收益",
                "近20日收益",
                "近20日波动率",
                "近20日回撤",
            ]
            show_trades = show_trades[
                [c for c in display_trade_cols if c in show_trades.columns]
            ].copy()

            st.dataframe(show_trades, width="stretch")
    elif backtest_nav is not None and backtest_metrics and not backtest_matches_current_backend:
        st.warning(
            "已有回测结果来自其他模型，已避免混合展示。"
            f"当前选择：{selected_backend_label}；已有结果："
            f"{backend_display_name(backtest_metrics_backend)} / {backtest_metrics.get('model_name', '未知')}。"
            "请点击“检查数据并运行 T+1 回测”生成当前后端的回测结果。"
        )
    else:
        st.info("暂无回测结果。")

if selected_home_section == "\u65b0\u95fb\u4e8b\u4ef6":
    st.subheader("\u65b0\u95fb\u4e8b\u4ef6")
    st.caption("\u5c55\u793a\u672c\u5730\u7f13\u5b58\u4e2d\u7684\u65b0\u95fb/\u516c\u544a\u4e8b\u4ef6\uff0c\u4e0d\u89e6\u53d1\u8054\u7f51\u4e0b\u8f7d\u3002")

    events = load_news_events_for_app()

    if events.empty:
        st.info("\u6682\u65e0\u65b0\u95fb/\u516c\u544a\u7f13\u5b58\u3002")
    else:
        news_col1, news_col2, news_col3, news_col4 = st.columns([2, 1, 2, 1])

        with news_col1:
            news_stock = st.selectbox(
                "\u6309\u80a1\u7968\u8fc7\u6ee4",
                options=["\u5168\u90e8"] + ranking["name"].astype(str).tolist(),
                key="news_stock_filter",
            )

        with news_col2:
            news_event_type = st.selectbox(
                "\u4e8b\u4ef6\u7c7b\u578b",
                options=[
                    "\u5168\u90e8",
                    "\u6b63\u9762",
                    "\u8d1f\u9762",
                    "\u98ce\u9669",
                    "\u4e2d\u7acb",
                ],
                key="news_event_type_filter",
            )

        with news_col3:
            event_dates = pd.to_datetime(events["date"], errors="coerce").dropna()
            if event_dates.empty:
                min_event_date = pd.Timestamp.today().date()
                max_event_date = min_event_date
            else:
                min_event_date = event_dates.min().date()
                max_event_date = event_dates.max().date()

            news_date_range = st.date_input(
                "\u65e5\u671f\u8303\u56f4",
                value=(min_event_date, max_event_date),
                min_value=min_event_date,
                max_value=max_event_date,
                key="news_date_range_filter",
            )

        with news_col4:
            news_rows = st.selectbox(
                "\u5c55\u793a\u6761\u6570",
                options=[20, 50, 100],
                index=0,
                key="news_rows_filter",
            )

        show_events_all = events.copy()

        if news_stock != "\u5168\u90e8":
            news_code = ranking.loc[ranking["name"].astype(str) == news_stock, "code"].iloc[0]
            show_events_all = show_events_all[show_events_all["code"] == str(news_code).zfill(6)].copy()

        if isinstance(news_date_range, (list, tuple)):
            if len(news_date_range) >= 2:
                start_date, end_date = news_date_range[0], news_date_range[1]
            elif len(news_date_range) == 1:
                start_date = end_date = news_date_range[0]
            else:
                start_date, end_date = min_event_date, max_event_date
        else:
            start_date = end_date = news_date_range

        event_date_values = pd.to_datetime(
            show_events_all["date"],
            errors="coerce",
        ).dt.date
        date_mask = (event_date_values >= start_date) & (event_date_values <= end_date)
        show_events_all = show_events_all.loc[date_mask].copy()

        if news_event_type != "\u5168\u90e8":
            flag_map = {
                "\u6b63\u9762": "is_positive_event",
                "\u8d1f\u9762": "is_negative_event",
                "\u98ce\u9669": "is_risk_event",
            }
            flags = show_events_all["title"].map(classify_event_title).apply(pd.Series)
            for flag_col in flag_map.values():
                if flag_col not in flags.columns:
                    flags[flag_col] = 0
                flags[flag_col] = pd.to_numeric(
                    flags[flag_col],
                    errors="coerce",
                ).fillna(0).astype(int)

            if news_event_type == "\u4e2d\u7acb":
                event_mask = (
                    (flags["is_positive_event"] <= 0)
                    & (flags["is_negative_event"] <= 0)
                    & (flags["is_risk_event"] <= 0)
                )
            else:
                event_mask = flags[flag_map[news_event_type]] > 0

            show_events_all = show_events_all.loc[event_mask].copy()

        show_events_all = show_events_all.sort_values(
            ["publish_time", "date"],
            ascending=False,
        ).head(int(news_rows))

        if show_events_all.empty:
            st.info("\u5f53\u524d\u7b5b\u9009\u6761\u4ef6\u4e0b\u6ca1\u6709\u65b0\u95fb/\u516c\u544a\u3002")
        else:
            show_events_all = show_events_all[["date", "code", "name", "title", "source", "url"]].copy()
            show_events_all["date"] = pd.to_datetime(show_events_all["date"]).dt.strftime("%Y-%m-%d")
            show_events_all = show_events_all.rename(
                columns={
                    "date": "\u65e5\u671f",
                    "code": "\u80a1\u7968\u4ee3\u7801",
                    "name": "\u80a1\u7968\u540d\u79f0",
                    "title": "\u6807\u9898",
                    "source": "\u6765\u6e90",
                    "url": "\u94fe\u63a5",
                }
            )
            st.dataframe(show_events_all, width="stretch")


if selected_home_section == "\u7cfb\u7edf\u8bbe\u7f6e":
    st.subheader("\u7cfb\u7edf\u8bbe\u7f6e")

    rag_ready = dashboard_service.rag_ready()

    setting_cols = st.columns(6)
    setting_cols[0].metric("Universe", UNIVERSE.upper())
    setting_cols[1].metric("\u5f53\u524d\u6a21\u578b\u7248\u672c", selected_version)
    setting_cols[2].metric("\u9ed8\u8ba4 TopK", str(topk_option))
    setting_cols[3].metric("\u65b0\u95fb\u7279\u5f81", "\u5f00\u542f" if ENABLE_NEWS_FEATURES else "\u5173\u95ed")
    setting_cols[4].metric("RAG \u68c0\u7d22", "\u53ef\u7528" if ENABLE_RAG and rag_ready else "\u672a\u5c31\u7eea")
    setting_cols[5].metric("AI \u89e3\u91ca", "\u5f00\u542f" if ENABLE_LLM_EXPLAINER else "\u5173\u95ed")

    st.markdown("#### \u672c\u5730\u914d\u7f6e")
    settings_col1, settings_col2 = st.columns(2)

    with settings_col1:
        st.write("Tushare Token\uff1a", "\u5df2\u586b\u5199" if token else "\u672a\u586b\u5199")
        st.write("\u81ea\u52a8\u66f4\u65b0\uff1a", "\u5f00\u542f" if auto_enabled else "\u5173\u95ed")
        st.write("\u81ea\u52a8\u66f4\u65b0\u65f6\u95f4\uff1a", auto_time.strftime("%H:%M"))

    with settings_col2:
        st.write("AI Profile\uff1a", active_llm_settings.profile_id)
        st.write("AI Base URL\uff1a", active_llm_settings.base_url if active_llm_settings.base_url else "\u9ed8\u8ba4")
        st.write("AI Model\uff1a", active_llm_settings.model)
        st.caption("AI \u63a5\u53e3\u5728\u5de6\u4fa7\u8fb9\u680f\u914d\u7f6e\u548c\u9a8c\u8bc1\u3002")

    st.markdown("#### \u672c\u5730\u6570\u636e\u72b6\u6001")
    status_rows = dashboard_service.file_status_rows([
        ("新闻缓存", NEWS_CACHE_PATH),
        ("公告缓存", ANNOUNCEMENT_CACHE_PATH),
        ("RAG 文档", RAG_DOCUMENTS_PATH),
        ("RAG 索引", RAG_INDEX_PATH),
        ("最新排名", RANKING_LATEST_PATH),
        ("回测预测", BACKTEST_DAILY_PREDICTIONS_PATH),
        ("模型候选表", MODEL_CANDIDATES_PATH),
        ("统一回测汇总", BACKTEST_MASTER_TABLE_PATH),
        ("目标搜索结果", MODEL_SEARCH_RESULTS_PATH),
        ("默认回测方案", SELECTED_STRATEGY_PATH),
    ])

    st.dataframe(pd.DataFrame(status_rows), width="stretch")

    with st.expander("\u8c03\u5ea6\u4efb\u52a1\u72b6\u6001"):
        jobs = get_scheduler_jobs(scheduler)
        st.write(jobs if jobs else "\u5f53\u524d\u6ca1\u6709\u542f\u7528\u81ea\u52a8\u66f4\u65b0\u4efb\u52a1\u3002")

    with st.expander("\u81ea\u52a8\u66f4\u65b0\u65e5\u5fd7"):
        log_text = read_auto_retrain_log()
        st.code(log_text if log_text else "\u6682\u65e0\u65e5\u5fd7\u3002")
