from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED = [
    "application/web_agent_service.py",
    "contracts/stage6/web-agent-contract.json",
    "server/api/routers/web_agent.py",
    "server/api/schemas/agent.py",
    "server/api/presenters/agent.py",
    "frontend/src/api/agentApi.ts",
    "frontend/src/types/agent.ts",
    "frontend/src/stores/agentTaskStore.ts",
    "frontend/src/hooks/useAgentTaskEvents.ts",
    "frontend/src/pages/agent/AgentPage.tsx",
    "frontend/src/components/agent/ConversationList.tsx",
    "frontend/src/components/agent/ChatMessageList.tsx",
    "frontend/src/components/agent/ChatComposer.tsx",
    "frontend/src/components/agent/AgentTaskProgress.tsx",
    "frontend/src/components/agent/AgentRunPanel.tsx",
    "frontend/src/components/agent/PendingActionPanel.tsx",
    "frontend/src/components/agent/StrategyProposalPanel.tsx",
]

EXPECTED_PATHS = {
    "/api/v1/web/agent/sessions",
    "/api/v1/web/agent/sessions/{conversation_id}",
    "/api/v1/web/agent/sessions/{conversation_id}/messages",
    "/api/v1/web/agent/sessions/{conversation_id}/finalize-task",
    "/api/v1/web/agent/runs/{run_id}",
    "/api/v1/web/agent/runs/{run_id}/trace",
    "/api/v1/web/agent/runs/{run_id}/reflection",
    "/api/v1/web/agent/runs/{run_id}/handoff",
    "/api/v1/web/agent/runs/{run_id}/react",
    "/api/v1/web/agent/runs/{run_id}/memory",
    "/api/v1/web/agent/pending-actions",
    "/api/v1/web/agent/pending-actions/{plan_id}/confirm",
    "/api/v1/web/agent/pending-actions/{plan_id}/reject",
    "/api/v1/web/agent/sessions/{conversation_id}/strategy-proposal",
}


