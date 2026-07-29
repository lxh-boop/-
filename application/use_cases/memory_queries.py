"""Read-only memory use cases shared by Agent and non-Agent callers."""

from __future__ import annotations

from pathlib import Path

from agent.memory.memory_context_bridge import (
    build_memory_store_health_summary,
    get_memory_manager_for_output,
)
from agent.memory.memory_types import MemoryType
from application.contracts import BusinessResult


def search_memory(
    *,
    user_id: str,
    query: str,
    output_dir: str | Path = "outputs",
    memory_types: list[str] | None = None,
    topics: list[str] | None = None,
    stock_codes: list[str] | None = None,
    task_type: str = "memory_search",
    candidate_top_n: int = 40,
    relevance_threshold: float = 0.42,
    token_budget: int = 600,
) -> BusinessResult:
    """Retrieve scoped memory without exposing Agent tool contracts."""

    resolved_types = [
        MemoryType.from_value(item)
        for item in list(memory_types or [])
    ]
    manager = get_memory_manager_for_output(output_dir)
    results = manager.retrieve_for_context(
        user_id=str(user_id or "default"),
        query=str(query or ""),
        memory_types=resolved_types or None,
        topics=list(topics or []),
        stock_codes=list(stock_codes or []),
        task_type=str(task_type or "memory_search"),
        candidate_top_n=int(candidate_top_n),
        relevance_threshold=float(relevance_threshold),
        token_budget=int(token_budget),
    )
    items = list(results.get("items") or [])
    return BusinessResult(
        success=True,
        message="Memory search completed.",
        data={
            "items": items,
            "item_count": len(items),
            "policy": dict(results.get("policy") or {}),
            "diagnostics": dict(results.get("diagnostics") or {}),
            "retrieval_id": str(results.get("retrieval_id") or ""),
            "not_committed": True,
        },
    )


def get_memory_summary(
    *,
    user_id: str,
    output_dir: str | Path = "outputs",
) -> BusinessResult:
    """Read the scoped memory-store health summary."""

    summary = build_memory_store_health_summary(
        user_id=str(user_id or "default"),
        output_dir=Path(output_dir),
    )
    return BusinessResult(
        success=True,
        message="Memory summary loaded.",
        data={**summary, "not_committed": True},
    )


__all__ = ["get_memory_summary", "search_memory"]
