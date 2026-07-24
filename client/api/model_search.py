from __future__ import annotations
from typing import Any
from client.api.base import call_operation, load_bootstrap

_BOOTSTRAP = load_bootstrap("model-search")
globals().update(_BOOTSTRAP)


def _remote(name: str):
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return call_operation("model-search", name, *args, **kwargs)
    wrapper.__name__ = name
    return wrapper

for _name in [
    "format_strategy_option",
    "load_daily_returns_for_strategy",
    "load_model_discovery_report",
    "load_selected_strategy",
    "load_table_file",
    "make_strategy_from_row",
    "resolve_output_path",
    "save_selected_strategy",
]:
    globals()[_name] = _remote(_name)

__all__ = [name for name in globals() if not name.startswith("_")]
