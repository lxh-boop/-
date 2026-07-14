from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from evaluation.system_monitor import collect_and_store_system_monitor_snapshot


def _json_default(value: Any) -> str:
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect a read-only system monitor snapshot.")
    parser.add_argument("--db-path", default="data/agent_quant.db")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--thresholds-path", default="configs/system_monitor_thresholds.json")
    parser.add_argument("--report-path", default="")
    args = parser.parse_args(argv)

    result = collect_and_store_system_monitor_snapshot(
        db_path=args.db_path,
        user_id=args.user_id,
        trade_date=args.trade_date or None,
        output_dir=args.output_dir,
        thresholds_path=args.thresholds_path,
    )
    payload = result.to_dict()
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    if args.report_path:
        path = Path(args.report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
