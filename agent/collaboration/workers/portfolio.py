"""Execute the portfolio-snapshot Worker task.

The executor asks the provider facade for the current user's authoritative
portfolio snapshot, returns portfolio and holding GraphRefs, and records reusable
session context. It does not calculate risk or create trading proposals.
"""

from __future__ import annotations

from pathlib import Path

from agent.graph.contracts import GraphRef, refs_from
from agent.graph.provider_adapter import GraphProviderAdapter

from ..models import GraphAgentTask, GraphWorkerResult, MemoryUpdate, ResultStatus
from .common import safe_public_value


def run_portfolio(
    provider: GraphProviderAdapter,
    task: GraphAgentTask,
    output_dir: str | Path,
    db_path: str | Path | None,
) -> GraphWorkerResult:
    raw = provider.load_portfolio_snapshot(
        user_id=task.user_id,
        output_dir=output_dir,
        db_path=db_path,
        as_of_time=task.as_of_time,
        source_task_id=task.task_id,
        source_agent_id=task.assigned_agent,
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
                "retryable": True,
            },
            focus_refs=task.focus_refs,
            summary=str(raw.get("message") or "无法读取当前组合。"),
            warnings=[str(item) for item in raw.get("warnings") or []],
        )
    portfolio_ref = GraphRef.from_dict(dict(raw["portfolio_ref"]))
    holding_refs = refs_from(raw.get("holding_refs") or [])
    produced = [portfolio_ref, *holding_refs]
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.PARTIAL if raw.get("unresolved_positions") else ResultStatus.COMPLETED,
        output_type="PortfolioAnalysisResult",
        data={
            "portfolio_ref": portfolio_ref.to_dict(),
            "holding_refs": [ref.to_dict() for ref in holding_refs],
            "portfolio_summary": safe_public_value(raw.get("portfolio") or {}),
            "unresolved_positions": safe_public_value(raw.get("unresolved_positions") or []),
        },
        error=None,
        focus_refs=[portfolio_ref],
        summary="已读取当前组合，并生成 Neo4j 组合快照。",
        findings=[
            {
                "kind": "portfolio_snapshot",
                "portfolio_ref": portfolio_ref.to_dict(),
                "holding_refs": [ref.to_dict() for ref in holding_refs],
                "holding_count": len(holding_refs),
                "unresolved_position_count": len(raw.get("unresolved_positions") or []),
                "portfolio_summary": safe_public_value(raw.get("portfolio") or {}),
            }
        ],
        confidence=1.0 if not raw.get("unresolved_positions") else 0.75,
        warnings=["portfolio_contains_unresolved_positions"] if raw.get("unresolved_positions") else [],
        memory_updates=[
            MemoryUpdate(
                key="active_graph_refs",
                value=[ref.to_dict() for ref in produced],
                value_type="graph_ref_list",
                source_ref=task.task_id,
                confirmed=True,
                confidence=1.0,
                summary="当前组合快照及持仓对象引用。",
            )
        ],
        metadata={
            "produced_refs": [ref.to_dict() for ref in produced],
            "unresolved_positions": safe_public_value(raw.get("unresolved_positions") or []),
        },
    )
