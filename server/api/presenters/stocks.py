from __future__ import annotations

from typing import Any
from server.api.presenters.common import table_payload, to_browser_value


def present_detail(value: dict[str, Any]) -> dict[str, Any]:
    return to_browser_value(value)


def present_history(value: dict[str, Any]) -> dict[str, Any]:
    table = table_payload(value.get("records"))
    table["stock_code"] = str(value.get("stock_code") or "").zfill(6)
    return table


def present_evidence(value: dict[str, Any]) -> dict[str, Any]:
    table = table_payload(value.get("records"))
    table.update({"stock_code": str(value.get("stock_code") or "").zfill(6), "query": str(value.get("query") or ""), "warning": value.get("warning")})
    return table


def present_explanation(value: dict[str, Any]) -> dict[str, Any]:
    return to_browser_value(value)
