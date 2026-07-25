from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DISPATCH = ROOT / "server/api/dispatch.py"
OUTPUT = ROOT / "contracts/stage6/operation-contract.generated.json"

SET_NAMES = {
    "dashboard": ["DASHBOARD_FUNCTIONS", "DASHBOARD_METHODS"],
    "agent": ["AGENT_UTILITY_FUNCTIONS", "AGENT_SERVICE_METHODS", "STRATEGY_PROPOSAL_METHODS"],
    "paper-trading": ["PAPER_FUNCTIONS"],
    "paper-profile": ["PAPER_PROFILE_FUNCTIONS"],
    "model-search": ["MODEL_FUNCTIONS"],
    "system-monitor": ["MONITOR_FUNCTIONS"],
    "handoff": ["HANDOFF_FUNCTIONS"],
    "reflection": ["REFLECTION_FUNCTIONS"],
}


def main() -> int:
    tree = ast.parse(DISPATCH.read_text(encoding="utf-8"))
    values: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        try:
            value = ast.literal_eval(node.value)
        except Exception:
            continue
        if isinstance(value, set):
            values[node.targets[0].id] = sorted(str(item) for item in value)

    domains: dict[str, list[str]] = {}
    for domain, names in SET_NAMES.items():
        if domain == "agent":
            operations = set(values.get("AGENT_UTILITY_FUNCTIONS", []))
            operations.update(f"service.{item}" for item in values.get("AGENT_SERVICE_METHODS", []))
            operations.update(f"strategy_proposal.{item}" for item in values.get("STRATEGY_PROPOSAL_METHODS", []))
            operations.update({"trace_event", "trace_exception"})
        else:
            operations = {item for name in names for item in values.get(name, [])}
        if domain == "dashboard":
            operations.update({"validate_llm_connection", "create_scheduler", "get_scheduler_jobs", "set_daily_retrain_job"})
        domains[domain] = sorted(operations)

    payload = {
        "contract_version": "stage6.generated",
        "api_version": "v1",
        "response_envelope": ["success", "data", "error", "request_id"],
        "domains": domains,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
