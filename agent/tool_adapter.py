from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.services.file_loader import safe_read_csv, safe_read_json
from config import (
    BACKTEST_METRICS_PATH,
    MARKET_CONTEXT_FEATURE_CACHE_PATH,
    MARKET_CONTEXT_INDEX_DAILY_CACHE_PATH,
    OUTPUT_DIR,
    RANKING_LATEST_PATH,
)
from core.config.paths import (
    BACKTEST_MASTER_TABLE_PATH,
    MODEL_CANDIDATES_PATH,
    MODEL_SEARCH_RESULTS_PATH,
    SELECTED_STRATEGY_PATH,
    OUTPUTS_DIR,
    project_path,
)
from ranking_schema import normalize_ranking_columns


def _jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return None if math.isnan(value) else value
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value) if not isinstance(value, (list, dict, tuple)) else False:
        return None
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    return value


def _records_from_df(df: pd.DataFrame) -> list[dict]:
    return [
        {str(k): _jsonable(v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]


def _safe_float(value, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except Exception:
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _find_latest_ranking_file() -> Path | None:
    primary = Path(RANKING_LATEST_PATH)
    if primary.exists():
        return primary

    output_dir = Path(OUTPUT_DIR)
    if not output_dir.exists():
        return None

    candidates: list[Path] = []
    for pattern in ["*ranking*.csv", "*predict*.csv", "*prediction*.csv"]:
        candidates.extend(path for path in output_dir.rglob(pattern) if path.is_file())

    filtered = [
        path
        for path in candidates
        if "master" not in path.name.lower()
        and "candidate" not in path.name.lower()
        and "daily_returns" not in str(path).lower()
    ]
    if not filtered:
        return None
    return sorted(filtered, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def _load_latest_ranking_df(model_name: str | None = None) -> tuple[pd.DataFrame, Path | None, str]:
    path = _find_latest_ranking_file()
    if path is None:
        return pd.DataFrame(), None, "未找到最新预测排名文件，请先运行 daily_incremental_update.py。"

    result = safe_read_csv(path, dtype={"code": str})
    if not result.ok:
        return pd.DataFrame(), path, result.message

    try:
        df = normalize_ranking_columns(result.data)
    except Exception as exc:
        return pd.DataFrame(), path, f"ranking 字段规范化失败：{exc}"

    if "code" not in df.columns:
        return pd.DataFrame(), path, "ranking 文件缺少股票代码字段。"

    if model_name and "model_name" in df.columns:
        wanted = str(model_name).strip().lower()
        if wanted:
            mask = df["model_name"].astype(str).str.lower().map(
                lambda value: wanted in value or value in wanted
            )
            filtered = df.loc[mask].copy()
            if not filtered.empty:
                df = filtered

    if "rank" in df.columns:
        df = df.sort_values("rank", ascending=True)
    else:
        df = df.sort_values("score", ascending=False)

    return df.reset_index(drop=True), path, "读取成功"


def _prediction_dates(df: pd.DataFrame) -> tuple[str, str]:
    trade_date = ""
    predict_for_date = ""
    if "date" in df.columns and not df.empty:
        trade_date = str(pd.to_datetime(df["date"], errors="coerce").dropna().max().date())
    for col in ["predict_for_date", "prediction_date", "next_trade_date"]:
        if col in df.columns and not df.empty:
            value = df[col].dropna()
            if not value.empty:
                predict_for_date = str(value.iloc[0]).split(" ")[0]
                break
    return trade_date, predict_for_date


def tool_query_latest_ranking(topk: int = 10, model_name: str | None = None) -> dict:
    from agent.services.market_analysis_service import market_analysis_service

    return market_analysis_service.get_latest_ranking_report(
        topk=topk,
        model_name=model_name,
        output_dir=OUTPUT_DIR,
        ranking_path=RANKING_LATEST_PATH,
    )

    df, path, message = _load_latest_ranking_df(model_name=model_name)
    if path is None or df.empty:
        return {
            "success": False,
            "message": message,
            "records": [],
        }

    topk = max(1, int(topk or 10))
    show = df.head(topk).copy()
    trade_date, predict_for_date = _prediction_dates(df)

    rename_map = {
        "code": "stock_code",
        "name": "stock_name",
        "date": "trade_date",
    }
    keep_cols = [
        "rank",
        "code",
        "name",
        "score",
        "confidence_score",
        "confidence",
        "risk_score",
        "risk_level",
        "model_name",
        "date",
        "close",
        "up_prob",
        "up_prob_calibrated",
    ]
    show = show[[col for col in keep_cols if col in show.columns]].rename(columns=rename_map)
    if "predict_for_date" not in show.columns:
        show["predict_for_date"] = predict_for_date

    return {
        "success": True,
        "message": f"查询成功，返回 {len(show)} 条预测排名记录。",
        "source_file": str(path),
        "total_rows": int(len(df)),
        "topk": int(topk),
        "trade_date": trade_date,
        "predict_for_date": predict_for_date,
        "model_name": model_name or (str(df["model_name"].iloc[0]) if "model_name" in df.columns else ""),
        "records": _records_from_df(show),
    }


_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _parse_rank_query(query: str) -> int | None:
    text = str(query or "").lower()
    match = re.search(r"top\s*(\d+)", text)
    if match:
        return int(match.group(1))

    match = re.search(r"(?:排名)?第?\s*(\d+)\s*名?", text)
    if match:
        return int(match.group(1))

    for word, number in _CHINESE_NUMBERS.items():
        if f"第{word}" in text or f"排名{word}" in text or f"{word}名" in text:
            return number
    return None


def _normalize_stock_code_query(query: str) -> str | None:
    text = str(query or "").strip().upper()
    match = re.search(r"(?:SH|SZ|BJ)?\s*(\d{6})(?:\.(?:SH|SZ|BJ))?", text)
    if match:
        return match.group(1).zfill(6)
    return None


def _find_stock_row(df: pd.DataFrame, stock_query: str) -> tuple[pd.Series | None, str]:
    if df.empty:
        return None, "ranking 为空。"

    rank = _parse_rank_query(stock_query)
    if rank is not None and "rank" in df.columns:
        match = df[pd.to_numeric(df["rank"], errors="coerce") == rank]
        if not match.empty:
            return match.iloc[0], f"按排名第 {rank} 名匹配。"

    code = _normalize_stock_code_query(stock_query)
    if code and "code" in df.columns:
        match = df[df["code"].astype(str).str.zfill(6) == code]
        if not match.empty:
            return match.iloc[0], f"按股票代码 {code} 匹配。"

    text = str(stock_query or "").strip()
    if text and "name" in df.columns:
        exact = df[df["name"].astype(str) == text]
        if not exact.empty:
            return exact.iloc[0], f"按股票名称 {text} 精确匹配。"
        contains = df[df["name"].astype(str).map(lambda value: value and value in text or text in value)]
        if not contains.empty:
            return contains.iloc[0], f"按股票名称 {contains.iloc[0].get('name', '')} 模糊匹配。"

    return None, f"未在最新 ranking 中匹配到：{stock_query}"


def tool_explain_stock(stock_query: str, model_name: str | None = None) -> dict:
    df, path, message = _load_latest_ranking_df(model_name=model_name)
    if path is None or df.empty:
        return {
            "success": False,
            "message": message,
            "explanation": "",
        }

    row, match_message = _find_stock_row(df, stock_query)
    if row is None:
        return {
            "success": False,
            "message": match_message,
            "source_file": str(path),
            "explanation": "",
        }

    market = tool_query_market_context()
    market_context = market if market.get("success") else None
    ranking_record = row.to_dict()

    try:
        from llm_explainer import explain_with_agent_context

        explanation = explain_with_agent_context(
            user_query=stock_query,
            ranking_record=ranking_record,
            model_info={"model_name": ranking_record.get("model_name", model_name or "")},
            backtest_info=None,
            market_context=market_context,
            news_context=None,
        )
    except Exception:
        explanation = (
            f"该股票出现在当前模型预测排名中，排名为第 {ranking_record.get('rank', '未知')} 名，"
            f"模型分数为 {ranking_record.get('score', '未知')}。\n\n"
            f"- 可信度评分：{ranking_record.get('confidence_score', '当前 ranking 未提供')}\n"
            f"- 风险评分：{ranking_record.get('risk_score', '当前 ranking 未提供')}\n"
            "- 市场环境：当前项目未提供该数据\n"
            "- 新闻因素：当前项目未提供该数据\n\n"
            "模型分数只表示当前特征和训练数据下的相对排序结果，不代表确定收益。\n\n"
            "本内容仅用于机器学习、金融数据分析和项目展示，不构成投资建议。"
        )

    return {
        "success": True,
        "message": f"解释生成成功，{match_message}",
        "source_file": str(path),
        "record": _jsonable(ranking_record),
        "explanation": explanation,
    }


def _load_model_zoo_rows() -> list[dict]:
    from model_zoo.metadata import bootstrap_registered_metadata, load_metadata
    from model_zoo.registry import list_model_entries

    bootstrap_registered_metadata()
    metadata = load_metadata()
    by_name = {str(item.get("name")): dict(item) for item in metadata.get("models", [])}
    rows = []
    for entry in list_model_entries():
        item = entry.to_metadata()
        item.update(by_name.get(entry.name, {}))
        rows.append(item)
    return rows


def tool_query_model_zoo() -> dict:
    errors = []
    rows: list[dict] = []

    try:
        rows = _load_model_zoo_rows()
    except Exception as exc:
        errors.append(f"Model Zoo 元数据读取失败：{type(exc).__name__}: {exc}")

    backtest = tool_query_backtest()
    backtest_rows = backtest.get("records", []) if backtest.get("success") else []

    return {
        "success": bool(rows),
        "message": "模型库查询完成。" if rows else "未查询到模型库信息。",
        "default_model": "chronos_bolt_small",
        "model_zoo": _jsonable(rows),
        "backtest_snapshot": backtest_rows[:5],
        "errors": errors,
    }


_BACKTEST_COLUMN_ALIASES = {
    "AR": "annual_return",
    "IR": "information_ratio",
    "MDD": "max_drawdown",
    "TopK": "topk",
    "holding_period": "holding_days",
    "benchmark_AR": "benchmark_return",
    "benchmark_cumulative_return": "benchmark_return",
    "mean_turnover": "turnover",
    "mean_cost": "transaction_cost",
}


def _normalize_backtest_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename = {old: new for old, new in _BACKTEST_COLUMN_ALIASES.items() if old in out.columns}
    out = out.rename(columns=rename)

    if "information_ratio" not in out.columns and "IR" in df.columns:
        out["information_ratio"] = df["IR"]
    if "model_name" not in out.columns and "model" in out.columns:
        out["model_name"] = out["model"]

    numeric_cols = [
        "topk",
        "holding_days",
        "annual_return",
        "benchmark_return",
        "excess_return",
        "information_ratio",
        "sharpe",
        "max_drawdown",
        "turnover",
        "transaction_cost",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _load_backtest_result_frames() -> list[tuple[Path, pd.DataFrame]]:
    paths = [
        BACKTEST_MASTER_TABLE_PATH,
        MODEL_SEARCH_RESULTS_PATH,
        OUTPUTS_DIR / "backtest_summary.csv",
        OUTPUTS_DIR / "backtests" / "backtest_summary.csv",
    ]
    frames: list[tuple[Path, pd.DataFrame]] = []
    for path in paths:
        if not Path(path).exists():
            continue
        result = safe_read_csv(path)
        if result.ok and not result.data.empty:
            df = _normalize_backtest_columns(result.data)
            df["source_file"] = str(path)
            frames.append((Path(path), df))
    return frames


def _load_legacy_backtest_metrics() -> pd.DataFrame:
    result = safe_read_json(BACKTEST_METRICS_PATH)
    if not result.ok or not isinstance(result.data, dict):
        return pd.DataFrame()
    data = dict(result.data)
    row = {
        "model_name": data.get("model_name") or data.get("model_backend") or "",
        "topk": data.get("topk"),
        "holding_days": data.get("holding_days"),
        "annual_return": data.get("annual_return") or data.get("annualized_return"),
        "benchmark_return": data.get("benchmark_return") or data.get("benchmark_cumulative_return"),
        "excess_return": data.get("excess_return"),
        "information_ratio": data.get("IR") or data.get("information_ratio"),
        "sharpe": data.get("sharpe"),
        "max_drawdown": data.get("max_drawdown"),
        "turnover": data.get("mean_turnover") or data.get("turnover"),
        "transaction_cost": data.get("mean_cost") or data.get("transaction_cost"),
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "source_file": str(BACKTEST_METRICS_PATH),
    }
    return _normalize_backtest_columns(pd.DataFrame([row]))


def tool_query_backtest(
    model_name: str | None = None,
    topk: int | None = None,
    holding_days: int | None = None,
) -> dict:
    frames = [df for _, df in _load_backtest_result_frames()]
    legacy = _load_legacy_backtest_metrics()
    if not legacy.empty:
        frames.append(legacy)

    if not frames:
        return {
            "success": False,
            "message": "未找到回测结果文件，请先运行 backtest.py 或 scripts/evaluate/run_model_backtest.py。",
            "records": [],
        }

    data = pd.concat(frames, ignore_index=True, sort=False)
    if model_name and "model_name" in data.columns:
        wanted = str(model_name).lower()
        data = data[data["model_name"].astype(str).str.lower().map(lambda value: wanted in value or value in wanted)]
    if topk is not None and "topk" in data.columns:
        data = data[pd.to_numeric(data["topk"], errors="coerce") == int(topk)]
    if holding_days is not None and "holding_days" in data.columns:
        data = data[pd.to_numeric(data["holding_days"], errors="coerce") == int(holding_days)]

    if data.empty:
        return {
            "success": False,
            "message": "未查询到符合条件的回测结果。",
            "records": [],
        }

    keep = [
        "run_id",
        "model_name",
        "model_source",
        "model_category",
        "topk",
        "holding_days",
        "annual_return",
        "benchmark_return",
        "excess_return",
        "information_ratio",
        "sharpe",
        "max_drawdown",
        "turnover",
        "transaction_cost",
        "start_date",
        "end_date",
        "daily_returns_csv",
        "prediction_csv",
        "source_file",
    ]
    sort_col = "annual_return" if "annual_return" in data.columns else None
    if sort_col:
        data = data.sort_values(sort_col, ascending=False, na_position="last")
    out = data[[col for col in keep if col in data.columns]].head(20).copy()

    return {
        "success": True,
        "message": f"查询成功，返回 {len(out)} 条回测记录。",
        "records": _records_from_df(out),
    }


def tool_compare_models(metric: str = "综合表现") -> dict:
    backtest = tool_query_backtest()
    if not backtest.get("success"):
        return backtest

    df = pd.DataFrame(backtest.get("records", []))
    if df.empty:
        return {
            "success": False,
            "message": "没有可比较的模型回测记录。",
            "records": [],
        }

    for col in ["annual_return", "information_ratio", "max_drawdown", "turnover"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["annual_rank_score"] = df.get("annual_return", pd.Series(index=df.index, dtype=float)).rank(pct=True)
    df["ir_rank_score"] = df.get("information_ratio", pd.Series(index=df.index, dtype=float)).rank(pct=True)
    df["drawdown_rank_score"] = df.get("max_drawdown", pd.Series(index=df.index, dtype=float)).rank(pct=True)
    if "turnover" in df.columns:
        df["turnover_penalty"] = df["turnover"].rank(pct=True).fillna(0.5) * 0.2
    else:
        df["turnover_penalty"] = 0.0
    df["综合分"] = (
        df["annual_rank_score"].fillna(0.5)
        + df["ir_rank_score"].fillna(0.5)
        + df["drawdown_rank_score"].fillna(0.5)
        - df["turnover_penalty"].fillna(0.0)
    )
    df = df.sort_values("综合分", ascending=False)
    best = df.iloc[0].to_dict()

    return {
        "success": True,
        "message": "模型比较完成，结果仅用于项目展示。",
        "metric": metric,
        "display_candidate": _jsonable(best),
        "records": _records_from_df(df.head(20)),
    }


def tool_query_news_mapping(query: str) -> dict:
    try:
        from news_mapping.mapping_pipeline import map_user_event_query

        result = map_user_event_query(query=query, max_results=20)
        try:
            from agent.services.evidence_service import evidence_service

            stocks = result.get("stocks") if isinstance(result, dict) else []
            if isinstance(stocks, list):
                result["sources"] = evidence_service.format_sources(
                    [item for item in stocks if isinstance(item, dict)],
                    source_type="news_mapping",
                )
        except Exception:
            pass
        return result
    except Exception as exc:
        return {
            "success": False,
            "message": f"新闻映射查询失败：{type(exc).__name__}: {exc}",
            "stocks": [],
        }


def tool_query_rag(question: str, topk: int = 5) -> dict:
    try:
        from rag_retriever import retrieve_for_agent

        result = retrieve_for_agent(question=question, topk=topk)
        try:
            from agent.services.evidence_service import evidence_service

            evidence = result.get("evidence") if isinstance(result, dict) else []
            if isinstance(evidence, list):
                result["sources"] = evidence_service.format_sources(
                    [item for item in evidence if isinstance(item, dict)],
                    source_type="rag_chunk",
                )
        except Exception:
            pass
        return result
    except Exception as exc:
        return {
            "success": False,
            "message": f"RAG 检索失败：{type(exc).__name__}: {exc}",
            "evidence": [],
        }


def tool_query_market_context() -> dict:
    index_result = safe_read_csv(MARKET_CONTEXT_INDEX_DAILY_CACHE_PATH, parse_dates=["date"])
    feature_result = safe_read_csv(MARKET_CONTEXT_FEATURE_CACHE_PATH, parse_dates=["date"])

    if not index_result.ok and not feature_result.ok:
        return {
            "success": False,
            "message": "未找到市场环境缓存，请先运行每日更新或市场环境数据生成流程。",
        }

    data: dict[str, Any] = {
        "success": True,
        "message": "市场环境数据来自本地缓存。",
        "data_source": "local_cache",
    }
    if index_result.ok and not index_result.data.empty:
        idx = index_result.data.copy()
        data.update(
            {
                "index_rows": int(len(idx)),
                "index_codes": sorted(idx.get("index_code", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()),
                "index_date_min": str(idx["date"].min().date()) if "date" in idx.columns else "",
                "index_date_max": str(idx["date"].max().date()) if "date" in idx.columns else "",
            }
        )
    if feature_result.ok and not feature_result.data.empty:
        feat = feature_result.data.copy()
        data.update(
            {
                "feature_rows": int(len(feat)),
                "feature_date_min": str(feat["date"].min().date()) if "date" in feat.columns else "",
                "feature_date_max": str(feat["date"].max().date()) if "date" in feat.columns else "",
                "feature_columns": int(max(len(feat.columns) - 1, 0)),
            }
        )
    return _jsonable(data)


def load_selected_strategy_for_agent() -> dict:
    result = safe_read_json(SELECTED_STRATEGY_PATH)
    return result.data if result.ok and isinstance(result.data, dict) else {}


__all__ = [
    "tool_query_latest_ranking",
    "tool_explain_stock",
    "tool_query_model_zoo",
    "tool_query_backtest",
    "tool_compare_models",
    "tool_query_news_mapping",
    "tool_query_rag",
    "tool_query_market_context",
    "load_selected_strategy_for_agent",
]
