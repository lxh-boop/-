"""Execute W01's high-level task through its private Tool DAG runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.graph.contracts import GraphNodeKind
from agent.tool_dag import WorkerToolDagRuntime

from ..completion import build_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .common import safe_public_value


def _final_data(tool_dag_result: Any) -> dict[str, Any]:
    """Return the validated finalizer payload without exposing private Tool ids."""

    for result in list(getattr(tool_dag_result, "final_results", []) or []):
        data = dict(getattr(result, "data", {}) or {})
        if data.get("validated_evidence_collection") is True:
            return data
    return {}


def _criterion_rows(
    task: GraphAgentTask,
    *,
    results_structured: bool,
    empty_handled_without_fabrication: bool,
    no_database_write: bool,
    source_refs: list[str],
) -> list[dict[str, Any]]:
    flags = [results_structured, empty_handled_without_fabrication, no_database_write]
    reasons = [
        "Tool DAG returned a validated per-entity evidence collection.",
        "Empty evidence is represented as an explicit business-empty result without fabricated records.",
        "The evidence Worker and all selected tools are read-only.",
    ]
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(task.completion_contract.get("criteria") or []):
        satisfied = flags[index] if index < len(flags) else False
        rows.append({
            "criterion_id": str(item.get("criterion_id") or ""),
            "satisfied": bool(satisfied),
            "reason": reasons[index] if index < len(reasons) else "No Worker-owned evaluation was supplied.",
            "source_refs": list(source_refs if satisfied else []),
        })
    return rows


def run_evidence(
    tool_dag_runtime: WorkerToolDagRuntime,
    task: GraphAgentTask,
    query: str,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    *,
    worker_prompt: str,
    allowed_tool_names: list[str],
) -> GraphWorkerResult:
    if task.task_type != "collect_external_evidence":
        raise ValueError(f"unsupported_evidence_task:{task.task_type}")

    requested_ref_ids = {
        str(item) for item in task.args.get("entity_ref_ids") or [] if str(item).strip()
    }
    selected_refs = [
        ref
        for ref in task.focus_refs + task.context_refs
        if ref.node_kind == GraphNodeKind.OBJECT
        and (not requested_ref_ids or ref.node_id in requested_ref_ids)
    ]
    collection_goal = str(
        task.args.get("collection_goal") or query or task.objective
    ).strip()
    if not selected_refs:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            output_type="EvidenceCollectionResult",
            payload_schema="evidence_collection_result.v1",
            payload=None,
            data=None,
            error=None,
            focus_refs=task.focus_refs,
            summary="缺少已解析并锁定的金融实体集合。",
            missing_items=[
                MissingContextItem(
                    key="entity_refs",
                    description="需要一个或多个权威金融实体 GraphRef。",
                    expected_format="GraphRef 集合，集合可以只包含一个元素",
                    reason="W01 不允许根据自由文本重新猜测实体。",
                    searched_sources=["task.focus_refs", "task.context_refs"],
                )
            ],
        )
    if not collection_goal:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            output_type="EvidenceCollectionResult",
            payload_schema="evidence_collection_result.v1",
            payload=None,
            data=None,
            error=None,
            focus_refs=selected_refs,
            summary="缺少外部证据收集目标。",
            missing_items=[
                MissingContextItem(
                    key="collection_goal",
                    description="需要说明要收集的外部证据范围。",
                    expected_format="自然语言证据收集目标",
                    searched_sources=["task.args.collection_goal", "current_user_request"],
                )
            ],
        )

    top_k = max(1, min(int(task.args.get("top_k") or default_top_k or 20), 100))
    available_context = {
        "object_refs": [ref.to_dict() for ref in selected_refs],
        "required_object_refs": [ref.to_dict() for ref in selected_refs],
        "query": collection_goal,
        "collection_goal": collection_goal,
        "source_scope": [
            str(item) for item in task.args.get("source_scope") or [] if str(item).strip()
        ],
        "time_range": safe_public_value(task.args.get("time_range") or {}),
        "top_k": top_k,
        "as_of_time": str(task.as_of_time or ""),
    }
    execution_context = {
        "user_id": task.user_id,
        "conversation_id": task.session_id,
        "session_id": task.session_id,
        "run_id": task.run_id,
        "task_id": task.task_id,
        "agent_role": task.assigned_agent,
        "output_dir": output_dir,
        "db_path": db_path,
    }
    dag_result = tool_dag_runtime.run(
        worker_task_id=task.task_id,
        worker_role=task.assigned_agent,
        worker_task_type=task.task_type,
        worker_objective=task.objective or collection_goal,
        worker_prompt=worker_prompt,
        available_context=available_context,
        required_output_keys=[
            "validated_evidence_collection",
            "results",
            "record_count",
            "source_count",
            "coverage",
        ],
        completion_criteria=[
            "按实体返回带来源的外部证据集合。",
            "只选择完成当前证据范围所需的私有工具；允许单节点或并行 Tool DAG。",
            "最终结果必须完成去重、排序和实体覆盖校验。",
            "无证据属于业务结果为空，不得补造。",
        ],
        allowed_tool_names=list(allowed_tool_names),
        execution_context=execution_context,
        read_only=True,
        max_replans=1,
    )
    raw = _final_data(dag_result)
    success = bool(dag_result.success and raw)
    results = safe_public_value(raw.get("results") or [])
    record_count = int(raw.get("record_count") or 0)
    source_count = int(raw.get("source_count") or 0)
    coverage = safe_public_value(raw.get("coverage") or {})
    business_empty = bool(raw.get("business_empty", record_count == 0))
    coverage_satisfied = bool(coverage.get("coverage_satisfied", True))
    payload = {
        "entity_refs": [ref.to_dict() for ref in selected_refs],
        "entity_catalog": safe_public_value(
            task.metadata.get("authoritative_entity_catalog") or []
        ),
        "collection_goal": collection_goal,
        "results": results,
        "record_count": record_count,
        "source_count": source_count,
        "coverage": coverage,
        "business_empty": business_empty,
        "write_performed": False,
    }
    warnings = [
        str(item)
        for item in [*(raw.get("warnings") or []), *(raw.get("errors") or [])]
        if str(item).strip()
    ]
    if success:
        status = ResultStatus.PARTIAL if record_count and not coverage_satisfied else ResultStatus.COMPLETED
    else:
        status = ResultStatus.FAILED
    failed_observations = [
        item.to_dict()
        for item in dag_result.observations
        if not item.success
    ]
    required_slots = list(task.completion_contract.get("required_information_slots") or [])
    if success:
        if business_empty:
            produced_slots = required_slots
            expected_completed = True
            completion_status = "completed"
            business_status = "empty"
        elif coverage_satisfied:
            produced_slots = required_slots
            expected_completed = True
            completion_status = "completed"
            business_status = "sufficient"
        else:
            produced_slots = [slot for slot in required_slots if slot == "entity_external_evidence"]
            expected_completed = False
            completion_status = "partially_completed"
            business_status = "partial"
        completion = build_completion_report(
            task,
            execution_status="succeeded",
            contract_status="valid",
            business_status=business_status,
            completion_status=completion_status,
            expected_task_completed=expected_completed,
            produced_information_slots=produced_slots,
            criterion_results=_criterion_rows(
                task,
                results_structured=True,
                empty_handled_without_fabrication=True,
                no_database_write=True,
                source_refs=[f"tool_result:{task_id}" for task_id in dag_result.final_output_task_ids],
            ),
            limitations=warnings if not expected_completed else [],
            failure_kind="business_result_insufficient" if not expected_completed else "none",
        )
    else:
        completion = build_completion_report(
            task,
            execution_status="failed",
            contract_status="not_evaluated",
            business_status="unknown",
            completion_status="not_completed",
            expected_task_completed=False,
            produced_information_slots=[],
            criterion_results=_criterion_rows(
                task,
                results_structured=False,
                empty_handled_without_fabrication=False,
                no_database_write=True,
                source_refs=[],
            ),
            limitations=["W01 private Tool DAG did not form a validated EvidenceCollectionResult."],
            failure_kind="tool_execution_failure",
        )
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=status,
        output_type="EvidenceCollectionResult",
        payload_schema="evidence_collection_result.v1",
        payload=payload if success else None,
        data=payload if success else None,
        error=(
            None
            if success
            else {
                "code": "tool_dag_evidence_collection_failed",
                "message": "W01 私有 Tool DAG 未形成有效的证据收集结果。",
                "component": task.assigned_agent,
                "retryable": any(bool(item.get("retryable")) for item in failed_observations),
                "failure_details": failed_observations[:10],
            }
        ),
        focus_refs=selected_refs,
        summary=(
            f"已为 {len(selected_refs)} 个金融实体收集 {record_count} 条外部证据。"
            if success and record_count
            else "外部证据收集已完成，但未检索到符合条件的证据。"
            if success
            else "外部证据 Tool DAG 执行失败。"
        ),
        findings=[
            {
                "kind": "external_evidence_collection",
                "entity_count": len(selected_refs),
                "record_count": record_count,
                "source_count": source_count,
                "business_empty": business_empty,
                "coverage_satisfied": coverage_satisfied,
            }
        ],
        confidence=0.9 if success and record_count else 0.6 if success else 0.0,
        warnings=warnings,
        completion=completion,
        metadata={
            "tool_dag_used": True,
            "tool_task_count": len(dag_result.plan.tasks),
            "tool_dag_batch_count": len(dag_result.execution_batches),
            "tool_dag_replan_count": int(dag_result.replan_count),
            "derived_graph_write": False,
            "database_write": False,
        },
    )


__all__ = ["run_evidence"]
