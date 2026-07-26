from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"

REQUIRED = [
    "frontend/src/api/dashboardApi.ts", "frontend/src/api/stockApi.ts", "frontend/src/api/modelApi.ts",
    "frontend/src/api/backtestApi.ts", "frontend/src/api/newsApi.ts", "frontend/src/api/settingsApi.ts",
    "frontend/src/api/monitorApi.ts", "frontend/src/pages/dashboard/RankingPage.tsx",
    "frontend/src/pages/dashboard/StockDetailPage.tsx", "frontend/src/pages/dashboard/ModelMetricsPage.tsx",
    "frontend/src/pages/dashboard/ModelSearchPage.tsx", "frontend/src/pages/dashboard/BacktestPage.tsx",
    "frontend/src/pages/dashboard/NewsPage.tsx", "frontend/src/pages/dashboard/SettingsPage.tsx",
    "frontend/src/pages/monitor/SystemMonitorPage.tsx", "application/web_read_service.py",
    "server/api/routers/web_dashboard.py", "server/api/routers/web_stocks.py", "server/api/routers/web_models.py",
    "server/api/routers/web_backtests.py", "server/api/routers/web_news.py", "server/api/routers/web_settings.py",
    "server/api/routers/web_monitor.py",
]


def main() -> int:
    violations: list[str] = []
    for item in REQUIRED:
        if not (ROOT / item).exists():
            violations.append(f"required file missing: {item}")

    forbidden = {
        "direct CSV access": re.compile(r"read_csv|\.csv[\"']", re.I),
        "direct SQLite access": re.compile(r"sqlite|database_path|db_path", re.I),
        "server path": re.compile(r"[A-Za-z]:\\"),
        "secret field": re.compile(r"llm_api_key|tushare_token|password|confirmation_token", re.I),
        "write HTTP method": re.compile(r"httpClient\.(post|put|patch|delete)|fetch\([^\n]+method\s*:\s*[\"'](POST|PUT|PATCH|DELETE)", re.I),
    }
    checked = 0
    for path in FRONTEND.rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        checked += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT).as_posix()
        for label, pattern in forbidden.items():
            if label == "write HTTP method" and rel not in {
                "frontend/src/api/webApi.ts",
                "frontend/src/api/dashboardApi.ts",
                "frontend/src/api/stockApi.ts",
                "frontend/src/api/modelApi.ts",
                "frontend/src/api/backtestApi.ts",
                "frontend/src/api/newsApi.ts",
                "frontend/src/api/settingsApi.ts",
                "frontend/src/api/monitorApi.ts",
            }:
                continue
            if pattern.search(text):
                violations.append(f"{rel}: {label}")

    for path in (ROOT / "server/api/routers").glob("web_*.py"):
        if path.name == "web_common.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    method = decorator.func.attr.lower()
                    if method in {"post", "put", "patch", "delete"}:
                        violations.append(f"{path.relative_to(ROOT).as_posix()}: non-read-only route {method.upper()} {node.name}")

    service = (ROOT / "application/web_read_service.py").read_text(encoding="utf-8")
    for marker in ("save_local_config", "collect_and_store_system_monitor_snapshot", "run_latest_t1_backtest", "save_selected_strategy"):
        if marker in service:
            violations.append(f"application/web_read_service.py: forbidden write symbol {marker}")

    main_text = (ROOT / "server/api/main.py").read_text(encoding="utf-8")
    for marker in ("web_dashboard_router", "web_stocks_router", "web_models_router", "web_backtests_router", "web_news_router", "web_settings_router", "web_monitor_router"):
        if marker not in main_text:
            violations.append(f"server/api/main.py: missing router {marker}")

    report = {"stage": "6.2", "checked_frontend_files": checked, "required_files": len(REQUIRED), "violation_count": len(violations), "violations": violations}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
