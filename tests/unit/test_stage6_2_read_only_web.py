from __future__ import annotations

from server.api.main import create_app
from server.api.presenters.common import table_payload, to_browser_value
from server.api.presenters.settings import present_settings


EXPECTED_READ_ONLY_PATHS = {
    "/api/v1/web/dashboard/summary",
    "/api/v1/web/dashboard/rankings",
    "/api/v1/web/dashboard/model-status",
    "/api/v1/web/dashboard/data-freshness",
    "/api/v1/web/stocks/{stock_code}",
    "/api/v1/web/stocks/{stock_code}/history",
    "/api/v1/web/stocks/{stock_code}/evidence",
    "/api/v1/web/stocks/{stock_code}/explanation",
    "/api/v1/web/models/metrics",
    "/api/v1/web/models/catalog",
    "/api/v1/web/models/search-results",
    "/api/v1/web/backtests",
    "/api/v1/web/backtests/{backtest_id}",
    "/api/v1/web/backtests/{backtest_id}/equity",
    "/api/v1/web/backtests/{backtest_id}/trades",
    "/api/v1/web/backtests/{backtest_id}/predictions",
    "/api/v1/web/news/events",
    "/api/v1/web/news/events/{event_id}",
    "/api/v1/web/settings",
    "/api/v1/web/monitor/summary",
    "/api/v1/web/monitor/services",
    "/api/v1/web/monitor/history",
    "/api/v1/web/monitor/alerts",
}
HTTP_METHODS = {"get", "head", "post", "put", "patch", "delete", "options", "trace"}


def test_stage6_2_web_routes_are_get_only() -> None:
    paths = create_app().openapi().get("paths", {})
    web_paths = {
        str(path): path_item
        for path, path_item in paths.items()
        if str(path).startswith("/api/v1/web")
    }

    missing = EXPECTED_READ_ONLY_PATHS - set(web_paths)
    assert not missing, f"missing stage 6.2 OpenAPI paths: {sorted(missing)}"

    for path in sorted(EXPECTED_READ_ONLY_PATHS):
        path_item = web_paths[path]
        methods = {str(key).lower() for key in path_item if str(key).lower() in HTTP_METHODS}
        assert methods, f"no HTTP method found for {path}"
        assert methods <= {"get", "head"}, f"write method exposed by {path}: {sorted(methods)}"


def test_browser_presenter_removes_secrets_and_paths() -> None:
    value = to_browser_value({
        "stock_code": "000001",
        "api_key": "secret",
        "confirmation_token": "token",
        "db_path": r"D:\stock_daily_app\agent.db",
        "message": r"read D:\stock_daily_app\outputs\x.csv",
        "token_configured": True,
    })
    assert value["stock_code"] == "000001"
    assert "api_key" not in value
    assert "confirmation_token" not in value
    assert "db_path" not in value
    assert "D:" not in value["message"]
    assert value["token_configured"] is True


def test_public_settings_preserves_only_safe_credential_status() -> None:
    value = present_settings({
        "credentials": {
            "tushare_configured": True,
            "llm_configured": False,
            "api_key": "must-not-leak",
            "tushare_token": "must-not-leak",
            "password": "must-not-leak",
        },
        "feature_flags": {"news": True},
    })
    assert value["credentials"] == {
        "tushare_configured": True,
        "llm_configured": False,
    }
    rendered = repr(value)
    assert "must-not-leak" not in rendered
    assert "api_key" not in value["credentials"]
    assert "tushare_token" not in value["credentials"]
    assert "password" not in value["credentials"]


def test_table_payload_is_plain_json_shape() -> None:
    payload = table_payload([{"code": "000001", "score": 0.2}, {"code": "600519", "score": 0.3}])
    assert payload["total"] == 2
    assert payload["records"][0]["code"] == "000001"
    assert {item["key"] for item in payload["columns"]} == {"code", "score"}
