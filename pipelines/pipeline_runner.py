from __future__ import annotations

import argparse
import json
from typing import Sequence

from pipelines.daily_update_pipeline import run_daily_update_pipeline
from pipelines.schemas import PipelineContext


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the fixed daily pipeline workflow.")
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--trade-date", default="latest")
    parser.add_argument("--decision-time", default="")
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--stock-pool", default="csi300")
    parser.add_argument("--model-name", default="chronos_bolt_small")
    parser.add_argument("--model-version", default="latest")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--paper-trading", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--steps", default="prediction,rag,scoring,paper,report")
    return parser


def context_from_args(args: argparse.Namespace) -> PipelineContext:
    return PipelineContext(
        user_id=args.user_id,
        trade_date=args.trade_date,
        decision_time=args.decision_time,
        stock_pool=args.stock_pool,
        model_name=args.model_name,
        model_version=args.model_version,
        top_k=args.top_k,
        output_dir=args.output_dir,
        db_path=args.db_path,
        dry_run=args.dry_run,
        paper_trading_enabled=bool(args.paper_trading),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    context = context_from_args(args)
    result = run_daily_update_pipeline(context, steps=args.steps)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
    return 0 if result.status in {"success", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
