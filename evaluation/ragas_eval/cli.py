from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evaluation.ragas_eval.config import RagasEvalConfig
from evaluation.ragas_eval.runner import RagasEvalRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline RAG/Ragas evaluation.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default="configs/ragas_eval/retrieval_only.yaml")
    parser.add_argument("--experiment-name", default="")
    parser.add_argument("--mode", choices=["retrieval", "answer", "all"], default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case-id", default="")
    parser.add_argument("--output-dir", default=str(Path("outputs") / "ragas_eval"))
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Reserved for future resumable runs; current run preserves completed sample outputs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = RagasEvalConfig.load(args.config)
    if args.experiment_name:
        config.experiment_name = args.experiment_name
    if args.mode:
        config.mode = args.mode
    if args.no_llm:
        config.runtime.no_llm = True

    runner = RagasEvalRunner(config)
    output_dir, summary = runner.run(
        dataset=args.dataset,
        output_dir=args.output_dir,
        mode=config.mode,
        limit=args.limit,
        case_id=args.case_id or None,
        no_llm=args.no_llm,
        fail_fast=args.fail_fast,
    )
    gates = summary.get("quality_gates") or {}
    print(f"Ragas offline evaluation finished: {output_dir}")
    print(f"cases: success={summary.get('success_count')} failure={summary.get('failure_count')}")
    if gates.get("acceptance_eligible") is False:
        print(f"quality_gates: not_eligible ({gates.get('reason') or 'requirements not met'})")
        return 0 if gates.get("dataset_class") == "diagnostic" else 1
    print(f"quality_gates: {'passed' if gates.get('overall_passed') else 'failed'}")
    if gates.get("overall_passed") is False:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
