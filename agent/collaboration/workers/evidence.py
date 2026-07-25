"""Execute evidence-domain Worker tasks behind the GraphRef boundary.

The executor consumes resolved object or evidence GraphRefs and delegates entity
analysis or evidence retrieval to the provider facade. Evidence retrieval may
ingest evidence into the financial graph; portfolio impact and proposals are
outside this module's responsibility.
"""

from __future__ import annotations

from pathlib import Path

from agent.graph.contracts import GraphNodeKind, refs_from
from agent.graph.provider_adapter import GraphProviderAdapter

from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .common import safe_public_value


def run_evidence(
    provider: GraphProviderAdapter,
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
    if task.task_type == "analyze_entity_evidence":
        analysis = provider.analyze_entities(
            object_refs,
            user_id=task.user_id,
            output_dir=output_dir,
            db_path=db_path,
        )
    else:
        analysis = provider.retrieve_evidence(
            object_refs,
            query=query or task.objective,
            top_k=max(1, min(int(default_top_k or 20), 100)),
            output_dir=output_dir,
            db_path=db_path,
            source_task_id=task.task_id,
            source_agent_id=task.assigned_agent,
            as_of_time=task.as_of_time,
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
        warnings=[str(item) for item in analysis.get("warnings") or []],
        metadata={
            "produced_refs": [ref.to_dict() for ref in produced_evidence],
            "ingestion_results": safe_public_value(analysis.get("ingestion_results") or []),
        },
    )
