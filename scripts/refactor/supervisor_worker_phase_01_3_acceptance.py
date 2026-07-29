from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.console_trace import (
    finalize_flow_markdown,
    flow_event,
    get_flow_markdown_path,
)
from agent.executor import _empty_failure
from core.llm.contracts import LLMJSONError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = "agent_run_phase_01_3_acceptance"
    with tempfile.TemporaryDirectory() as directory:
        os.environ["AGENT_FLOW_TRACE"] = "1"
        os.environ["AGENT_FLOW_MARKDOWN_DIR"] = directory

        flow_event(
            "GRAPH_REQUEST",
            {"raw_message": "分析600519"},
            run_id=run_id,
        )
        flow_event(
            "WORKER_PLANNING_STARTED",
            {"worker_selection_owner": "main_agent"},
            run_id=run_id,
        )
        flow_event(
            "LOCAL_LLM_REQUEST_STARTED",
            {"stage": "graph_coordinator_planner"},
            run_id=run_id,
        )

        error = LLMJSONError("repair failed")
        error.diagnostics = {
            "primary": {
                "candidate": {
                    "tasks": [
                        {
                            "task_id": "W04_001",
                            "args": {"risk_question": "分析组合风险"},
                            "inputs": {
                                "portfolio_state": {
                                    "from_task_id": "W01_001",
                                    "expected_output_type": "PortfolioAnalysisResult",
                                }
                            },
                        }
                    ]
                },
                "error_message": (
                    "unknown_upstream_input_task@"
                    "$.tasks[0].inputs.portfolio_state[0].from_task_id:W01_001"
                ),
            },
            "repair": {
                "error_message": "unknown_upstream_input_task"
            },
        }
        failure = _empty_failure(
            exc=error,
            query="分析600519",
            user_id="cht",
            session_id="acceptance-session",
            run_id=run_id,
            language="zh",
        )
        flow_event(
            "RUN_FAILED",
            {
                "failure": failure["orchestration"]["failure"],
                "planner": failure["orchestration"]["graph_runtime"]["planner"],
            },
            run_id=run_id,
            level="ERROR",
        )
        finalize_flow_markdown(
            run_id=run_id,
            question="分析600519",
            execution=failure["orchestration"],
            runtime_status="failed",
            success=False,
            final_answer=failure["answer"],
            user_id="cht",
            session_id="acceptance-session",
            language="zh",
        )

        markdown_path = Path(get_flow_markdown_path(run_id))
        text = markdown_path.read_text(encoding="utf-8")
        checks = {
            "run_id_in_filename": run_id in markdown_path.name,
            "live_planning_event_saved": "LOCAL_LLM_REQUEST_STARTED" in text,
            "rejected_candidate_saved": "portfolio_state" in text,
            "validation_error_saved": (
                "unknown_upstream_input_task" in text
            ),
            "failure_classification_saved": "main_agent_planning_failed" in text,
            "neo4j_not_misreported": "请检查 Neo4j" not in failure["answer"],
            "worker_execution_not_claimed": "尚未进入 Worker 执行阶段" in failure["answer"],
        }
        report = {
            "phase": "01.3",
            "status": "passed" if all(checks.values()) else "failed",
            "checks": checks,
            "markdown_name": markdown_path.name,
            "failure_message": failure["answer"],
        }

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
