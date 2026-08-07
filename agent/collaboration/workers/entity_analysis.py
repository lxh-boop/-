"""Analyze financial entities from completed upstream evidence and fact results."""

from __future__ import annotations

import inspect
import json
from typing import Any

from core.llm import LLMService
from core.llm.contracts import LLMJSONError, extract_json_object
from core.llm.prompt_compaction import compact_json_dumps, schema_for_prompt

from ..completion import build_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from ..worker_contracts import array_schema, object_schema, string_schema, validate_schema
from .common import execution_safe_value, safe_public_value
from .slot_inputs import contract_input_slot_ids, slot_envelopes


_CLAIM_LIST_FIELDS = ("facts", "analysis", "uncertainties")


_EVIDENCE_SLOTS = {"entity_external_evidence", "evidence_source_records"}


_MAX_EVIDENCE_RECORDS_PER_ENTITY = 12
_MAX_RECORD_TEXT_CHARS = 700
_MAX_PRIMARY_OUTPUT_TOKENS = 2600
_MAX_REPAIR_OUTPUT_TOKENS = 2200
_MAX_REPAIR_INPUT_CHARS = 12000


def _claim_schema() -> dict[str, Any]:
    return object_schema(
        {
            "claim_id": string_schema(min_length=1, max_length=80),
            "statement": string_schema(min_length=1, max_length=320),
            "source_task_ids": array_schema(
                string_schema(min_length=1, max_length=80), max_items=8
            ),
        },
        required=["claim_id", "statement", "source_task_ids"],
        additional_properties=False,
    )


def _entity_analysis_llm_schema() -> dict[str, Any]:
    claim = _claim_schema()
    return object_schema(
        {
            "entity_refs": array_schema(
                object_schema({}, additional_properties=True), max_items=8
            ),
            "facts": array_schema(claim, max_items=8),
            "analysis": array_schema(claim, max_items=6),
            "uncertainties": array_schema(claim, max_items=4),
            "conclusion": string_schema(max_length=500),
            "source_task_ids": array_schema(
                string_schema(min_length=1, max_length=80), max_items=20
            ),
        },
        required=[
            "entity_refs",
            "facts",
            "analysis",
            "uncertainties",
            "conclusion",
            "source_task_ids",
        ],
        additional_properties=False,
    )


