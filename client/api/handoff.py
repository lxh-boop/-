from __future__ import annotations
from typing import Any
from client.api.base import call_operation

def build_handoff_safe_summary(*args: Any, **kwargs: Any) -> Any:
    return call_operation("handoff", "build_handoff_safe_summary", *args, **kwargs)

def format_handoff_caption(*args: Any, **kwargs: Any) -> Any:
    return call_operation("handoff", "format_handoff_caption", *args, **kwargs)

def build_handoff_health_summary(*args: Any, **kwargs: Any) -> Any:
    return call_operation("handoff", "build_handoff_health_summary", *args, **kwargs)
