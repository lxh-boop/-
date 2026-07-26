"""Execute evidence-domain Worker tasks through private atomic tools.

The Worker consumes resolved object or evidence GraphRefs, chooses one
allowlisted evidence capability, and consumes its normalized result. Provider
dependencies, registration metadata, and graph persistence remain behind the
private tool boundary.
"""

from __future__ import annotations

from pathlib import Path

from agent.graph.contracts import GraphNodeKind, refs_from
from agent.tool_runtime import ToolExecutor
from agent.worker_tools import (
    EVIDENCE_ANALYZE_ENTITIES_TOOL,
    EVIDENCE_RETRIEVE_TOOL,
)

from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .common import safe_public_value


def run_evidence(
    tool_executor: ToolExecutor,
    task: GraphAgentTask,
    query: str,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
) -> GraphWorkerResult:
    evidence_refs = [
        ref
        for ref in task.focus_refs + task.context_refs
        if ref.node_kind == GraphNodeKind.EVIDENCE
    ]
    object_refs = [ref for ref in task.focus_refs if ref.node_kind == GraphNodeKind.OBJECT]
    if evidence_refs and not object_refs:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.COMPLETED,
            focus_refs=task.focus_refs,
            summary="已使用指定新闻或证据节点作为分析原因锚点。",
            evidence_refs=evidence_refs,
            findings=[
                {
                    "kind": "provided_evidence",
                    "evidence_refs": [ref.to_dict() for ref in evidence_refs],
                }
            ],
            confidence=1.0,
            metadata={"produced_refs": [ref.to_dict() for ref in evidence_refs]},
        )
    if not object_refs:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            focus_refs=task.focus_refs,
            summary="缺少已解析的金融对象或指定证据。",
            missing_items=[
                MissingContextItem(
                    key="focus_graph_ref",
                    description="需要明确分析对象或指定新闻的 GraphRef。",
                    expected_format="唯一对象、新闻、公告或研报",
                    reason="Worker 不允许从自由文本重新猜测权威金融实体。",
                    searched_sources=["task.focus_refs", "task.context_refs"],
                )
            ],
        )
    analyze_task_types = {
        "analyze_entity_evidence",
        "compare_entity_evidence",
    }
    tool_name = (
        EVIDENCE_ANALYZE_ENTITIES_TOOL
        if task.task_type in analyze_task_types
        else EVIDENCE_RETRIEVE_TOOL
    )
    arguments = {
        "object_refs": [ref.to_dict() for ref in object_refs],
        "user_id": task.user_id,
    }
    if tool_name == EVIDENCE_RETRIEVE_TOOL:
        arguments.update(
            {
                "query": query or task.objective,
                "top_k": max(1, min(int(default_top_k or 20), 100)),
                "source_task_id": task.task_id,
                "source_agent_id": task.assigned_agent,
                "as_of_time": task.as_of_time,
            }
        )
    tool_result = tool_executor.execute(
        tool_name,
        arguments,
        context={
            "user_id": task.user_id,
            "conversation_id": task.session_id,
            "session_id": task.session_id,
            "run_id": task.run_id,
            "task_id": task.task_id,
            "agent_role": task.assigned_agent,
            "output_dir": output_dir,
            "db_path": db_path,
        },
        agent_type=task.assigned_agent,
    )
    analysis = dict(tool_result.data or {})
    analysis.update(
        {
            "success": tool_result.success,
            "message": tool_result.message,
            "warnings": list(tool_result.warnings or []),
            "errors": list(tool_result.errors or []),
        }
    )
    produced_evidence = refs_from(analysis.get("evidence_refs") or [])
    success = bool(analysis.get("success"))
    findings = []
    for item in analysis.get("results") or []:
        if not isinstance(item, dict):
            continue
        findings.append(
            {
                "kind": "entity_evidence_result",
                "focus_ref": safe_public_value(item.get("focus_ref")),
                "success": bool(item.get("success")),
                "message": str(item.get("message") or "")[:1200],
                "record_count": len(item.get("records") or []),
                "source_count": len(item.get("sources") or []),
                "data_summary": safe_public_value(item.get("data") or {}),
            }
        )
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED if success else ResultStatus.FAILED,
        focus_refs=object_refs,
        summary="已完成金融对象证据读取并写入可追踪金融图。" if success else "未获得可用的金融证据。",
        findings=findings,
        confidence=0.85 if success else 0.0,
        evidence_refs=produced_evidence,
        warnings=[
            str(item)
            for item in [
                *(analysis.get("warnings") or []),
                *(analysis.get("errors") or []),
            ]
            if str(item).strip()
        ],
        metadata={
            "produced_refs": [ref.to_dict() for ref in produced_evidence],
            "ingestion_results": safe_public_value(analysis.get("ingestion_results") or []),
            "tool_execution": {
                "tool_name": tool_result.tool_name,
                "artifact_id": tool_result.artifact_id,
                "error_type": tool_result.error_type,
            },
        },
    )
