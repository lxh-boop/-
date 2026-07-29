from __future__ import annotations

from typing import Any
from server.api.presenters.common import table_payload, to_browser_value


def present_events(value: dict[str, Any]) -> dict[str, Any]:
    table = table_payload(value.get("records"))
    table.update({"total": int(value.get("total") or 0), "offset": int(value.get("offset") or 0), "limit": int(value.get("limit") or 0)})
    return table


def present_event(value: dict[str, Any]) -> dict[str, Any]:
    return to_browser_value(value)
