from __future__ import annotations

from pathlib import Path

import yaml

from agent.tool_adapter import safe_read_csv, safe_read_json
from application.support.backtest_display import build_display_date_options
from application.support.model_search_results import BACKTEST_DISCLAIMER, load_table_file
from server.api.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_streamlit_and_python_client_are_removed() -> None:
    for relative in (
        "app.py",
        "app",
        "client",
        "requirements-compose-streamlit.txt",
        "docker-compose.react-preview.yml",
    ):
        assert not (ROOT / relative).exists(), relative


def test_final_compose_has_only_api_and_frontend() -> None:
    source = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    compose = yaml.safe_load(source)
    assert set((compose or {}).get("services") or {}) == {"api", "frontend"}
    assert "${STOCK_APP_WEB_PORT:-3000}:80" in source
    assert "streamlit" not in source.lower()
    assert "react-preview" not in source.lower()


def test_backend_helpers_are_application_owned() -> None:
    assert callable(safe_read_csv)
    assert callable(safe_read_json)
    assert callable(build_display_date_options)
    assert "不构成投资建议" in BACKTEST_DISCLAIMER
    dashboard = (ROOT / "application/dashboard_service.py").read_text(encoding="utf-8")
    model_search = (ROOT / "application/model_search_service.py").read_text(encoding="utf-8")
    tool_adapter = (ROOT / "agent/tool_adapter.py").read_text(encoding="utf-8")
    combined = dashboard + model_search + tool_adapter
    assert "app.services" not in combined
    assert "client.api" not in combined


def test_final_openapi_keeps_stage6_routes() -> None:
    paths = create_app().openapi()["paths"]
    assert "/api/v1/health" in paths
    assert "/api/v1/tasks" in paths
    assert "/api/v1/web/dashboard/summary" in paths
    assert "/api/v1/web/paper-trading/summary" in paths
    assert "/api/v1/web/agent/sessions" in paths


def test_migrated_model_search_loader_works_without_ui_package(tmp_path: Path) -> None:
    csv_path = tmp_path / "search.csv"
    csv_path.write_text("run_id,model_name,topk\nr1,model-a,10\n", encoding="utf-8")
    frame = load_table_file(csv_path)
    assert frame.to_dict("records") == [{"run_id": "r1", "model_name": "model-a", "topk": 10}]
