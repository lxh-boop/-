from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.collaboration.models import GraphAgentTask, GraphWorkerResult, ResultStatus
from agent.collaboration.runtime_services import CollaborationRuntimeServices
from agent.runtime import AgentRuntimeRecorder, load_run_snapshot
from database.connection import initialize_database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a deterministic Supervisor-Worker Phase 01 runtime acceptance test."
    )
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="sw_phase_01_acceptance_") as temp_dir:
        db_path = Path(temp_dir) / "agent_quant.db"
        initialize_database(db_path)

        recorder = AgentRuntimeRecorder(
            user_id="phase-01-acceptance-user",
            goal="verify worker dag runtime persistence after service restart",
            db_path=db_path,
            session_id="phase-01-acceptance-session",
        )
        services = CollaborationRuntimeServices.from_recorder(
            recorder,
            user_id="phase-01-acceptance-user",
            session_id="phase-01-acceptance-session",
        )

        first = GraphAgentTask(
            task_id="acceptance_task_1",
            run_id=recorder.run_id,
            session_id="phase-01-acceptance-session",
            assigned_agent="PORTFOLIO_ANALYST",
            objective="load portfolio snapshot",
            task_type="load_portfolio_snapshot",
            user_id="phase-01-acceptance-user",
            required_outputs=["portfolio_snapshot"],
        )
        second = GraphAgentTask(
            task_id="acceptance_task_2",
            run_id=recorder.run_id,
            session_id="phase-01-acceptance-session",
            assigned_agent="RISK_MONITOR",
            objective="analyze portfolio risk",
            task_type="analyze_portfolio_risk",
            user_id="phase-01-acceptance-user",
            dependency_task_ids=[first.task_id],
            required_outputs=["risk_summary"],
        )

        services.register_tasks([first, second])
        services.mark_ready(first)
        services.mark_running(first)
        services.record_result(
            first,
            GraphWorkerResult(
                task_id=first.task_id,
                agent_id=first.assigned_agent,
                status=ResultStatus.COMPLETED,
                summary="portfolio snapshot ready",
                confidence=0.95,
                artifact_refs=[{"artifact_id": "artifact://phase-01-acceptance"}],
            ),
        )
        services.mark_ready(second)
        services.mark_running(second)
        services.record_result(
            second,
            GraphWorkerResult(
                task_id=second.task_id,
                agent_id=second.assigned_agent,
                status=ResultStatus.COMPLETED,
                summary="risk analysis ready",
                confidence=0.90,
            ),
        )

        snapshot = load_run_snapshot(db_path, recorder.run_id)
        steps = {item["step_id"]: item for item in snapshot.get("steps", [])}
        checks = {
            "run_id_matches": snapshot.get("run", {}).get("run_id") == recorder.run_id,
            "two_worker_steps_persisted": set(steps) == {first.task_id, second.task_id},
            "first_step_succeeded": steps.get(first.task_id, {}).get("status") == "succeeded",
            "second_step_succeeded": steps.get(second.task_id, {}).get("status") == "succeeded",
            "dependency_persisted": steps.get(second.task_id, {}).get("depends_on_json") == [first.task_id],
            "worker_layer_metadata": steps.get(first.task_id, {}).get("metadata_json", {}).get("runtime_layer") == "worker_dag",
            "terminal_status_recorded": steps.get(second.task_id, {}).get("metadata_json", {}).get("worker_result_status") == "completed",
        }
        passed = all(checks.values())
        result = {
            "success": passed,
            "run_id": recorder.run_id,
            "checks": checks,
            "step_count": len(steps),
            "steps": [
                {
                    "step_id": item.get("step_id"),
                    "status": item.get("status"),
                    "depends_on": item.get("depends_on_json"),
                    "runtime_layer": item.get("metadata_json", {}).get("runtime_layer"),
                    "worker_result_status": item.get("metadata_json", {}).get("worker_result_status"),
                }
                for item in snapshot.get("steps", [])
            ],
        }
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        print(rendered)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
