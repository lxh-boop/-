from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from scheduler.daily_worker import run_scheduled_daily_update
from scheduler.health_check import run_health_check
from scheduler.job_state import load_latest_job_status


def _json_print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stock daily app scheduled worker CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run scheduled daily update")
    run.add_argument("--trade-date", default=None)
    run.add_argument("--user-id", action="append", default=[])
    run.add_argument("--all-users", action="store_true")
    run.add_argument("--force", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--skip-training", action="store_true")
    run.add_argument("--skip-news", action="store_true")
    run.add_argument("--skip-paper-trading", action="store_true")
    run.add_argument("--source", default="manual", choices=["scheduled", "manual", "retry"])
    run.add_argument("--top-k", type=int, default=50)
    run.add_argument("--output-dir", default="outputs")
    run.add_argument("--db-path", default=None)

    sub.add_parser("status", help="Show latest scheduler status")
    sub.add_parser("health", help="Run scheduler health check")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        _json_print(load_latest_job_status("."))
        return 0
    if args.command == "health":
        result = run_health_check(".")
        _json_print(result)
        return 0 if result.get("overall_status") == "success" else 2
    if args.command == "run":
        selected_users = None if args.all_users else (args.user_id or None)
        result = run_scheduled_daily_update(
            trade_date=args.trade_date,
            user_ids=selected_users,
            force=args.force,
            dry_run=args.dry_run,
            skip_training=args.skip_training,
            skip_news=args.skip_news,
            skip_paper_trading=args.skip_paper_trading,
            source=args.source,
            top_k=args.top_k,
            output_dir=args.output_dir,
            db_path=args.db_path,
        )
        _json_print(result.to_dict())
        return 1 if result.overall_status == "failed" else 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
