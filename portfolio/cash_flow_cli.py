from __future__ import annotations

import argparse
import json
import sys

from portfolio.cash_flow import add_cash_flow, cancel_cash_flow, cash_flow_table_rows, list_cash_flows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper trading cash flow CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Add a pending paper cash flow")
    add.add_argument("--user-id", required=True)
    add.add_argument("--type", required=True, choices=["deposit", "withdrawal"])
    add.add_argument("--amount", required=True, type=float)
    add.add_argument("--effective-date", required=True)
    add.add_argument("--reason", default="")
    add.add_argument("--source", default="cli", choices=["app", "cli", "scheduled", "backfill"])
    add.add_argument("--output-dir", default="outputs")
    add.add_argument("--db-path", default=None)

    list_cmd = sub.add_parser("list", help="List paper cash flows")
    list_cmd.add_argument("--user-id", required=True)
    list_cmd.add_argument("--output-dir", default="outputs")
    list_cmd.add_argument("--db-path", default=None)

    cancel = sub.add_parser("cancel", help="Cancel a pending paper cash flow")
    cancel.add_argument("--cash-flow-id", required=True)
    cancel.add_argument("--user-id", default=None)
    cancel.add_argument("--output-dir", default="outputs")
    cancel.add_argument("--db-path", default=None)
    return parser


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "add":
        flow = add_cash_flow(
            user_id=args.user_id,
            flow_type=args.type,
            amount=args.amount,
            effective_date=args.effective_date,
            reason=args.reason,
            source=args.source,
            db_path=args.db_path,
            output_dir=args.output_dir,
        )
        _print(flow.to_dict())
        return 0
    if args.command == "list":
        _print(cash_flow_table_rows(list_cash_flows(args.user_id, db_path=args.db_path, output_dir=args.output_dir)))
        return 0
    if args.command == "cancel":
        flow = cancel_cash_flow(
            args.cash_flow_id,
            user_id=args.user_id,
            db_path=args.db_path,
            output_dir=args.output_dir,
        )
        _print(flow.to_dict())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
