from __future__ import annotations

from typing import Any
from server.api.presenters.common import table_payload, to_browser_value


def present_metrics(metrics: Any, selected_strategy: dict[str, Any]) -> dict[str, Any]:
    converted = to_browser_value(metrics)
    return {"metrics": converted if isinstance(converted, dict) else {"value": converted}, "selected_strategy": to_browser_value(selected_strategy)}


def present_catalog(value: dict[str, Any]) -> dict[str, Any]:
    return table_payload(value.get("records"))


def present_search_results(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidates": table_payload(value.get("candidates")),
        "master_backtests": table_payload(value.get("master_backtests")),
        "target_results": table_payload(value.get("target_results")),
        "errors": table_payload(value.get("errors")),
        "selected_strategy": to_browser_value(value.get("selected_strategy") or {}),
        "discovery_report": str(value.get("discovery_report") or ""),
        "read_only": True,
    }
