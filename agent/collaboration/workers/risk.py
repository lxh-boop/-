"""Execute the portfolio-risk Worker task.

The executor extracts an upstream portfolio GraphRef, delegates risk analysis to
the provider facade, and normalizes the result. It does not load graph paths,
generate proposals, or execute portfolio writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.graph.contracts import GraphNodeKind
from agent.graph.provider_adapter import GraphProviderAdapter

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import refs_from_dependencies, safe_public_value


def run_risk(
    provider: GraphProviderAdapter,
    task: GraphAgentTask,
    dependency_results: dict[str, dict[str, Any]],
    output_dir: str | Path,
    db_path: str | Path | None,
) -> GraphWorkerResult:
    portfolio_task_ids = task.input_task_ids("portfolio_state")
    related_task_ids = task.input_task_ids("related_analysis")
    selected_dependencies = {
        task_id: payload
        for task_id, payload in dependency_results.items()
        if not portfolio_task_ids + related_task_ids
        or task_id in set(portfolio_task_ids + related_task_ids)
    }
    refs = refs_from_dependencies(selected_dependencies, kinds={GraphNodeKind.OBJECT})
    portfolio_ref = next(
        (ref for ref in refs if "portfolio" in ref.node_id.lower()),
        None,
    )
    raw = provider.analyze_risk(
        user_id=task.user_id,
        output_dir=output_dir,
        db_path=db_path,
        portfolio_ref=portfolio_ref,
    )
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED if raw.get("success") else ResultStatus.FAILED,
        output_type="PortfolioRiskResult",
        data=(
            {
                "portfolio_task_ids": portfolio_task_ids or list(selected_dependencies.keys()),
                "risk_analysis": safe_public_value(raw.get("data") or {}),
                "records": safe_public_value(raw.get("records") or []),
            }
            if raw.get("success")
            else None
        ),
        error=(
            None
            if raw.get("success")
            else {
                "code": str(raw.get("error_type") or "risk_dependency_failed"),
                "message": str(raw.get("message") or "组合风险分析失败。"),
                "component": "risk_provider",
                "retryable": True,
            }
        ),
        focus_refs=[portfolio_ref] if portfolio_ref else task.focus_refs,
        summary=str(
            raw.get("message")
            or ("已完成组合风险分析。" if raw.get("success") else "组合风险分析失败。")
        ),
        findings=[
            {
                "kind": "portfolio_risk",
                "data": safe_public_value(raw.get("data") or {}),
                "record_count": len(raw.get("records") or []),
            }
        ],
        confidence=0.9 if raw.get("success") else 0.0,
        warnings=[str(item) for item in raw.get("warnings") or []],
    )