def main() -> int:
    violations: list[str] = []
    for item in REQUIRED:
        if not (ROOT / item).exists():
            violations.append(f"required file missing: {item}")

    forbidden_patterns = {
        "Windows absolute path": re.compile(r"[A-Za-z]:\\"),
        "direct database access": re.compile(r"sqlite3?|neo4j|database_path|db_path", re.I),
        "credential field": re.compile(
            r"llm_api_key|tushare_token|neo4j_password|confirmation_token|password\s*[:=]",
            re.I,
        ),
        "direct backend origin": re.compile(
            r"https?://(?:api|127\.0\.0\.1:8010|localhost:8010)", re.I
        ),
        "direct filesystem access": re.compile(
            r"read_csv|write_text|read_text|node:fs|from ['\"]fs['\"]", re.I
        ),
    }
    checked = 0
    for path in FRONTEND.rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        checked += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT).as_posix()
        for label, pattern in forbidden_patterns.items():
            if pattern.search(text):
                violations.append(f"{rel}: {label}")
        if "httpClient." in text and not rel.startswith("frontend/src/api/"):
            violations.append(f"{rel}: component bypasses API client")
        if "/operations/" in text and rel.startswith("frontend/src/components/agent/"):
            violations.append(f"{rel}: Agent component uses legacy operation RPC")

    store_path = ROOT / "frontend/src/stores/agentTaskStore.ts"
    store = store_path.read_text(encoding="utf-8") if store_path.exists() else ""
    partial = store.split("partialize:", 1)[1] if "partialize:" in store else ""
    for marker in ("task: state.task", "events: state.events", "result", "error"):
        if marker in partial:
            violations.append(f"agentTaskStore persists business payload: {marker}")
    for marker in ("taskId", "conversationId", "lastSequence"):
        if marker not in partial:
            violations.append(f"agentTaskStore recovery metadata missing: {marker}")

    page_path = ROOT / "frontend/src/pages/agent/AgentPage.tsx"
    page = page_path.read_text(encoding="utf-8") if page_path.exists() else ""
    for marker in (
        "submitTask",
        "task_type: 'agent.run'",
        "listTasks",
        "finalizeTask",
        "acknowledgeTask",
        "cancelTask",
        "useAgentTaskEvents",
    ):
        if marker not in page:
            violations.append(f"Agent page task lifecycle marker missing: {marker}")
    if "window.prompt" in page:
        violations.append("Agent page uses browser prompt instead of application UI")
    if "output_dir" in page:
        violations.append("Agent browser submits a server-owned output path")

    event_hook = (ROOT / "frontend/src/hooks/useAgentTaskEvents.ts").read_text(encoding="utf-8")
    for marker in ("connectTaskEvents", "lastSequence", "appendEvent", "onComplete"):
        if marker not in event_hook:
            violations.append(f"Agent SSE recovery marker missing: {marker}")

    pending = (ROOT / "frontend/src/components/agent/PendingActionPanel.tsx").read_text(encoding="utf-8")
    agent_api = (ROOT / "frontend/src/api/agentApi.ts").read_text(encoding="utf-8")
    for marker in ("confirmation_phrase", "Modal.confirm"):
        if marker not in pending:
            violations.append(f"Agent protected-write marker missing: {marker}")
    if "idempotencyKey" not in agent_api or "idempotency_key" not in agent_api:
        violations.append("Agent API idempotency key is missing")
    if "confirmation_token" in pending:
        violations.append("Agent pending-action UI contains confirmation_token")

    service_path = ROOT / "application/web_agent_service.py"
    service = service_path.read_text(encoding="utf-8") if service_path.exists() else ""
    for marker in (
        "task_owner_mismatch",
        "task_conversation_mismatch",
        "agent_task_not_terminal",
        "confirmation_text_mismatch",
        "request_id_and_idempotency_key_required",
        "control_action",
        "build_message_trace_summary",
        "build_handoff_safe_summary",
        "build_reflection_safe_summary",
        "build_react_safe_summary",
    ):
        if marker not in service:
            violations.append(f"Agent service safety/diagnostic marker missing: {marker}")

    router_path = ROOT / "server/api/routers/web_agent.py"
    write_count = 0
    if router_path.exists():
        tree = ast.parse(router_path.read_text(encoding="utf-8"), filename=str(router_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    if decorator.func.attr.lower() in {"post", "put", "patch", "delete"}:
                        write_count += 1
    if write_count < 7:
        violations.append(f"Agent browser write routes incomplete: found {write_count}")

    main_text = (ROOT / "server/api/main.py").read_text(encoding="utf-8")
    if "web_agent_router" not in main_text:
        violations.append("Agent web router is not registered")

    try:
        from server.api.main import create_app

        paths = create_app().openapi().get("paths", {})
        actual = {path for path in paths if path.startswith("/api/v1/web/agent")}
        missing = sorted(EXPECTED_PATHS - actual)
        if missing:
            violations.append(f"Agent OpenAPI paths missing: {missing}")
    except Exception as exc:
        actual = set()
        violations.append(f"Agent OpenAPI inspection failed: {type(exc).__name__}: {exc}")

    task_api = (ROOT / "server/api/tasks.py").read_text(encoding="utf-8")
    for marker in ('kwargs.setdefault("output_dir", str(OUTPUT_DIR))', 'kwargs["user_id"]', 'kwargs["session_id"]'):
        if marker not in task_api:
            violations.append(f"Agent task server-default marker missing: {marker}")

    task_contract = json.loads((ROOT / "contracts/stage6/task-contract.json").read_text(encoding="utf-8"))
    if "agent.run" not in task_contract.get("task_types", []):
        violations.append("Task contract no longer contains agent.run")

    report = {
        "stage": "6.4",
        "checked_frontend_files": checked,
        "required_files": len(REQUIRED),
        "agent_openapi_paths": len(actual),
        "protected_write_routes": write_count,
        "violation_count": len(violations),
        "violations": violations,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
