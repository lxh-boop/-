from __future__ import annotations

import argparse
import json

from evaluation.agent_harness.case_loader import load_cases
from evaluation.agent_harness.runner import run_harness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Agent end-to-end harness cases through run_agent_request().")
    parser.add_argument("--cases", default="data/evaluation/agent_harness_cases.jsonl")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--llm-api-key", default="")
    parser.add_argument("--llm-base-url", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    report = run_harness(
        cases,
        output_dir=args.output_dir,
        llm_settings={
            "llm_api_key": args.llm_api_key,
            "llm_base_url": args.llm_base_url,
            "llm_model": args.llm_model,
        },
        export=not args.no_export,
    )
    print(json.dumps({"metrics": report["metrics"], "report_path": report["report_path"]}, ensure_ascii=False, indent=2))
    return 0 if report["metrics"].get("case_pass_rate") == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
