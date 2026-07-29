from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"

REQUIRED = [
    "application/web_paper_trading_service.py",
    "contracts/stage6/web-paper-trading-contract.json",
    "server/api/routers/web_paper_trading.py",
    "server/api/schemas/paper_trading.py",
    "server/api/presenters/paper_trading.py",
    "frontend/src/api/paperTradingApi.ts",
    "frontend/src/api/writeOperationApi.ts",
    "frontend/src/types/paperTrading.ts",
    "frontend/src/pages/paper/PaperTradingPage.tsx",
    "frontend/src/components/paper/UserProfileForm.tsx",
    "frontend/src/components/paper/ProposalPanel.tsx",
    "frontend/src/components/paper/PaperTaskActions.tsx",
    "frontend/src/components/tasks/TaskDrawer.tsx",
]


def main() -> int:
    violations: list[str] = []
    for item in REQUIRED:
        if not (ROOT / item).exists():
            violations.append(f"required file missing: {item}")

    forbidden_patterns = {
        "Windows absolute path": re.compile(r"[A-Za-z]:\\"),
        "direct database access": re.compile(r"sqlite3?|neo4j|database_path|db_path", re.I),
        "credential field": re.compile(r"llm_api_key|tushare_token|neo4j_password|confirmation_token|password\s*[:=]", re.I),
        "direct backend origin": re.compile(r"https?://(?:api|127\.0\.0\.1:8010|localhost:8010)", re.I),
        "direct filesystem access": re.compile(r"read_csv|write_text|read_text|node:fs|from ['\"]fs['\"]", re.I),
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
        if "/operations/" in text and rel.startswith("frontend/src/components/paper/"):
            violations.append(f"{rel}: paper component uses legacy operation RPC")
        if "httpClient." in text and not rel.startswith("frontend/src/api/"):
            violations.append(f"{rel}: component bypasses API client")

    task_store = (ROOT / "frontend/src/stores/taskStore.ts").read_text(encoding="utf-8")
    partial = task_store.split("partialize:", 1)[1] if "partialize:" in task_store else ""
    for marker in ("events: state.events", "task: state.task", "result: state"):
        if marker in partial:
            violations.append(f"taskStore persists business payload: {marker}")
    for marker in ("activeTaskId", "lastSequence"):
        if marker not in partial:
            violations.append(f"taskStore recovery metadata missing: {marker}")

    task_actions = (ROOT / "frontend/src/components/paper/PaperTaskActions.tsx").read_text(encoding="utf-8")
    for task_type in (
        "paper-trading.update",
        "paper-profile.ai-news-adjustment",
        "paper-profile.scheduler-manual",
    ):
        if task_type not in task_actions:
            violations.append(f"paper task action missing: {task_type}")
    if "submitTask" not in task_actions:
        violations.append("paper long tasks do not use Task API")

    proposal_panel = (ROOT / "frontend/src/components/paper/ProposalPanel.tsx").read_text(encoding="utf-8")
    if "paper-trading.backfill" not in proposal_panel or "submitTask" not in proposal_panel:
        violations.append("paper backfill confirmation is not routed through Task Runtime")

    router_path = ROOT / "server/api/routers/web_paper_trading.py"
    tree = ast.parse(router_path.read_text(encoding="utf-8"), filename=str(router_path))
    write_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if decorator.func.attr.lower() in {"post", "put", "patch", "delete"}:
                    write_count += 1
    if write_count < 5:
        violations.append(f"protected write routes incomplete: found {write_count}")

    service = (ROOT / "application/web_paper_trading_service.py").read_text(encoding="utf-8")
    for marker in ("execute_confirmed_plan_v2", "confirmation_text_mismatch", "paper_backfill_requires_task_runtime"):
        if marker not in service:
            violations.append(f"write safety marker missing: {marker}")
    if '"confirmation_token":' in service:
        violations.append("browser proposal summary exposes confirmation_token")

    handlers = (ROOT / "server/task_runtime/handlers.py").read_text(encoding="utf-8")
    manager = (ROOT / "server/task_runtime/manager.py").read_text(encoding="utf-8")
    contract = json.loads((ROOT / "contracts/stage6/task-contract.json").read_text(encoding="utf-8"))
    for task_type in ("paper-trading.backfill",):
        if task_type not in contract.get("task_types", []):
            violations.append(f"task contract missing additive task: {task_type}")
        if f'task_type == "{task_type}"' not in handlers:
            violations.append(f"task handler missing: {task_type}")
        if f'"{task_type}"' not in manager:
            violations.append(f"task allowlist missing: {task_type}")

    main_text = (ROOT / "server/api/main.py").read_text(encoding="utf-8")
    if "web_paper_trading_router" not in main_text:
        violations.append("paper trading router is not registered")

    report = {
        "stage": "6.3",
        "checked_frontend_files": checked,
        "required_files": len(REQUIRED),
        "protected_write_routes": write_count,
        "violation_count": len(violations),
        "violations": violations,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
