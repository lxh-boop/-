from __future__ import annotations

from typing import Any

from application.use_cases.memory_queries import (
    get_memory_summary,
    search_memory,
)


def execute_memory_search_tool(
    args: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Adapt Agent arguments to the read-only memory-search use case."""

    output_dir = context.get("output_dir") or args.get("output_dir") or "outputs"
    user_id = str(args.get("user_id") or context.get("user_id") or "default")
    query = str(args.get("query") or "")
    raw_memory_types = args.get("memory_types") or args.get("memory_type") or []
    if isinstance(raw_memory_types, str):
        raw_memory_types = [raw_memory_types]
    result = search_memory(
        user_id=user_id,
        query=query,
        output_dir=output_dir,
        memory_types=list(raw_memory_types) if isinstance(raw_memory_types, list) else [],
        topics=list(args.get("topics") or []),
        stock_codes=list(args.get("stock_codes") or []),
        task_type=str(args.get("task_type") or "memory_search"),
        candidate_top_n=int(args.get("candidate_top_n") or args.get("top_n") or 40),
        relevance_threshold=float(args.get("relevance_threshold") or 0.42),
        token_budget=int(args.get("token_budget") or 600),
    )
    payload = result.to_dict()
    payload.update({
        "tool_name": "memory.search",
        "sources": [],
        "metadata": {"read_only": True, "store": "outputs/memory/memory_store.sqlite"},
    })
    return payload


def execute_memory_summary_tool(
    args: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Adapt Agent arguments to the read-only memory-summary use case."""

    output_dir = context.get("output_dir") or args.get("output_dir") or "outputs"
    user_id = str(args.get("user_id") or context.get("user_id") or "default")
    payload = get_memory_summary(
        user_id=user_id,
        output_dir=output_dir,
    ).to_dict()
    payload.update({
        "tool_name": "memory.get_summary",
        "sources": [],
        "metadata": {"read_only": True, "store": "outputs/memory/memory_store.sqlite"},
    })
    return payload


__all__ = ["execute_memory_search_tool", "execute_memory_summary_tool"]
