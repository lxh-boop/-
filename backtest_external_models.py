from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from backtest_engine import BACKTEST_OUTPUT_DIR, run_topk_backtest, update_backtest_summary
from evaluate_external_models import (
    PREDICTION_DIR,
    _load_data,
    _prediction_dates,
    evaluate_model,
)
from model_zoo.registry import get_model_entry


def _load_or_make_predictions(
    model_name: str,
    raw_data: pd.DataFrame,
    feature_data: pd.DataFrame,
    prediction_dates: list[pd.Timestamp],
    device: str,
    context_length: int,
    batch_size: int,
    force_predict: bool,
) -> tuple[pd.DataFrame, dict]:
    entry = get_model_entry(model_name)
    pred_path = PREDICTION_DIR / f"{entry.name}_predictions.csv"

    if pred_path.exists() and not force_predict:
        pred = pd.read_csv(pred_path, dtype={"code": str}, encoding="utf-8-sig")
        pred["date"] = pd.to_datetime(pred["date"])
        return pred, {"model_name": entry.name, "prediction_file": str(pred_path), "status": "loaded"}

    pred, metrics = evaluate_model(
        model_name=entry.name,
        raw_data=raw_data,
        feature_data=feature_data,
        prediction_dates=prediction_dates,
        device=device,
        context_length=context_length,
        batch_size=batch_size,
    )
    return pred, metrics


def run_external_model_backtests(args: argparse.Namespace) -> tuple[pd.DataFrame, dict]:
    raw, feature = _load_data()
    dates = _prediction_dates(feature, args.backtest_days, args.start_date, args.end_date)
    if not dates:
        raise RuntimeError("没有可回测的历史日期。")

    all_metrics = []
    errors = {}
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    topks = [int(x.strip()) for x in args.topk.split(",") if x.strip()]

    for model in models:
        try:
            entry = get_model_entry(model)
            pred, pred_metrics = _load_or_make_predictions(
                model_name=entry.name,
                raw_data=raw,
                feature_data=feature,
                prediction_dates=dates,
                device=args.device,
                context_length=args.context_length,
                batch_size=args.batch_size,
                force_predict=args.force_predict,
            )

            for topk in topks:
                _, metrics = run_topk_backtest(
                    pred_df=pred,
                    model_name=entry.name,
                    topk=topk,
                    holding_days=args.holding_days,
                    buy_cost=args.buy_cost,
                    sell_cost=args.sell_cost,
                    stamp_tax=args.stamp_tax,
                    output_dir=BACKTEST_OUTPUT_DIR,
                )
                metrics["prediction_status"] = pred_metrics.get("status")
                all_metrics.append(metrics)
        except Exception as exc:
            model_key = model
            try:
                model_key = get_model_entry(model).name
            except Exception:
                pass
            errors[model_key] = str(exc)

    summary_path = update_backtest_summary(all_metrics, output_dir=BACKTEST_OUTPUT_DIR) if all_metrics else None
    error_path = BACKTEST_OUTPUT_DIR / "external_backtest_errors.json"
    error_path.parent.mkdir(parents=True, exist_ok=True)
    error_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = pd.read_csv(summary_path, encoding="utf-8-sig") if summary_path else pd.DataFrame()
    return summary, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", required=True)
    parser.add_argument("--topk", default="10,30,50")
    parser.add_argument("--holding-days", type=int, default=5)
    parser.add_argument("--buy-cost", type=float, default=0.0003)
    parser.add_argument("--sell-cost", type=float, default=0.0008)
    parser.add_argument("--stamp-tax", type=float, default=0.001)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--benchmark", default="csi300_cross_section_mean")
    parser.add_argument("--backtest-days", type=int, default=60)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--context-length", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--force-predict", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    summary_df, errors = run_external_model_backtests(parse_args())
    if not summary_df.empty:
        print(summary_df.tail(20).to_string(index=False))
    if errors:
        print(json.dumps(errors, ensure_ascii=False, indent=2))
        raise SystemExit(1)
