"""Static architecture checks for the complete Agent-run Markdown archive."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def main() -> int:
    trace_source = read("agent/console_trace.py")
    executor_source = read("agent/executor.py")
    coordinator_source = read("agent/collaboration/coordinator.py")
    planner_source = read("agent/collaboration/planner.py")
    models_source = read("agent/collaboration/models.py")

    checks = {
        "final_snapshot_writer_exists": "def finalize_flow_markdown(" in trace_source,
        "final_snapshot_is_idempotent": "AGENT_RUN_FINAL_SNAPSHOT" in trace_source,
        "worker_dag_section_exists": "## Worker DAG" in trace_source,
        "worker_result_section_exists": "## Worker 执行结果" in trace_source,
        "final_answer_section_exists": "## 最终回答" in trace_source,
        "executor_finalizes_success": executor_source.count("finalize_flow_markdown(") >= 2,
        "coordinator_exports_worker_dag": "worker_dag_snapshot.v1" in coordinator_source,
        "validator_does_not_mutate_dag": '"dag_mutation_after_planning": "forbidden"' in planner_source,
        "final_report_content_is_public": "def _public_result_data(" in models_source
        and 'str(output_type or "") == "FinalReport"' in models_source,
        "private_raw_content_stays_filtered": '"body", "full_text"' in models_source,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise AssertionError("phase_01_2_architecture_failed:" + ",".join(failed))

    print("[OK] Supervisor-Worker phase 01.2 Markdown architecture checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