def _resolved_items(
    task: GraphAgentTask,
    resolved_inputs: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Project only contract-declared SlotBinder inputs that are actually present."""

    return slot_envelopes(
        task,
        resolved_inputs,
        include_slots=contract_input_slot_ids(task),
    )


def _trim_text(value: Any, *, limit: int = _MAX_RECORD_TEXT_CHARS) -> str:
    return str(value or "")[:limit]


def _compact_record(row: dict[str, Any]) -> dict[str, Any]:
    """Keep only grounded fields needed for analysis and structured attribution."""

    wanted = (
        "chunk_id",
        "news_id",
        "source_id",
        "source_type",
        "source",
        "title",
        "section_title",
        "publish_time",
        "trade_date",
        "date",
        "url",
        "score",
        "mapping_confidence",
    )
    compact = {
        key: safe_public_value(row.get(key))
        for key in wanted
        if row.get(key) not in (None, "", [], {})
    }
    text = row.get("text") or row.get("content") or row.get("summary")
    if text not in (None, ""):
        compact["text"] = _trim_text(text)
    return compact


def _compact_evidence_payload(payload: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in list(payload.get("results") or [])[:20]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "focus_ref": safe_public_value(item.get("focus_ref") or {}),
                "source_names": [str(value) for value in item.get("source_names") or []][:10],
                "records": [
                    _compact_record(row)
                    for row in list(item.get("records") or [])[:_MAX_EVIDENCE_RECORDS_PER_ENTITY]
                    if isinstance(row, dict)
                ],
                "sources": [
                    _compact_record(row)
                    for row in list(item.get("sources") or [])[:12]
                    if isinstance(row, dict)
                ],
                "warnings": [str(value)[:500] for value in item.get("warnings") or []][:10],
                "errors": [str(value)[:500] for value in item.get("errors") or []][:10],
            }
        )
    return {
        "entity_refs": safe_public_value(payload.get("entity_refs") or []),
        "entity_catalog": safe_public_value(payload.get("entity_catalog") or []),
        "collection_goal": _trim_text(payload.get("collection_goal"), limit=800),
        "results": results,
        "record_count": int(payload.get("record_count") or 0),
        "source_count": int(payload.get("source_count") or 0),
        "deduplication": safe_public_value(payload.get("deduplication") or {}),
        "coverage": safe_public_value(payload.get("coverage") or {}),
        "business_empty": bool(payload.get("business_empty", False)),
    }


def _compact_payload(slot_id: str, payload: Any) -> Any:
    if not isinstance(payload, dict):
        return safe_public_value(payload)
    if slot_id in _EVIDENCE_SLOTS:
        return _compact_evidence_payload(payload)
    # Internal fact results are already structured and normally much smaller.
    encoded = json.dumps(execution_safe_value(payload), ensure_ascii=False, default=str)
    if len(encoded) <= 16000:
        return execution_safe_value(payload)
    return {
        "truncated": True,
        "summary": encoded[:15000],
    }


def _claim_text(item: dict[str, Any]) -> str:
    return str(item.get("statement") or item.get("text") or item.get("summary") or "").strip()


def _claim_source_ids(item: dict[str, Any]) -> list[str]:
    values = item.get("source_task_ids")
    if not isinstance(values, list):
        single = str(item.get("source_task_id") or "").strip()
        values = [single] if single else []
    return [str(value).strip() for value in values if str(value).strip()]


def _authoritative_entity_refs(
    task: GraphAgentTask,
    evidence_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs = [ref.to_dict() for ref in task.focus_refs if getattr(ref, "node_id", "")]
    if refs:
        return safe_public_value(refs)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence_items:
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        for ref in payload.get("entity_refs") or []:
            if not isinstance(ref, dict):
                continue
            node_id = str(ref.get("node_id") or "")
            if node_id and node_id not in seen:
                seen.add(node_id)
                rows.append(safe_public_value(ref))
    return rows


def _authoritative_entity_catalog(
    task: GraphAgentTask,
    evidence_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    catalog = task.metadata.get("authoritative_entity_catalog")
    if isinstance(catalog, list) and all(isinstance(item, dict) for item in catalog):
        return safe_public_value(catalog)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence_items:
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        for descriptor in payload.get("entity_catalog") or []:
            if not isinstance(descriptor, dict):
                continue
            node_id = str(descriptor.get("node_id") or descriptor.get("entity_ref", {}).get("node_id") or "")
            if node_id and node_id not in seen:
                seen.add(node_id)
                rows.append(safe_public_value(descriptor))
    return rows


def _generate_text_no_thinking(
    llm_service: LLMService,
    *,
    stage: str,
    messages: list[dict[str, Any]],
    max_output_tokens: int,
    operation: str,
) -> str:
    """Call generate_text while disabling model thinking when supported.

    V22.0.1 keeps compatibility with older LLMService builds by discovering the
    optional ``disable_thinking`` argument at runtime instead of requiring a core
    LLM service replacement.
    """

    kwargs: dict[str, Any] = {
        "stage": stage,
        "messages": messages,
        "max_output_tokens": max_output_tokens,
        "temperature": 0.0,
        "operation": operation,
    }
    try:
        if "disable_thinking" in inspect.signature(llm_service.generate_text).parameters:
            kwargs["disable_thinking"] = True
    except (TypeError, ValueError):
        pass
    return str(llm_service.generate_text(**kwargs) or "")


def _generate_entity_analysis_json(
    llm_service: LLMService,
    *,
    messages: list[dict[str, Any]],
    output_schema: dict[str, Any],
    validate: Any,
    allowed_source_task_ids: list[str],
    operation: str,
) -> dict[str, Any]:
    """Generate W09 business JSON with one Worker-local structural repair.

    The repair request intentionally does not include the original evidence or
    user task. It receives only the first model output, the validation error, the
    business schema, and the already-authorized source task ids. This prevents
    schema repair from becoming a second full business-analysis pass.
    """

    primary_text = _generate_text_no_thinking(
        llm_service,
        stage="graph_entity_analysis",
        messages=messages,
        max_output_tokens=_MAX_PRIMARY_OUTPUT_TOKENS,
        operation=operation,
    )
    try:
        primary = extract_json_object(primary_text)
        validate(primary)
        return primary
    except Exception as primary_exc:
        repair_request = {
            "task": "repair_existing_json_only",
            "instruction": (
                "Repair only the JSON syntax/shape of invalid_output. Preserve existing claims. "
                "Do not redo the analysis, do not add facts or sources, and do not infer missing content. "
                "If a field was truncated and cannot be recovered from invalid_output, use the smallest valid empty value allowed by the schema."
            ),
            "validation_error": {
                "type": type(primary_exc).__name__,
                "message": str(primary_exc)[:2000],
            },
            "allowed_source_task_ids": allowed_source_task_ids,
            "output_schema": schema_for_prompt(output_schema),
            "invalid_output": primary_text[:_MAX_REPAIR_INPUT_CHARS],
        }
        repair_messages = [
            {
                "role": "system",
                "content": (
                    "You are a JSON structural repair function. Never perform business reasoning. "
                    "Return exactly one complete JSON object and nothing else."
                ),
            },
            {
                "role": "user",
                "content": compact_json_dumps(repair_request),
            },
        ]
        repaired_text = _generate_text_no_thinking(
            llm_service,
            stage="graph_entity_analysis",
            messages=repair_messages,
            max_output_tokens=_MAX_REPAIR_OUTPUT_TOKENS,
            operation="schema_repair_structural_only",
        )
        try:
            repaired = extract_json_object(repaired_text)
            validate(repaired)
            return repaired
        except Exception as repair_exc:
            raise LLMJSONError(
                "W09 local structured-output recovery exhausted: "
                f"primary={type(primary_exc).__name__}:{str(primary_exc)[:800]}; "
                f"repair={type(repair_exc).__name__}:{str(repair_exc)[:800]}"
            ) from repair_exc


def run_entity_analysis(
    llm_service: LLMService,
    task: GraphAgentTask,
    *,
    resolved_inputs: dict[str, Any] | None = None,
    language: str = "zh",
) -> GraphWorkerResult:

    items = _resolved_items(task, resolved_inputs)
    evidence_items = [item for item in items if item.get("slot_id") in _EVIDENCE_SLOTS]

    safe_items: list[dict[str, Any]] = []
    full_evidence_source_ids: set[str] = set()
    for item in items:
        slot_id = str(item.get("slot_id") or "")
        source_task_ids = [str(value) for value in item.get("source_task_ids") or [] if str(value)]
        payload = item.get("payload")
        if slot_id == "entity_external_evidence":
            full_evidence_source_ids.update(source_task_ids)
            compact_payload = _compact_payload(slot_id, payload)
        elif slot_id == "evidence_source_records" and set(source_task_ids).intersection(full_evidence_source_ids):
            # W01 currently publishes the same evidence collection payload into both
            # evidence slots. Keep the second slot's identity without duplicating the
            # complete evidence corpus in the W09 prompt.
            payload_dict = payload if isinstance(payload, dict) else {}
            compact_payload = {
                "payload_alias_of": "entity_external_evidence",
                "record_count": int(payload_dict.get("record_count") or 0),
                "source_count": int(payload_dict.get("source_count") or 0),
                "coverage": safe_public_value(payload_dict.get("coverage") or {}),
                "business_empty": bool(payload_dict.get("business_empty", False)),
            }
        else:
            compact_payload = _compact_payload(slot_id, payload)
        safe_items.append({
            "slot_id": slot_id,
            "source_task_ids": source_task_ids,
            "status": str(item.get("status") or "available"),
            "payload": compact_payload,
        })
    known_source_task_ids = {
        str(source_id)
        for item in safe_items
        for source_id in item.get("source_task_ids") or []
        if str(source_id)
    }

    output_schema = _entity_analysis_llm_schema()

    def validate(payload: dict[str, Any]) -> None:
        validate_schema(payload, output_schema)
        required = ["entity_refs", *_CLAIM_LIST_FIELDS, "conclusion", "source_task_ids"]
        missing = [key for key in required if key not in payload]
        if missing:
            raise RuntimeError(f"entity_analysis_missing_fields:{','.join(missing)}")
        if not isinstance(payload.get("entity_refs"), list) or any(
            not isinstance(item, dict) for item in payload.get("entity_refs") or []
        ):
            raise RuntimeError("entity_analysis_entity_refs_must_be_object_array")
        seen_claim_ids: set[str] = set()
        for field in _CLAIM_LIST_FIELDS:
            values = payload.get(field)
            if not isinstance(values, list):
                raise RuntimeError(f"entity_analysis_{field}_must_be_array")
            for index, item in enumerate(values):
                if not isinstance(item, dict):
                    raise RuntimeError(
                        f"entity_analysis_{field}_item_must_be_object:{index}"
                    )
                claim_id = str(item.get("claim_id") or "").strip()
                if not claim_id:
                    raise RuntimeError(f"entity_analysis_{field}_claim_id_required:{index}")
                if claim_id in seen_claim_ids:
                    raise RuntimeError(f"entity_analysis_duplicate_claim_id:{claim_id}")
                seen_claim_ids.add(claim_id)
                if not _claim_text(item):
                    raise RuntimeError(
                        f"entity_analysis_{field}_statement_required:{index}"
                    )
                source_ids = _claim_source_ids(item)
                if field != "uncertainties" and not source_ids:
                    raise RuntimeError(
                        f"entity_analysis_{field}_source_task_ids_required:{index}"
                    )
                unknown = sorted(set(source_ids) - known_source_task_ids)
                if unknown:
                    raise RuntimeError(
                        f"entity_analysis_unknown_source_task_ids:{field}:{index}:{','.join(unknown)}"
                    )
        source_task_ids = payload.get("source_task_ids")
        if not isinstance(source_task_ids, list) or any(
            not isinstance(item, str) for item in source_task_ids
        ):
            raise RuntimeError("entity_analysis_source_task_ids_must_be_string_array")
        unknown_overall = sorted(set(source_task_ids) - known_source_task_ids)
        if unknown_overall:
            raise RuntimeError(
                "entity_analysis_unknown_overall_source_task_ids:"
                + ",".join(unknown_overall)
            )
        if not isinstance(payload.get("conclusion"), str):
            raise RuntimeError("entity_analysis_conclusion_must_be_string")

    system = (
        "你是W09结构化实体分析Worker。你只处理本任务实际绑定并物化给你的信息Slot，"
        "这些Slot就是你完整的工作世界；不要猜测、枚举或评价未绑定的信息、Worker、Tool、数据源或潜在分析维度。"
        "你的职责是把收到的结构化输入融合为通用facts、analysis、uncertainties和conclusion。"
        "不同来源的数据都统一融合进这些通用字段，不要按系统内部能力域创建固定输出栏目。"
        "不得自行检索、查询数据库、解析新实体或补造输入中不存在的事实、数值、风险、建议和因果关系。"
        "每个非空claim必须有唯一claim_id、statement和source_task_ids，且source_task_ids只能引用本次实际输入的上游任务。"
        "uncertainties只能描述实际输入内容本身存在的不确定性，不得把未收到的信息描述成缺口。"
        "只输出业务分析JSON，不输出completion_report；完成度和合同验收由Runtime负责。只输出JSON，不生成面向用户的完整自然语言报告。"
    )
    if language == "en":
        system = (
            "You are W09, a structured entity-analysis Worker. Process only the information slots actually bound and materialized for this task; those slots are your entire working world. "
            "Do not infer, enumerate, or evaluate unbound information, Workers, Tools, data sources, or hypothetical analysis dimensions. "
            "Fuse supplied structured inputs into generic facts, analysis, uncertainties, and a conclusion. Do not create fixed output categories based on internal capability domains. "
            "Do not retrieve data, query databases, resolve new entities, or invent facts, numbers, risks, recommendations, or causal claims. Every non-empty claim must cite only source_task_ids attached to actual inputs. "
            "Uncertainties may describe uncertainty inside supplied information only. Return JSON only."
        )


    generation_messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": compact_json_dumps(
                {
                    "analysis_goal": str(task.args.get("analysis_goal") or task.objective),
                    "comparison_mode": len(task.focus_refs) > 1,
                    "allowed_source_task_ids": sorted(known_source_task_ids),
                    "bound_input_slot_ids": sorted(str(item.get("slot_id") or "") for item in safe_items),
                    "authoritative_entity_refs": _authoritative_entity_refs(task, evidence_items),
                    "authoritative_entity_catalog": _authoritative_entity_catalog(task, evidence_items),
                    "bound_information_slots": safe_items,
                    "entity_analysis_output_schema": schema_for_prompt(output_schema),
                    "reply_language": language,
                },
            ),
        },
    ]
    try:
        analysis = _generate_entity_analysis_json(
            llm_service,
            messages=generation_messages,
            output_schema=output_schema,
            validate=validate,
            allowed_source_task_ids=sorted(known_source_task_ids),
            operation=task.boundary_id,
        )
    except LLMJSONError as exc:
        completion = build_completion_report(
            task,
            execution_status="failed",
            contract_status="not_satisfied",
            business_status="unknown",
            completion_status="not_completed",
            expected_task_completed=False,
            produced_information_slots=[],
            limitations=[str(exc)[:1000]],
            failure_kind="worker_structured_output_failure",
            report_source="runtime",
        )
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.FAILED,
            output_type="CapabilityResult",
            data=None,
            error={
                "code": "worker_structured_output_failed",
                "message": str(exc),
                "component": task.assigned_agent,
                "retryable": False,
                "local_recovery_exhausted": True,
            },
            focus_refs=task.focus_refs,
            summary=(
                "W09结构化输出修复失败。"
                if language != "en" else
                "W09 structured-output repair failed."
            ),
            warnings=[f"LLMJSONError:{exc}"],
            completion=completion,
            metadata={
                "structured_output_local_recovery": "exhausted",
                "main_agent_replan_recommended": False,
                "database_write": False,
            },
        )

    completion = build_completion_report(
        task,
        execution_status="succeeded",
        contract_status="valid",
        business_status="sufficient",
        completion_status="completed",
        expected_task_completed=True,
        produced_information_slots=[
            "entity_analysis",
            "entity_analysis_uncertainty",
        ],
        limitations=[],
        failure_kind="none",
        report_source="runtime",
    )
    authoritative_refs = _authoritative_entity_refs(task, evidence_items)
    entity_analysis_slot = {
        "entity_refs": authoritative_refs or execution_safe_value(analysis.get("entity_refs") or []),
        "entity_catalog": _authoritative_entity_catalog(task, evidence_items),
        "facts": execution_safe_value(analysis.get("facts") or []),
        "analysis": execution_safe_value(analysis.get("analysis") or []),
        "uncertainties": execution_safe_value(analysis.get("uncertainties") or []),
        "conclusion": str(analysis.get("conclusion") or ""),
        "source_task_ids": sorted(known_source_task_ids),
    }
    payload = {
        **entity_analysis_slot,
        "slots": {
            "entity_analysis": entity_analysis_slot,
            "entity_analysis_uncertainty": {
                "entity_refs": entity_analysis_slot["entity_refs"],
                "uncertainties": entity_analysis_slot["uncertainties"],
                "source_task_ids": entity_analysis_slot["source_task_ids"],
            },
        },
        "produced_information_slots": [
            "entity_analysis",
            "entity_analysis_uncertainty",
        ],
    }
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        output_type="EntityAnalysisResult",
        payload_schema="entity_analysis_result.v1",
        payload=payload,
        data=payload,
        error=None,
        focus_refs=task.focus_refs,
        summary="已基于上游证据和结构化事实完成金融实体分析。",
        findings=[
            {
                "kind": "entity_analysis_output_diagnostics",
                "fact_count": len(payload["facts"]),
                "analysis_count": len(payload["analysis"]),
                "uncertainty_count": len(payload["uncertainties"]),
                "source_task_count": len(payload["source_task_ids"]),
            },
        ],
        confidence=0.85,
        completion=completion,
        metadata={
            "database_write": False,
            "source_task_ids": payload["source_task_ids"],
            "bound_slot_projection": "execution_materialized_then_worker_compacted",
        },
    )


__all__ = ["run_entity_analysis"]
