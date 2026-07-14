from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.runtime_fault_injection import run_runtime_fault_injection_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run runtime reliability fault-injection simulations.")
    parser.add_argument("--task-count", type=int, default=10)
    parser.add_argument("--report-path", default="")
    args = parser.parse_args(argv)
    report = run_runtime_fault_injection_suite(task_count=args.task_count)
    if args.report_path:
        path = Path(args.report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("all_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
