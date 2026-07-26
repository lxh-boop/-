from __future__ import annotations

from typing import Any
from server.api.presenters.common import table_payload, to_browser_value


def present_list(value: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"backtest_id": "latest", "available": bool(value.get("available")), "metrics": to_browser_value(value.get("metrics") or {})}]


def present_detail(value: dict[str, Any]) -> dict[str, Any]:
    return {"backtest_id": "latest", "available": bool(value.get("available")), "metrics": to_browser_value(value.get("metrics") or {})}


def present_equity(value: dict[str, Any]) -> dict[str, Any]:
    return table_payload(value.get("equity"))


def present_trades(value: dict[str, Any]) -> dict[str, Any]:
    return table_payload(value.get("trades"))


def present_predictions(value: dict[str, Any]) -> dict[str, Any]:
    return table_payload(value.get("predictions"))
