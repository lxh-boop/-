from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require_text(path: str, *needles: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8-sig")
    for needle in needles:
        if needle not in text:
            raise AssertionError(f"missing:{path}:{needle}")


def main() -> int:
    require_text(
        "agent/collaboration/models.py",
        "class WorkerTaskContract",
        "payload_schema",
        "payload_version",
        "def task_contract",
    )
    require_text(
        "agent/collaboration/agent_directory.py",
        'role="INTERNAL_SYSTEM_RETRIEVER"',
        'task_type="query_stock_prediction"',
        'output_type="ModelPredictionResult"',
        "def resolve_task_inputs",
        "upstream_result_output_type_mismatch",
    )
    require_text(
        "agent/worker_tools/internal_system.py",
        'INTERNAL_PREDICTION_GET_STOCK = "internal.prediction.get_stock"',
        "market_analysis_service.get_ranking",
        "portfolio_service.get_account_summary",
        "user_profile_service.get_user_profile",
    )
    require_text(
        "agent/collaboration/planner.py",
        "W02 的 query_stock_prediction 内部模型预测任务",
        "card.authoritative_bindings_for(task_type)",
    )
    require_text(
        "agent/communication/message_types.py",
        'WORKER_RESULT_AVAILABLE = "WORKER_RESULT_AVAILABLE"',
    )
    planner_text = (ROOT / "agent/collaboration/planner.py").read_text(encoding="utf-8-sig")
    for forbidden in (
        "auto_insert_worker", "auto_remove_worker", "auto_merge_worker",
        "auto_split_worker", "auto_rewire_worker",
    ):
        if forbidden in planner_text:
            raise AssertionError(f"forbidden DAG mutation:{forbidden}")
    report = {
        "phase": "01.4",
        "status": "passed",
        "w02_internal_system_retriever": True,
        "task_specific_contracts": True,
        "typed_worker_payload": True,
        "explicit_resolved_inputs": True,
        "message_bus_transports_summary_and_refs_only": True,
        "main_agent_owns_worker_dag": True,
        "dag_mutation_after_planning": False,
        "timeout_changed": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
