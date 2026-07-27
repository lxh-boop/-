from __future__ import annotations

from typing import Any
from server.api.presenters.common import to_browser_value


def present_settings(value: dict[str, Any]) -> dict[str, Any]:
    output = to_browser_value(value)
    output["read_only"] = bool(value.get("read_only", False))
    return output
