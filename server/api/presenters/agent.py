from __future__ import annotations

from typing import Any

from server.api.presenters.common import to_browser_value


def present_agent(value: Any) -> Any:
    return to_browser_value(value)
