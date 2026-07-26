"""Compose Evidence-Worker results from private atomic-tool observations."""

from __future__ import annotations

from agent.graph.contracts import GraphNodeKind, refs_from
from agent.worker_planning.executor import WorkerPlanExecution

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import safe_public_value


def provided_evidence_result(
    task: GraphAgentTask,
) -> GraphWorkerResult | None:
    evidence_refs = [
        ref
        for ref in task.focus_refs + task.context_refs
        if ref.node_kind == GraphNodeKind.EVIDENCE
    ]
    object_refs = [
        ref
        for ref in task.focus_refs
        if ref.node_kind == GraphNodeKind.OBJECT
    ]
    if not evidence_refs or object_refs:
        return None
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        focus_refs=task.focus_refs,
        summary="已使用指定证据节点作为分析依据。",
        evidence_refs=evidence_refs,
        findings=[
            {
                "kind": "provided_evidence",
                "evidence_refs": [
                    ref.to_dict() for ref in evidence_refs
                ],
            }
        ],
        confidence=1.0,
        metadata={
            "produced_refs": [
                ref.to_dict() for ref in evidence_refs
            ],
            "tool_plan": {
                "execution_mode": "provided_graph_context",
                "tool_call_count": 0,
            },
        },
    )


def compose_evidence_result(
    task: GraphAgentTask,
    execution: WorkerPlanExecution,
) -> GraphWorkerResult:
    if execution.missing_items:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            focus_refs=task.focus_refs,
            summary="证据分析缺少必要的业务上下文。",
            missing_items=execution.missing_items,
            warnings=execution.warnings,
        )

    results: list[dict] = []
    evidence_refs = []
    ingestion_results: list[dict] = []
    tool_observations: list[dict] = []
    for step_id, tool_result in execution.step_results.items():
        tool_observations.append(
            {
                "step_id": step_id,
                "tool_name": tool_result.tool_name,
                "success": tool_result.success,
                "artifact_id": tool_result.artifact_id,
                "error_type": tool_result.error_type,
            }
        )
        results.extend(
            dict(item)
            for item in tool_result.data.get("results") or []
            if isinstance(item, dict)
        )
        evidence_refs.extend(
            refs_from(tool_result.data.get("evidence_refs") or [])
        )
        ingestion_results.extend(
            dict(item)
            for item in tool_result.data.get("ingestion_results") or []
            if isinstance(item, dict)
        )
    findings = [
        {
            "kind": "entity_evidence_result",
            "focus_ref": safe_public_value(item.get("focus_ref")),
            "success": bool(item.get("success")),
            "message": str(item.get("message") or "")[:1200],
            "record_count": len(item.get("records") or []),
            "source_count": len(item.get("sources") or []),
            "data_summary": safe_public_value(item.get("data") or {}),
        }
        for item in results
    ]
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=(
            ResultStatus.COMPLETED
            if execution.success
            else ResultStatus.FAILED
        ),
        focus_refs=task.focus_refs,
        summary=(
            "已完成证据工具计划。"
            if execution.success
            else "证据工具计划执行失败。"
        ),
        findings=findings,
        confidence=0.85 if execution.success else 0.0,
        evidence_refs=refs_from(
            [ref.to_dict() for ref in evidence_refs]
        ),
        warnings=list(
            dict.fromkeys(
                [
                    *execution.warnings,
                    *[
                        warning
                        for result in execution.step_results.values()
                        for warning in [
                            *result.warnings,
                            *result.errors,
                        ]
                    ],
                ]
            )
        ),
        metadata={
            "produced_refs": [
                ref.to_dict() for ref in evidence_refs
            ],
            "ingestion_results": safe_public_value(ingestion_results),
            "tool_plan": {
                "ordered_step_ids": execution.ordered_step_ids,
                "tool_call_count": execution.tool_call_count,
                "observations": tool_observations,
            },
        },
    )


__all__ = [
    "compose_evidence_result",
    "provided_evidence_result",
]
