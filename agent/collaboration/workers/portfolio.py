"""Deprecated read-only portfolio Worker compatibility entry point.

The active W02 runtime is ``workers.internal_system.run_internal_system``.
This module is retained only for older direct imports.  It no longer creates a
Neo4j snapshot; derived graph materialization belongs exclusively to W08.
"""

from __future__ import annotations

from pathlib import Path

from agent.graph.provider_adapter import GraphProviderAdapter

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import safe_public_value


def run_portfolio(
    provider: GraphProviderAdapter,
    task: GraphAgentTask,
    output_dir: str | Path,
    db_path: str | Path | None,
) -> GraphWorkerResult:
    """Read the authoritative portfolio without any derived graph write."""

    raw = provider.read_portfolio_state(
        user_id=task.user_id,
        output_dir=output_dir,
        db_path=db_path,
    )
    if not raw.get("success"):
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.FAILED,
            output_type="PortfolioAnalysisResult",
            data=None,
            error={
                "code": str(raw.get("error_type") or "portfolio_dependency_failed"),
                "message": str(raw.get("message") or "无法读取当前组合。"),
                "component": "portfolio_provider",
                "retryable": bool(raw.get("retryable", False)),
            },
            focus_refs=task.focus_refs,
            summary=str(raw.get("message") or "无法读取当前组合。"),
            warnings=[str(item) for item in raw.get("warnings") or []],
        )

    portfolio = safe_public_value(raw.get("portfolio") or {})
    payload = {
        "portfolio_summary": portfolio,
        "graph_snapshot_materialized": False,
    }
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        output_type="PortfolioAnalysisResult",
        payload_schema="portfolio_analysis_result.v1",
        payload=payload,
        data=payload,
        error=None,
        focus_refs=[],
        summary="已读取当前权威组合状态；未创建或更新 Neo4j 组合快照。",
        metadata={
            "deprecated_entry_point": True,
            "derived_graph_write": False,
            "mutates_business_state": False,
        },
    )


__all__ = ["run_portfolio"]
