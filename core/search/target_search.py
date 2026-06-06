from __future__ import annotations

import argparse

import pandas as pd

from core.config.paths import (
    BACKTEST_MASTER_TABLE_PATH,
    MODEL_CANDIDATES_PATH,
    MODEL_SEARCH_DIR,
    MODEL_SEARCH_ERRORS_PATH,
    MODEL_SEARCH_REPORT_PATH,
    MODEL_SEARCH_RESULTS_PATH,
)
from model_discovery.discovery_pipeline import run_discovery


DISCLAIMER = "回测结果仅代表历史数据上的模型表现，不代表未来收益，不构成投资建议。"


def ensure_dirs() -> None:
    MODEL_SEARCH_DIR.mkdir(parents=True, exist_ok=True)


def _load_candidates() -> pd.DataFrame:
    if not MODEL_CANDIDATES_PATH.exists():
        run_discovery(include_online=False)
    if not MODEL_CANDIDATES_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(MODEL_CANDIDATES_PATH, encoding="utf-8-sig")


def _load_master() -> pd.DataFrame:
    if not BACKTEST_MASTER_TABLE_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(BACKTEST_MASTER_TABLE_PATH, encoding="utf-8-sig")


def build_search_results(
    target_metric: str = "annual_return",
    target_value: float = 0.10,
    max_candidates: int = 50,
    min_days: int = 60,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ensure_dirs()
    candidates = _load_candidates()
    master = _load_master()

    if master.empty:
        errors = pd.DataFrame(
            [
                {
                    "stage": "target_search",
                    "error": "backtest_master_table.csv is missing or empty; run at least one model backtest first",
                }
            ]
        )
        errors.to_csv(MODEL_SEARCH_ERRORS_PATH, index=False, encoding="utf-8-sig")
        return pd.DataFrame(), errors

    success = master[master.get("status", "").astype(str).eq("success")].copy()
    if "num_days" in success.columns:
        success["num_days"] = pd.to_numeric(success["num_days"], errors="coerce")
        success = success[success["num_days"] >= int(min_days)].copy()
    if success.empty:
        errors = pd.DataFrame(
            [
                {
                    "stage": "target_search",
                    "error": f"no successful backtest rows with num_days >= {min_days} found in backtest_master_table.csv",
                }
            ]
        )
        errors.to_csv(MODEL_SEARCH_ERRORS_PATH, index=False, encoding="utf-8-sig")
        return pd.DataFrame(), errors

    if target_metric not in success.columns:
        raise RuntimeError(f"target metric is not in master table: {target_metric}")

    if "timestamp" in success.columns:
        success["_timestamp_sort"] = pd.to_datetime(
            success["timestamp"].astype(str),
            format="%Y%m%d_%H%M%S",
            errors="coerce",
        )
        success = success.sort_values(["_timestamp_sort", "run_id"], ascending=[True, True])
        strategy_keys = [
            col
            for col in ["model_name", "topk", "holding_days", "rank_by"]
            if col in success.columns
        ]
        if strategy_keys:
            success = success.drop_duplicates(strategy_keys, keep="last").copy()
        success = success.drop(columns=["_timestamp_sort"], errors="ignore")

    success[target_metric] = pd.to_numeric(success[target_metric], errors="coerce")
    success["target_metric"] = target_metric
    success["target_value"] = float(target_value)
    success["target_hit"] = success[target_metric] >= float(target_value)

    if not candidates.empty:
        candidate_cols = [
            "model_name",
            "category",
            "source_url",
            "has_pretrained_weight",
            "has_training_code",
            "priority",
        ]
        available = [col for col in candidate_cols if col in candidates.columns]
        candidate_info = candidates[available].copy()
        if "model_name" in candidate_info.columns:
            success = success.merge(
                candidate_info,
                on="model_name",
                how="left",
                suffixes=("", "_candidate"),
            )

    sort_cols = ["target_hit", target_metric, "cum_return"]
    sort_cols = [col for col in sort_cols if col in success.columns]
    success = success.sort_values(sort_cols, ascending=[False] + [False] * (len(sort_cols) - 1))
    result = success.head(int(max_candidates)).copy()
    result.to_csv(MODEL_SEARCH_RESULTS_PATH, index=False, encoding="utf-8-sig")

    errors = pd.DataFrame(columns=["stage", "error"])
    errors.to_csv(MODEL_SEARCH_ERRORS_PATH, index=False, encoding="utf-8-sig")
    write_report(result, target_metric, target_value)
    return result, errors


def write_report(results: pd.DataFrame, target_metric: str, target_value: float) -> None:
    if results.empty:
        lines = [
            "# Model Search Report",
            "",
            DISCLAIMER,
            "",
            "No successful model backtest result is available yet.",
        ]
        MODEL_SEARCH_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
        return

    hits = results[results["target_hit"].astype(bool)].copy()
    best = results.iloc[0].to_dict()
    lines = [
        "# Model Search Report",
        "",
        DISCLAIMER,
        "",
        f"- target_metric: {target_metric}",
        f"- target_value: {target_value}",
        f"- result_rows: {len(results)}",
        f"- target_hits: {len(hits)}",
        "",
    ]
    if hits.empty:
        lines.extend(
            [
                "## Closest Strategy",
                "",
                (
                    f"No model reached the target. Closest result: {best.get('model_name')} "
                    f"top{best.get('topk')} with {target_metric}={best.get(target_metric)}."
                ),
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Target Hit Strategies",
                "",
                "| model | topk | holding_days | annual_return | cum_return | daily_returns_csv |",
                "|---|---:|---:|---:|---:|---|",
            ]
        )
        for _, row in hits.iterrows():
            lines.append(
                f"| {row.get('model_name')} | {row.get('topk')} | {row.get('holding_days')} | "
                f"{row.get('annual_return')} | {row.get('cum_return')} | {row.get('daily_returns_csv')} |"
            )

    MODEL_SEARCH_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize model-search results against a target metric.")
    parser.add_argument("--target-metric", default="annual_return")
    parser.add_argument("--target-value", type=float, default=0.10)
    parser.add_argument("--max-candidates", type=int, default=50)
    parser.add_argument("--min-days", type=int, default=60)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results, errors = build_search_results(
        target_metric=args.target_metric,
        target_value=args.target_value,
        max_candidates=args.max_candidates,
        min_days=args.min_days,
    )
    print(f"[Target Search] results={len(results)}")
    print(f"[Target Search] errors={len(errors)}")
    print(f"[Target Search] csv={MODEL_SEARCH_RESULTS_PATH}")
    if not results.empty:
        best = results.iloc[0]
        print(
            f"[Target Search] best={best.get('model_name')} top{best.get('topk')} "
            f"{args.target_metric}={best.get(args.target_metric)} target_hit={best.get('target_hit')}"
        )


if __name__ == "__main__":
    main()
