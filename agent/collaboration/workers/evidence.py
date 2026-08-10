"""Execute W01's high-level task through its private Tool DAG runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.graph.contracts import GraphNodeKind
from agent.tool_dag import WorkerToolDagRuntime

from ..completion import build_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .common import contract_acceptance_rules, contract_output_slots, execution_safe_value, safe_public_value

_CANONICAL_EVIDENCE_SLOT = "entity_external_evidence"
_SOURCE_RECORDS_SLOT = "evidence_source_records"
_EVIDENCE_VIEW_PREFIX = "evidence."
_EVIDENCE_VIEW_SOURCE_ALIASES: dict[str, set[str]] = {
    "news": {"news_and_announcements"},
    "research": {"rag_evidence"},
}
_SOURCE_INDEX_FIELDS = (
    "canonical_id",
    "source_ids",
    "retrieved_by",
    "news_id",
    "source_id",
    "graph_evidence_key",
    "chunk_id",
    "source_type",
    "provider_type",
    "source",
    "title",
    "section_title",
    "publish_time",
    "trade_date",
    "date",
    "url",
    "score",
    "mapping_confidence",
    "merged_record_count",
)

# Worker-to-Worker canonical evidence is an analysis transport contract, not a
# dump of the private Tool result.  Preserve stable identity/provenance and
# business-relevant metadata, but normalize all body variants to one bounded
# text field.  The complete Tool result remains private to W01's Tool DAG.
_CANONICAL_RECORD_FIELDS = (
    "canonical_id",
    "source_ids",
    "retrieved_by",
    "news_id",
    "source_id",
    "graph_evidence_key",
    "chunk_id",
    "source_type",
    "provider_type",
    "source",
    "title",
    "section_title",
    "publish_time",
    "trade_date",
    "date",
    "url",
    "stock_code",
    "industry",
    "concept",
    "event_type",
    "sentiment",
    "importance_score",
    "is_announcement",
    "relevance_score",
    "mapping_confidence",
    "impact_direction",
    "impact_strength",
    "impact_confidence",
    "score",
    "merged_record_count",
    "content_level",
)
_CANONICAL_TEXT_FIELDS = ("summary", "text", "chunk_text", "content")
_CANONICAL_TEXT_LIMIT_CHARS = 1000


def _bounded_evidence_text(value: Any, *, limit: int = _CANONICAL_TEXT_LIMIT_CHARS) -> tuple[str, bool]:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text, False
    # Keep both the opening context and the tail conclusion instead of silently
    # retaining only the first paragraph.
    tail = max(180, min(300, limit // 3))
    head = max(1, limit - tail - 18)
    return f"{text[:head]} …<truncated>… {text[-tail:]}", True


def _canonical_record(row: dict[str, Any]) -> dict[str, Any]:
    projected = {
        key: execution_safe_value(row.get(key))
        for key in _CANONICAL_RECORD_FIELDS
        if row.get(key) not in (None, "", [], {})
    }
    body_field = ""
    body_value: Any = ""
    for candidate in _CANONICAL_TEXT_FIELDS:
        if row.get(candidate) not in (None, ""):
            body_field = candidate
            body_value = row.get(candidate)
            break
    if body_field:
        original_text = str(body_value or "")
        bounded, truncated = _bounded_evidence_text(original_text)
        projected["text"] = bounded
        projected["text_source_field"] = body_field
        projected["text_original_chars"] = len(original_text)
        if truncated:
            projected["text_truncated"] = True
    return execution_safe_value(projected)


def _compact_deduplication(value: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "policy",
        "raw_record_count",
        "canonical_record_count",
        "duplicate_record_count",
        "duplicate_group_count",
        "cross_source_duplicate_group_count",
        "source_record_counts",
    )
    return execution_safe_value({
        key: value.get(key)
        for key in keep
        if value.get(key) not in (None, "", [], {})
    })


def _canonical_payload(
    *,
    selected_refs: list[Any],
    entity_catalog: list[dict[str, Any]],
    collection_goal: str,
    results: list[dict[str, Any]],
    record_count: int,
    source_count: int,
    deduplication: dict[str, Any],
    coverage: dict[str, Any],
    business_empty: bool,
) -> dict[str, Any]:
    projected_results: list[dict[str, Any]] = []
    truncated_record_count = 0
    for item in results:
        if not isinstance(item, dict):
            continue
        records = [
            _canonical_record(row)
            for row in list(item.get("records") or [])
            if isinstance(row, dict)
        ]
        truncated_record_count += sum(1 for row in records if row.get("text_truncated"))
        projected_results.append({
            "focus_ref": execution_safe_value(item.get("focus_ref") or {}),
            "success": bool(item.get("success", bool(records))),
            "records": records,
            "source_names": [str(value) for value in item.get("source_names") or [] if str(value)],
            "warnings": [str(value) for value in item.get("warnings") or []],
            "errors": [str(value) for value in item.get("errors") or []],
        })
    return execution_safe_value({
        "entity_refs": [ref.to_dict() for ref in selected_refs],
        "entity_catalog": entity_catalog,
        "collection_goal": collection_goal,
        "results": projected_results,
        "record_count": record_count,
        "source_count": source_count,
        "deduplication": _compact_deduplication(deduplication),
        "coverage": coverage,
        "business_empty": business_empty,
        "projection": {
            "kind": "analysis_canonical_evidence",
            "body_policy": "single_bounded_text",
            "text_limit_chars": _CANONICAL_TEXT_LIMIT_CHARS,
            "projected_record_count": sum(len(item.get("records") or []) for item in projected_results),
            "truncated_record_count": truncated_record_count,
        },
    })


def _record_retrieval_sources(row: dict[str, Any]) -> set[str]:
    raw = row.get("retrieved_by")
    if isinstance(raw, (list, tuple, set)):
        return {str(item).strip() for item in raw if str(item).strip()}
    value = str(raw or "").strip()
    return {value} if value else set()


def _source_index_record(row: dict[str, Any]) -> dict[str, Any]:
    """Return provenance/index fields only; never repeat evidence body text."""

    return execution_safe_value({
        key: row.get(key)
        for key in _SOURCE_INDEX_FIELDS
        if row.get(key) not in (None, "", [], {})
    })


def _coverage_for_results(
    *,
    selected_refs: list[Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    required_ids = {str(ref.node_id) for ref in selected_refs if str(getattr(ref, "node_id", ""))}
    covered_ids = {
        str((item.get("focus_ref") or {}).get("node_id") or "")
        for item in results
        if isinstance(item, dict) and list(item.get("records") or [])
    }
    covered_ids.discard("")
    return {
        "required_entity_count": len(required_ids),
        "covered_entity_count": len(covered_ids),
        "missing_entity_ref_ids": sorted(required_ids - covered_ids),
        "coverage_satisfied": required_ids.issubset(covered_ids),
    }


def _source_records_payload(
    *,
    selected_refs: list[Any],
    entity_catalog: list[dict[str, Any]],
    collection_goal: str,
    results: list[dict[str, Any]],
    coverage: dict[str, Any],
    business_empty: bool,
) -> dict[str, Any]:
    indexed_results: list[dict[str, Any]] = []
    record_count = 0
    source_ids: set[str] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        indexed_records = [
            _source_index_record(row)
            for row in list(item.get("records") or [])
            if isinstance(row, dict)
        ]
        record_count += len(indexed_records)
        for row in indexed_records:
            for source_id in row.get("source_ids") or []:
                if str(source_id).strip():
                    source_ids.add(str(source_id).strip())
            for key in ("canonical_id", "news_id", "source_id", "graph_evidence_key", "chunk_id"):
                if str(row.get(key) or "").strip():
                    source_ids.add(str(row.get(key)).strip())
        indexed_results.append({
            "focus_ref": execution_safe_value(item.get("focus_ref") or {}),
            "success": bool(indexed_records),
            "records": indexed_records,
            "source_names": [str(value) for value in item.get("source_names") or [] if str(value)],
            "warnings": [str(value) for value in item.get("warnings") or []],
            "errors": [str(value) for value in item.get("errors") or []],
        })
    return execution_safe_value({
        "entity_refs": [ref.to_dict() for ref in selected_refs],
        "entity_catalog": entity_catalog,
        "collection_goal": collection_goal,
        "results": indexed_results,
        "record_count": record_count,
        "source_count": len(source_ids) or record_count,
        "coverage": coverage,
        "business_empty": business_empty,
        "projection": "provenance_index",
    })


def _view_sources(slot_id: str) -> set[str]:
    suffix = slot_id[len(_EVIDENCE_VIEW_PREFIX):].strip()
    if not suffix:
        return set()
    return set(_EVIDENCE_VIEW_SOURCE_ALIASES.get(suffix, {suffix}))


def _evidence_view_payload(
    *,
    slot_id: str,
    selected_refs: list[Any],
    entity_catalog: list[dict[str, Any]],
    collection_goal: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    allowed_sources = _view_sources(slot_id)
    view_results: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        selected_records: list[dict[str, Any]] = []
        for row in list(item.get("records") or []):
            if not isinstance(row, dict):
                continue
            retrieved_by = _record_retrieval_sources(row)
            if allowed_sources and retrieved_by.intersection(allowed_sources):
                selected_records.append(_canonical_record(row))
                for source_name in retrieved_by.intersection(allowed_sources):
                    source_counts[source_name] = source_counts.get(source_name, 0) + 1
        view_results.append({
            "focus_ref": execution_safe_value(item.get("focus_ref") or {}),
            "success": bool(selected_records),
            "message": str(item.get("message") or ""),
            "records": selected_records,
            "sources": [_source_index_record(row) for row in selected_records],
            "source_names": sorted(allowed_sources.intersection({
                str(value) for value in item.get("source_names") or [] if str(value)
            })),
            "warnings": [str(value) for value in item.get("warnings") or []],
            "errors": [str(value) for value in item.get("errors") or []],
        })
    record_count = sum(len(item.get("records") or []) for item in view_results)
    source_count = sum(len(item.get("sources") or []) for item in view_results)
    coverage = _coverage_for_results(selected_refs=selected_refs, results=view_results)
    return execution_safe_value({
        "entity_refs": [ref.to_dict() for ref in selected_refs],
        "entity_catalog": entity_catalog,
        "collection_goal": collection_goal,
        "view_slot": slot_id,
        "retrieval_sources": sorted(allowed_sources),
        "results": view_results,
        "record_count": record_count,
        "source_count": source_count,
        "deduplication": {
            "policy": "canonical_collection_source_view",
            "canonical_record_count": record_count,
            "source_record_counts": source_counts,
        },
        "coverage": coverage,
        "business_empty": record_count == 0,
        "projection": "source_view",
    })


def _semantic_evidence_slots(
    *,
    requested_slots: list[str],
    selected_refs: list[Any],
    entity_catalog: list[dict[str, Any]],
    collection_goal: str,
    results: list[dict[str, Any]],
    record_count: int,
    source_count: int,
    deduplication: dict[str, Any],
    coverage: dict[str, Any],
    business_empty: bool,
) -> dict[str, Any]:
    canonical = _canonical_payload(
        selected_refs=selected_refs,
        entity_catalog=entity_catalog,
        collection_goal=collection_goal,
        results=results,
        record_count=record_count,
        source_count=source_count,
        deduplication=deduplication,
        coverage=coverage,
        business_empty=business_empty,
    )
    slots: dict[str, Any] = {}
    for slot_id in requested_slots:
        if slot_id == _CANONICAL_EVIDENCE_SLOT:
            slots[slot_id] = canonical
        elif slot_id == _SOURCE_RECORDS_SLOT:
            slots[slot_id] = _source_records_payload(
                selected_refs=selected_refs,
                entity_catalog=entity_catalog,
                collection_goal=collection_goal,
                results=results,
                coverage=coverage,
                business_empty=business_empty,
            )
        elif slot_id.startswith(_EVIDENCE_VIEW_PREFIX):
            slots[slot_id] = _evidence_view_payload(
                slot_id=slot_id,
                selected_refs=selected_refs,
                entity_catalog=entity_catalog,
                collection_goal=collection_goal,
                results=results,
            )
    return slots


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
    for index, rule_id in enumerate(contract_acceptance_rules(task)):
        satisfied = flags[index] if index < len(flags) else True
        rows.append({
            "rule_id": str(rule_id),
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
        boundary_id=task.boundary_id,
        worker_objective=task.objective or collection_goal,
        worker_prompt=worker_prompt,
        available_context=available_context,
        required_output_keys=[
            "validated_evidence_collection",
            "results",
            "record_count",
            "source_count",
            "deduplication",
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
    results = execution_safe_value(raw.get("results") or [])
    record_count = int(raw.get("record_count") or 0)
    source_count = int(raw.get("source_count") or 0)
    coverage = safe_public_value(raw.get("coverage") or {})
    deduplication = safe_public_value(raw.get("deduplication") or {})
    business_empty = bool(raw.get("business_empty", record_count == 0))
    coverage_satisfied = bool(coverage.get("coverage_satisfied", True))
    requested_slots = contract_output_slots(task)
    entity_catalog = execution_safe_value(
        task.metadata.get("authoritative_entity_catalog") or []
    )
    semantic_slots = _semantic_evidence_slots(
        requested_slots=requested_slots,
        selected_refs=selected_refs,
        entity_catalog=entity_catalog,
        collection_goal=collection_goal,
        results=results,
        record_count=record_count,
        source_count=source_count,
        deduplication=deduplication,
        coverage=coverage,
        business_empty=business_empty,
    )
    payload = {
        "entity_refs": [ref.to_dict() for ref in selected_refs],
        "entity_catalog": safe_public_value(entity_catalog),
        "collection_goal": collection_goal,
        "results": results,
        "record_count": record_count,
        "source_count": source_count,
        "deduplication": deduplication,
        "coverage": coverage,
        "business_empty": business_empty,
        "write_performed": False,
        "slots": semantic_slots,
        "produced_information_slots": list(semantic_slots),
    }
    warnings = [
        str(item)
        for item in [*(raw.get("warnings") or []), *(raw.get("errors") or [])]
        if str(item).strip()
    ]
    requested_slot_payloads = [
        value for value in semantic_slots.values() if isinstance(value, dict)
    ]
    all_requested_business_empty = bool(requested_slot_payloads) and all(
        bool(value.get("business_empty", False)) for value in requested_slot_payloads
    )
    requested_coverage_satisfied = bool(requested_slot_payloads) and all(
        bool(value.get("business_empty", False))
        or bool((value.get("coverage") or {}).get("coverage_satisfied", True))
        for value in requested_slot_payloads
    )
    if success:
        status = (
            ResultStatus.PARTIAL
            if requested_slot_payloads and not requested_coverage_satisfied
            else ResultStatus.COMPLETED
        )
    else:
        status = ResultStatus.FAILED
    failed_observations = [
        item.to_dict()
        for item in dag_result.node_records
        if not item.success
    ]
    required_slots = requested_slots
    produced_slots = list(semantic_slots)
    all_required_slots_materialized = set(required_slots).issubset(produced_slots)
    if success:
        if all_requested_business_empty and all_required_slots_materialized:
            expected_completed = True
            completion_status = "completed"
            business_status = "empty"
        elif requested_coverage_satisfied and all_required_slots_materialized:
            expected_completed = True
            completion_status = "completed"
            business_status = "sufficient"
        else:
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
                "raw_record_count": int(deduplication.get("raw_record_count") or record_count),
                "canonical_record_count": int(deduplication.get("canonical_record_count") or record_count),
                "duplicate_record_count": int(deduplication.get("duplicate_record_count") or 0),
                "duplicate_group_count": int(deduplication.get("duplicate_group_count") or 0),
                "cross_source_duplicate_group_count": int(deduplication.get("cross_source_duplicate_group_count") or 0),
                "identity_fields": list(deduplication.get("identity_fields") or []),
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
            "deduplication_logged": True,
        },
    )


__all__ = ["run_evidence"]
