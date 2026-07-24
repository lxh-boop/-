from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UI_FILES = [
    PROJECT_ROOT / "app.py",
    PROJECT_ROOT / "app" / "pages" / "ai_agent.py",
    PROJECT_ROOT / "app" / "pages" / "ai_paper_trading.py",
    PROJECT_ROOT / "app" / "pages" / "model_search.py",
    PROJECT_ROOT / "app" / "pages" / "system_monitor.py",
]

ALLOWED_IMPORT_PREFIXES = (
    "__future__",
    "application",
    "app.components",
    "app.display_labels",
    "app.pages",
    "datetime",
    "json",
    "os",
    "pandas",
    "pathlib",
    "plotly",
    "re",
    "streamlit",
    "time",
    "typing",
    "uuid",
)

FORBIDDEN_CALL_TEXT = (
    "pd.read_csv(",
    ".read_text(",
    ".write_text(",
    "subprocess.Popen(",
    "AgentRepository(",
    "run_agent_request(",
    "execute_confirmed_plan_v2(",
    "execute_tool(",
)

# These call names are allowed only through an Application Service import.
APPLICATION_EXCEPTIONS = {
    "app/pages/ai_paper_trading.py": {
        "execute_confirmed_plan_v2(",
        "execute_tool(",
    },
}


def module_imports(tree: ast.AST) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.extend((node.lineno, item.name) for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            rows.append((node.lineno, node.module or ""))
    return rows


def main() -> int:
    violations: list[dict[str, object]] = []
    checked: list[str] = []

    for path in UI_FILES:
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        checked.append(relative)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))

        for line, module in module_imports(tree):
            if not module.startswith(ALLOWED_IMPORT_PREFIXES):
                violations.append(
                    {
                        "file": relative,
                        "line": line,
                        "type": "forbidden_import",
                        "value": module,
                    }
                )

        exceptions = APPLICATION_EXCEPTIONS.get(relative, set())
        for marker in FORBIDDEN_CALL_TEXT:
            if marker in exceptions:
                continue
            if marker in source:
                violations.append(
                    {
                        "file": relative,
                        "line": 0,
                        "type": "forbidden_direct_call",
                        "value": marker,
                    }
                )

    app_source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8-sig")
    for obsolete in (
        'if selected_home_section == "RAG 检索":',
        'if selected_home_section == "AI 解释":',
    ):
        if obsolete in app_source:
            violations.append(
                {
                    "file": "app.py",
                    "line": 0,
                    "type": "obsolete_page_branch",
                    "value": obsolete,
                }
            )

    required = [
        "application/contracts.py",
        "application/agent_service.py",
        "application/dashboard_service.py",
        "application/handoff_service.py",
        "application/model_search_service.py",
        "application/paper_profile_service.py",
        "application/paper_trading_service.py",
        "application/reflection_service.py",
        "application/system_monitor_service.py",
    ]
    for item in required:
        if not (PROJECT_ROOT / item).exists():
            violations.append(
                {
                    "file": item,
                    "line": 0,
                    "type": "missing_application_service",
                    "value": item,
                }
            )

    application_files = sorted((PROJECT_ROOT / "application").glob("*.py"))
    for path in application_files:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        for line, module in module_imports(tree):
            if module == "streamlit" or module.startswith("streamlit."):
                violations.append(
                    {
                        "file": relative,
                        "line": line,
                        "type": "application_depends_on_streamlit",
                        "value": module,
                    }
                )

    report = {
        "stage": 2,
        "checked_files": checked,
        "violation_count": len(violations),
        "violations": violations,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
