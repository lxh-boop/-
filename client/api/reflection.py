from __future__ import annotations
from typing import Any
from client.api.base import call_operation

def build_reflection_safe_summary(*args: Any, **kwargs: Any) -> Any:
    return call_operation("reflection", "build_reflection_safe_summary", *args, **kwargs)

def format_reflection_caption(*args: Any, **kwargs: Any) -> Any:
    return call_operation("reflection", "format_reflection_caption", *args, **kwargs)

def build_reflection_health_summary(*args: Any, **kwargs: Any) -> Any:
    return call_operation("reflection", "build_reflection_health_summary", *args, **kwargs)
