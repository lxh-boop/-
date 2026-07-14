from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluation.multi_agent.runner import run_benchmark
from evaluation.multi_agent.scenarios import default_scenarios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the read-only multi-agent benchmark.")
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to outputs/multi_agent_benchmark/<timestamp>.")
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N fixed scenarios.")
    parser.add_argument("--user-id", default="benchmark_user")
    args = parser.parse_args(argv)

    scenarios = default_scenarios()
    if args.limit:
        scenarios = scenarios[: max(1, int(args.limit))]

    result: dict[str, Any] = run_benchmark(
        output_dir=Path(args.output_dir) if args.output_dir else None,
        scenarios=scenarios,
        user_id=args.user_id,
        export=True,
    )
    print(
        json.dumps(
            {
                "metrics": result.get("metrics"),
                "metrics_by_mode": result.get("metrics_by_mode"),
                "artifacts": result.get("artifacts"),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
