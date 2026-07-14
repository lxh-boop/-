from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from evaluation.news_rag_diagnostics import run_news_rag_diagnostics
from news_db_sync import refresh_and_sync_news_to_agent_db, sync_event_cache_to_agent_db
from universe import get_stock_pool


def _json_default(value: Any) -> str:
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh or resync news events, rebuild RAG indexes, and run diagnostic-only checks."
    )
    parser.add_argument("--db-path", default="data/agent_quant.db")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--token-env", default="TUSHARE_TOKEN")
    parser.add_argument("--from-cache", action="store_true", help="Do not fetch; resync existing news cache only.")
    parser.add_argument("--events-csv", default="", help="Use a specific event CSV instead of fetching or global cache.")
    parser.add_argument("--query", default="")
    parser.add_argument("--stock-code", default="")
    parser.add_argument("--decision-time", default="")
    parser.add_argument("--require-dense", action="store_true")
    parser.add_argument("--report-path", default="")
    args = parser.parse_args(argv)

    stock_pool = get_stock_pool()
    if args.events_csv:
        import pandas as pd

        sync_result = sync_event_cache_to_agent_db(
            stock_pool=stock_pool,
            db_path=args.db_path,
            output_dir=args.output_dir,
            start_date=args.start_date or None,
            end_date=args.end_date or None,
            events=pd.read_csv(args.events_csv, dtype={"code": str}),
        )
    elif args.from_cache:
        sync_result = sync_event_cache_to_agent_db(
            stock_pool=stock_pool,
            db_path=args.db_path,
            output_dir=args.output_dir,
            start_date=args.start_date or None,
            end_date=args.end_date or None,
        )
    else:
        if not args.start_date or not args.end_date:
            raise SystemExit("--start-date and --end-date are required unless --from-cache is used")
        token = args.token or os.getenv(args.token_env, "")
        sync_result = refresh_and_sync_news_to_agent_db(
            token=token or None,
            stock_pool=stock_pool,
            start_date=args.start_date,
            end_date=args.end_date,
            db_path=args.db_path,
            output_dir=args.output_dir,
        )

    diagnostic_report = run_news_rag_diagnostics(
        args.db_path,
        query=args.query,
        stock_code=args.stock_code,
        decision_time=args.decision_time,
        output_dir=args.output_dir,
        rebuild_indexes=True,
        require_dense=args.require_dense,
    )
    payload = {
        "sync_result": sync_result.to_dict(),
        "diagnostic_report": diagnostic_report,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    if args.report_path:
        report_path = Path(args.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
    print(text)
    return 0 if diagnostic_report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
