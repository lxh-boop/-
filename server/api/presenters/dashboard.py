from __future__ import annotations

from typing import Any
from server.api.presenters.common import table_payload, to_browser_value


def present_summary(value: dict[str, Any]) -> dict[str, Any]:
    return to_browser_value(value)


def present_ranking_page(value: dict[str, Any]) -> dict[str, Any]:
    table = table_payload(value.get("records"))
    table.update({"total": int(value.get("total") or 0), "offset": int(value.get("offset") or 0), "limit": int(value.get("limit") or 0)})
    table["top15_statistics"] = to_browser_value(value.get("top15_statistics"))
    table["target_validation"] = to_browser_value(value.get("target_validation"))
    return table


def present_freshness(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return to_browser_value(value)
