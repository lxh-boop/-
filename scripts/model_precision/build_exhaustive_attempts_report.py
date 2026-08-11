from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "outputs" / "model_precision"
JSON_OUTPUT = OUTPUT_DIR / "stock_top15_exhaustive_attempts_report.json"
MARKDOWN_OUTPUT = OUTPUT_DIR / "stock_top15_exhaustive_attempts_report.md"
DISCLAIMER = "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。"


def _read(name: str) -> dict[str, Any]:
    return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))


def _atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    formal = _read("stock_top15_evaluation_report.json")
    candidate = _read("stock_top15_candidate_ensemble_holdout.json")
    annual = _read("stock_top15_annual_walk_forward.json")
    v7 = _read("stock_top15_model_search_v7_groups.json")
    regime = _read("stock_top15_regime_ensemble.json")
    sklearn_heads = _read("stock_top15_sklearn_heads.json")
    meta = _read("stock_top15_oof_meta_head.json")
    event_manifest = json.loads(
        (ROOT / "data" / "model_precision" / "tushare_events" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    event_dir = ROOT / "data" / "model_precision" / "tushare_events"
    event_endpoints = (
        "fina_indicator",
        "forecast",
        "express",
        "dividend",
        "stk_holdernumber",
        "share_float",
        "top_list",
        "block_trade",
        "top_inst",
        "repurchase",
        "broker_recommend",
    )
    event_reports = []
    for endpoint in event_endpoints:
        path = event_dir / f"{endpoint}.csv"
        if not path.exists():
            continue
        try:
            rows = len(pd.read_csv(path, usecols=[0], dtype=str))
        except pd.errors.EmptyDataError:
            rows = 0
        event_reports.append(
            {"endpoint": endpoint, "rows": rows, "output": str(path)}
        )
    validation_signals = int(candidate["validation_signals"])
    target_validation_correct = math.ceil(validation_signals * 0.55)
    validation_correct = int(candidate["validation_correct"])
    holdout = candidate["holdout"]
    target_holdout_correct = math.ceil(int(holdout["signals"]) * 0.55)
    baseline_validation = formal["baselines"]["validation_pred_return_top15"]
    baseline_holdout = formal["baselines"]["holdout_pred_return_top15"]
    v7_best = max(v7["models"], key=lambda row: row["validation_precision"])
    sklearn_best = max(
        sklearn_heads["models"], key=lambda row: row["precision"]
    )
    report: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "accepted": False,
        "objective": "fixed_daily_individual_stock_top15_next_trading_day_up_precision",
        "target_precision": 0.55,
        "metric_definition": {
            "label": "future_1d_ret > 0",
            "daily_selection_count": 15,
            "daily_precision": "next-day rising stocks among the selected 15 divided by 15",
            "reported_precision": "arithmetic mean of daily precision across every evaluation trading day",
            "abstention_allowed": False,
            "note": "Because every day has exactly 15 signals, daily-average precision equals pooled correct/signals.",
        },
        "data": {
            "rows": 604403,
            "stocks": 557,
            "days": 2049,
            "start_date": "2018-02-14",
            "end_date": "2026-07-30",
            "training": formal["training"],
            "validation": {
                "year": 2025,
                "days": 243,
                "signals": validation_signals,
            },
            "holdout": {
                "year": 2026,
                "days": int(holdout["days"]),
                "signals": int(holdout["signals"]),
            },
            "v7_feature_count": 1163,
            "v7_feature_groups": {
                "alpha": 157,
                "events": 94,
                "daily_cross_sectional_ranks": 353,
                "industry_relative_ranks": 197,
            },
            "tushare_event_reports": event_reports,
            "latest_event_download_manifest": event_manifest,
        },
        "baselines": {
            "kronos_pred_return_2025": baseline_validation,
            "kronos_pred_return_2026": baseline_holdout,
        },
        "best_observed_but_rejected": {
            "validation_2025": {
                "precision": float(candidate["validation_precision_used_for_selection"]),
                "correct": validation_correct,
                "signals": validation_signals,
                "required_correct": target_validation_correct,
                "shortfall_correct": target_validation_correct - validation_correct,
            },
            "holdout_2026": {
                **holdout,
                "required_correct": target_holdout_correct,
                "shortfall_correct": target_holdout_correct - int(holdout["correct"]),
            },
            "rejection_reason": "The candidate missed 55% on validation and collapsed on the later holdout.",
        },
        "cross_year_walk_forward": annual,
        "attempt_summary": [
            {
                "family": "formal LightGBM rank_xendcg stock head",
                "validation_precision": formal["validation"]["daily_average_precision"],
                "holdout_precision": formal["holdout"]["daily_average_precision"],
            },
            {
                "family": "LambdaRank seeds, truncation levels, depth and regularization",
                "best_validation_precision": candidate["validation_precision_used_for_selection"],
                "holdout_precision": holdout["precision"],
            },
            {
                "family": "complete Alpha158 plus Tushare event/fundamental features",
                "best_model": v7_best["name"],
                "best_validation_precision": v7_best["validation_precision"],
            },
            {
                "family": "one-model-per-year regime ensemble",
                "validation_precision": regime["validation_selected"]["precision"],
                "holdout_precision": regime["holdout"]["precision"],
            },
            {
                "family": "ExtraTrees, histogram gradient, random forest and linear classification heads",
                "best_model": sklearn_best["model"],
                "best_validation_precision": sklearn_best["precision"],
            },
            {
                "family": "OOF base prediction plus second-stage ranking/binary head",
                "validation_precision": meta["validation_selected"]["precision"],
                "holdout_precision": meta["holdout"]["precision"],
            },
            {
                "family": "additional rejected searches",
                "methods": [
                    "binary classification, raw-return regression and rank regression",
                    "candidate-pool two-stage reranking",
                    "static and online factor selection",
                    "cross-sectional and industry-relative feature normalization",
                    "time-decay weighting, shorter windows, quarterly and annual walk-forward retraining",
                    "seed/model score blending and consensus reranking",
                    "direct top-list, institutional-list and block-trade rules",
                ],
            },
        ],
        "resource_limits": [
            "The local Kronos base-model training lab/checkpoint is absent, so the base representation cannot be retrained or given a native multitask direction head.",
            "No historical order-book, auction, intraday or complete long-horizon news panel exists in the project.",
            "Tushare report_rc is available but capped at 5000 rows per query and one query per minute; the existing event and fundamental endpoints with practical full-history coverage were downloaded instead.",
        ],
        "production_decision": {
            "promoted_new_model": False,
            "stock_direction_model_exists": (
                ROOT / "models" / "kronos_mini" / "stock_direction_head.joblib"
            ).exists(),
            "selection_contract": "exactly 15 stocks every day",
            "current_sort_signal": "Kronos pred_return",
            "reason": "No candidate met 55% on both validation and holdout; promoting one would misrepresent accuracy.",
        },
        "conclusion": "The requested 55% fixed-daily Top15 next-day up precision was not achieved with the available project resources.",
        "disclaimer": DISCLAIMER,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_text(JSON_OUTPUT, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    markdown = f"""# 每日固定 Top15 上涨精确率最终实验报告

- 结论：未达标，未发布新模型。
- 目标：每天固定选满15只，预测日后下一交易日收益 `> 0` 记为上涨，逐日精确率取算术平均，目标 `>= 55%`。
- 数据：604,403条、557只股票、2,049个交易日，2018-02-14至2026-07-30。
- 2025验证：最佳候选 `{candidate['validation_precision_used_for_selection']:.4%}`（{validation_correct}/{validation_signals}），达到55%至少需{target_validation_correct}次，差{target_validation_correct-validation_correct}次。
- 2026盲测：同一候选 `{holdout['precision']:.4%}`（{holdout['correct']}/{holdout['signals']}），显著失效。
- 原Kronos `pred_return`：2025 `{baseline_validation['daily_average_precision']:.4%}`，2026 `{baseline_holdout['daily_average_precision']:.4%}`。
- 新增资源：完整Alpha158、日横截面/行业排名、Tushare财务指标、龙虎榜、机构龙虎榜、大宗交易、回购、股东人数、分红、限售解禁和券商月度推荐。
- 已尝试：排序/分类/回归、传统树模型、时间衰减、滚动/年度专家、因子组合、两阶段重排、OOF二阶段头及多模型集成。
- 生产决定：保持每日固定15只的现有Kronos排序，不写入未达标的 `stock_direction_head.joblib`。

失败的核心证据是跨年不稳定：同一排序头在2022–2026分别为 `{annual['years'][0]['precision']:.2%}`、`{annual['years'][1]['precision']:.2%}`、`{annual['years'][2]['precision']:.2%}`、`{annual['years'][3]['precision']:.2%}`、`{annual['years'][4]['precision']:.2%}`。2025的高值不能代表可泛化能力。

{DISCLAIMER}
"""
    _atomic_text(MARKDOWN_OUTPUT, markdown)
    print(json.dumps({"json": str(JSON_OUTPUT), "markdown": str(MARKDOWN_OUTPUT), "accepted": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
