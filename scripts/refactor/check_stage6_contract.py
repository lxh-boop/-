from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "contracts/stage6"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))


def source_set_values(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        try:
            value = ast.literal_eval(node.value)
        except Exception:
            continue
        if isinstance(value, set):
            result[node.targets[0].id] = {str(item) for item in value}
    return result


def main() -> int:
    violations: list[str] = []
    operation_contract = load_json("operation-contract.json")
    task_contract = load_json("task-contract.json")
    transport_contract = load_json("transport-contract.json")

    dispatch_sets = source_set_values(ROOT / "server/api/dispatch.py")
    mapping = {
        "dashboard": ["DASHBOARD_FUNCTIONS", "DASHBOARD_METHODS"],
        "agent": ["AGENT_UTILITY_FUNCTIONS", "AGENT_SERVICE_METHODS", "STRATEGY_PROPOSAL_METHODS"],
        "paper-trading": ["PAPER_FUNCTIONS"],
        "paper-profile": ["PAPER_PROFILE_FUNCTIONS"],
        "model-search": ["MODEL_FUNCTIONS"],
        "system-monitor": ["MONITOR_FUNCTIONS"],
        "handoff": ["HANDOFF_FUNCTIONS"],
        "reflection": ["REFLECTION_FUNCTIONS"],
    }
    for domain, frozen in operation_contract["domains"].items():
        if domain == "agent":
            current = set(dispatch_sets.get("AGENT_UTILITY_FUNCTIONS", set()))
            current.update(f"service.{item}" for item in dispatch_sets.get("AGENT_SERVICE_METHODS", set()))
            current.update(f"strategy_proposal.{item}" for item in dispatch_sets.get("STRATEGY_PROPOSAL_METHODS", set()))
            current.update({"trace_event", "trace_exception"})
        else:
            current = {item for name in mapping[domain] for item in dispatch_sets.get(name, set())}
        if domain == "dashboard":
            current.update({"validate_llm_connection", "create_scheduler", "get_scheduler_jobs", "set_daily_retrain_job"})
        missing = sorted(set(frozen) - current)
        if missing:
            violations.append(f"{domain} missing frozen operations: {missing}")

    contracts_source = (ROOT / "server/api/contracts.py").read_text(encoding="utf-8")
    for field in operation_contract["response_envelope"]:
        if f"{field}:" not in contracts_source:
            violations.append(f"OperationResponse field removed: {field}")

    serialization_source = (ROOT / "server/api/serialization.py").read_text(encoding="utf-8")
    for transport_type in transport_contract["types"]:
        if f'"{transport_type}"' not in serialization_source:
            violations.append(f"transport type removed: {transport_type}")

    store_sets = source_set_values(ROOT / "server/task_runtime/store.py")
    active = store_sets.get("ACTIVE_STATUSES", set())
    terminal = store_sets.get("TERMINAL_STATUSES", set())
    if active != set(task_contract["active_statuses"]):
        violations.append(f"ACTIVE_STATUSES changed: {sorted(active)}")
    if terminal != set(task_contract["terminal_statuses"]):
        violations.append(f"TERMINAL_STATUSES changed: {sorted(terminal)}")

    handler_source = (ROOT / "server/task_runtime/handlers.py").read_text(encoding="utf-8")
    for task_type in task_contract["task_types"]:
        if f'task_type == "{task_type}"' not in handler_source:
            violations.append(f"task type removed: {task_type}")

    task_source = (ROOT / "server/api/tasks.py").read_text(encoding="utf-8")
    route_markers = [
        '@router.post("",', '@router.get("",', '@router.get("/{task_id}",',
        '@router.post("/{task_id}/cancel",', '@router.post("/{task_id}/acknowledge",',
        '@router.get("/{task_id}/events")', 'Last-Event-ID', 'event: task-event', 'event: task-complete',
    ]
    for marker in route_markers:
        if marker not in task_source:
            violations.append(f"Task/SSE contract marker removed: {marker}")

    main_source = (ROOT / "server/api/main.py").read_text(encoding="utf-8")
    if 'version="4.0.0"' not in main_source:
        violations.append("FastAPI v1 baseline version changed")
    if '"/api/v1/health"' not in main_source:
        violations.append("health route removed")

    report = {"stage": "6.0", "violation_count": len(violations), "violations": violations}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
