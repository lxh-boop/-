"""Compatibility façade for the retired keyword Agent registry."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def get_agent_registry() -> dict[str, Any]:
    # Kept only for callers that inspect the historical public symbol.
    return {"main_coordinator": "agent.executor.run_agent_request"}


def route_agent(query: str) -> str:
    del query
    return "main_coordinator"


def answer_with_registry(
    query: str,
    user_id: str = "default",
    trade_date: str | None = None,
    stock_code: str | None = None,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    top_k: int = 5,
    **kwargs: Any,
) -> dict[str, Any]:
    # trade_date/stock_code are retained in the signature only. They are passed
    # as explicit context rather than used for keyword routing.
    from agent.executor import run_agent_request

    decomposition_context = dict(kwargs.pop("decomposition_context", {}) or {})
    if trade_date:
        decomposition_context["trade_date"] = trade_date
    if stock_code:
        decomposition_context["stock_code"] = stock_code
    return run_agent_request(
        query,
        user_id=user_id,
        output_dir=output_dir,
        db_path=db_path,
        top_k=top_k,
        decomposition_context=decomposition_context,
        **kwargs,
    )


__all__ = ["answer_with_registry", "get_agent_registry", "route_agent"]
