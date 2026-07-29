from __future__ import annotations

from typing import Any
from server.api.presenters.common import table_payload, to_browser_value


def present_summary(value: dict[str, Any]) -> dict[str, Any]:
    return to_browser_value(value)


def present_services(value: dict[str, Any]) -> dict[str, Any]:
    return to_browser_value(value)


def present_history(value: list[dict[str, Any]]) -> dict[str, Any]:
    return table_payload(value)


def present_alerts(value: list[dict[str, Any]]) -> dict[str, Any]:
    return table_payload(value)
