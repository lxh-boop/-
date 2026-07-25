from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_FILES = [
    ROOT / "app.py",
    ROOT / "app/pages/ai_agent.py",
    ROOT / "app/pages/ai_paper_trading.py",
    ROOT / "app/pages/model_search.py",
    ROOT / "app/pages/system_monitor.py",
    ROOT / "app/classic_services.py",
    ROOT / "app/handoff_ui.py",
    ROOT / "app/reflection_ui.py",
]
CLIENT_FILES = list((ROOT / "client/api").glob("*.py"))
PROHIBITED_FRONTEND_PREFIXES = (
    "application", "agent", "database", "pipelines", "portfolio", "rag",
    "evaluation", "core.llm", "local_config", "scheduler_manager", "server",
)
PROHIBITED_CLIENT_PREFIXES = PROHIBITED_FRONTEND_PREFIXES + ("server",)
LONG_SYNC_MARKERS = {
    "server/api/dispatch.py": (
        '"run_latest_t1_backtest"',
        '"run_paper_trading_from_latest"',
        '"run_ai_news_adjustment_from_latest"',
        '"start_scheduler_manual_run"',
        'operation == "start_rolling_update_job"',
    ),
    "app.py": ("run_latest_t1_backtest(",),
    "app/pages/ai_paper_trading.py": ("run_paper_trading_from_latest(",),
}


def imports_for(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rows: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            rows.append((node.lineno, str(node.module or "")))
    return rows


def direct_io_violations(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ""
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                name = f"{node.func.value.id}.{node.func.attr}"
            else:
                name = node.func.attr
        if name in {"open", "subprocess.run", "subprocess.Popen", "pd.read_csv", "pd.read_json", "joblib.load"}:
            rows.append({"line": node.lineno, "call": name})
    return rows


def main() -> int:
    violations: list[dict[str, Any]] = []
    for path in FRONTEND_FILES:
        if not path.exists():
            violations.append({"file": str(path.relative_to(ROOT)), "issue": "missing_frontend_file"})
            continue
        for line, module in imports_for(path):
            if module.startswith(PROHIBITED_FRONTEND_PREFIXES):
                violations.append({
                    "file": str(path.relative_to(ROOT)), "line": line,
                    "issue": "frontend_imports_backend", "module": module,
                })
        for item in direct_io_violations(path):
            violations.append({"file": str(path.relative_to(ROOT)), "issue": "frontend_direct_io", **item})

    for path in CLIENT_FILES:
        for line, module in imports_for(path):
            if module.startswith(PROHIBITED_CLIENT_PREFIXES):
                violations.append({
                    "file": str(path.relative_to(ROOT)), "line": line,
                    "issue": "client_imports_backend", "module": module,
                })

    required_files = [
        ROOT / "server/task_runtime/store.py",
        ROOT / "server/task_runtime/manager.py",
        ROOT / "server/task_runtime/worker.py",
        ROOT / "server/task_runtime/handlers.py",
        ROOT / "server/api/tasks.py",
        ROOT / "client/api/tasks.py",
        ROOT / "scripts/refactor/stage4_browser_acceptance.py",
        ROOT / "scripts/refactor/stage4_task_smoke.py",
    ]
    for path in required_files:
        if not path.exists():
            violations.append({"file": str(path.relative_to(ROOT)), "issue": "missing_stage4_file"})

    for relative, markers in LONG_SYNC_MARKERS.items():
        path = ROOT / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker in text:
                violations.append({"file": relative, "issue": "long_sync_entry_remains", "marker": marker})

    main_text = (ROOT / "server/api/main.py").read_text(encoding="utf-8")
    if "tasks_router" not in main_text:
        violations.append({"file": "server/api/main.py", "issue": "task_router_missing"})
    if 'version="4.0.0"' not in main_text:
        violations.append({"file": "server/api/main.py", "issue": "api_version_not_stage4"})

    agent_text = (ROOT / "app/pages/ai_agent.py").read_text(encoding="utf-8")
    if ".submit_run(" not in agent_text or "find_latest_task(" not in agent_text:
        violations.append({"file": "app/pages/ai_agent.py", "issue": "agent_task_resume_missing"})
    app_text = (ROOT / "app.py").read_text(encoding="utf-8")
    if "submit_latest_t1_backtest(" not in app_text or "find_active_backtest(" not in app_text:
        violations.append({"file": "app.py", "issue": "backtest_task_resume_missing"})
    paper_text = (ROOT / "app/pages/ai_paper_trading.py").read_text(encoding="utf-8")
    if "submit_paper_trading_update(" not in paper_text or "find_latest_task(" not in paper_text:
        violations.append({"file": "app/pages/ai_paper_trading.py", "issue": "paper_task_resume_missing"})

    transport_text = "\n".join(path.read_text(encoding="utf-8") for path in [ROOT / "server/api/tasks.py", ROOT / "client/api/tasks.py"])
    if "pickle" in transport_text.lower():
        violations.append({"file": "task transport", "issue": "pickle_not_allowed"})

    payload = {
        "stage": 4,
        "checked_frontend_files": [str(path.relative_to(ROOT)) for path in FRONTEND_FILES],
        "checked_client_files": [str(path.relative_to(ROOT)) for path in CLIENT_FILES],
        "violation_count": len(violations),
        "violations": violations,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
