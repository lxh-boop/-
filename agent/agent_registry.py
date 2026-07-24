"""Single Main-Agent registry for the Neo4j financial-graph runtime."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def get_agent_registry() -> dict[str, Any]:
    return {
        "financial_graph_agent": {
            "entry": "agent.executor.run_agent_request",
            "public_identity_contract": "GraphRef",
            "worker_task_contract": "graph_agent_task.v1",
            "worker_result_contract": "graph_worker_result.v1",
        }
    }


def route_agent(query: str) -> str:
    del query
    return "financial_graph_agent"


def answer_with_registry(
    query: str,
    user_id: str = "default",
    graph_refs: list[dict[str, Any]] | None = None,
    as_of_time: str | None = None,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    top_k: int = 5,
    **kwargs: Any,
) -> dict[str, Any]:
    from agent.executor import run_agent_request

    context = dict(kwargs.pop("decomposition_context", {}) or {})
    if graph_refs:
        context["graph_refs"] = [dict(item) for item in graph_refs if isinstance(item, dict)]
    if as_of_time:
        context["as_of_time"] = str(as_of_time)
    return run_agent_request(
        query,
        user_id=user_id,
        output_dir=output_dir,
        db_path=db_path,
        top_k=top_k,
        decomposition_context=context,
        **kwargs,
    )


__all__ = ["answer_with_registry", "get_agent_registry", "route_agent"]
