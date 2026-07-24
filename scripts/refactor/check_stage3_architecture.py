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
    "application",
    "agent",
    "database",
    "pipelines",
    "portfolio",
    "rag",
    "evaluation",
    "core.llm",
    "local_config",
    "scheduler_manager",
)
PROHIBITED_CLIENT_PREFIXES = PROHIBITED_FRONTEND_PREFIXES + ("server",)


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
        imports = imports_for(path)
        for line, module in imports:
            if module.startswith(PROHIBITED_FRONTEND_PREFIXES):
                violations.append({
                    "file": str(path.relative_to(ROOT)),
                    "line": line,
                    "issue": "frontend_imports_backend",
                    "module": module,
                })
        for item in direct_io_violations(path):
            violations.append({
                "file": str(path.relative_to(ROOT)),
                "issue": "frontend_direct_io",
                **item,
            })

    for path in CLIENT_FILES:
        for line, module in imports_for(path):
            if module.startswith(PROHIBITED_CLIENT_PREFIXES):
                violations.append({
                    "file": str(path.relative_to(ROOT)),
                    "line": line,
                    "issue": "client_imports_backend",
                    "module": module,
                })

    required_files = [
        ROOT / "server/api/main.py",
        ROOT / "server/api/dispatch.py",
        ROOT / "client/api/base.py",
        ROOT / "client/api/dashboard.py",
        ROOT / "client/api/agent.py",
        ROOT / "client/api/paper_trading.py",
        ROOT / "run_agent_api.py",
    ]
    for path in required_files:
        if not path.exists():
            violations.append({"file": str(path.relative_to(ROOT)), "issue": "missing_stage3_file"})

    app_text = (ROOT / "app.py").read_text(encoding="utf-8")
    if "from client.api.dashboard import" not in app_text:
        violations.append({"file": "app.py", "issue": "dashboard_http_client_missing"})
    if "from application.dashboard_service import" in app_text:
        violations.append({"file": "app.py", "issue": "old_application_import_remains"})

    payload = {
        "stage": 3,
        "checked_frontend_files": [str(path.relative_to(ROOT)) for path in FRONTEND_FILES],
        "checked_client_files": [str(path.relative_to(ROOT)) for path in CLIENT_FILES],
        "violation_count": len(violations),
        "violations": violations,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
