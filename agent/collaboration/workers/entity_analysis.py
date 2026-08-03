"""Analyze financial entities from completed upstream evidence and fact results."""

from __future__ import annotations

import json
from typing import Any

from core.llm import LLMService

from ..completion import validate_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from ..worker_contracts import array_schema, completion_report_schema, object_schema, string_schema, validate_schema
from .common import dependency_results as dependency_result_items
from .common import safe_public_value


_CLAIM_LIST_FIELDS = (
    "facts",
    "analysis",
    "model_signals",
    "relation_interpretations",
    "uncertainties",
)


def _claim_schema() -> dict[str, Any]:
    return object_schema(
        {
            "statement": string_schema(min_length=1),
            "source_task_ids": array_schema({"type": "string"}),
        },
        required=["statement", "source_task_ids"],
        additional_properties=False,
    )


def _entity_analysis_llm_schema() -> dict[str, Any]:
    claim = _claim_schema()
    return object_schema(
        {
            "entity_refs": array_schema(object_schema({}, additional_properties=True)),
            "facts": array_schema(claim),
            "analysis": array_schema(claim),
            "model_signals": array_schema(claim),
            "relation_interpretations": array_schema(claim),
            "uncertainties": array_schema(claim),
            "conclusion": {"type": "string"},
            "source_task_ids": array_schema({"type": "string"}),
            "completion_report": completion_report_schema(),
        },
        required=[
            "entity_refs",
            "facts",
            "analysis",
            "model_signals",
            "relation_interpretations",
            "uncertainties",
            "conclusion",
            "source_task_ids",
            "completion_report",
        ],
        additional_properties=False,
    )


def _resolved_items(
    task: GraphAgentTask,
    dependency_results: dict[str, dict[str, Any]],
    resolved_inputs: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    explicit: list[dict[str, Any]] = []
    for value in dict(resolved_inputs or {}).values():
        values = value if isinstance(value, list) else [value]
        explicit.extend(item for item in values if isinstance(item, dict))
    if explicit:
        return explicit
    requested = set(
        task.input_task_ids("evidence")
        + task.input_task_ids("model_facts")
        + task.input_task_ids("relation_context")
    )
    selected = {
        task_id: payload
        for task_id, payload in dependency_results.items()
        if not requested or task_id in requested
    }
    return dependency_result_items(selected)


def _trim_text(value: Any, *, limit: int = 1200) -> str:
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
                    for row in list(item.get("records") or [])[:12]
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
        "coverage": safe_public_value(payload.get("coverage") or {}),
        "business_empty": bool(payload.get("business_empty", False)),
    }


def _compact_payload(output_type: str, payload: Any) -> Any:
    if not isinstance(payload, dict):
        return safe_public_value(payload)
    if output_type == "EvidenceCollectionResult":
        return _compact_evidence_payload(payload)
    # Internal fact results are already structured and normally much smaller.
    encoded = json.dumps(safe_public_value(payload), ensure_ascii=False, default=str)
    if len(encoded) <= 16000:
        return safe_public_value(payload)
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
        payload = item.get("payload", item.get("data"))
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
        payload = item.get("payload", item.get("data"))
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


def run_entity_analysis(
    llm_service: LLMService,
    task: GraphAgentTask,
    dependency_results: dict[str, dict[str, Any]],
    *,
    resolved_inputs: dict[str, Any] | None = None,
    language: str = "zh",
) -> GraphWorkerResult:
    if task.task_type not in {"analyze_financial_entities", "compare_financial_entities"}:
        raise ValueError(f"unsupported_entity_analysis_task:{task.task_type}")

    items = _resolved_items(task, dependency_results, resolved_inputs)
    evidence_items = [
        item
        for item in items
        if str(item.get("output_type") or "") == "EvidenceCollectionResult"
    ]
    if not evidence_items:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            output_type="EntityAnalysisResult",
            data=None,
            error=None,
            focus_refs=task.focus_refs,
            summary="金融实体分析缺少上游外部证据集合。",
            missing_items=[
                MissingContextItem(
                    key="evidence",
                    description="需要 W01 产生的 EvidenceCollectionResult。",
                    expected_format="一个或多个 EvidenceCollectionResult WorkerResult",
                    searched_sources=["declared upstream inputs", "dependency_results"],
                )
            ],
        )

    safe_items: list[dict[str, Any]] = []
    for item in items:
        task_id = str(item.get("from_task_id") or item.get("task_id") or "")
        output_type = str(item.get("output_type") or "")
        safe_items.append(
            {
                "task_id": task_id,
                "output_type": output_type,
                "status": str(item.get("status") or ""),
                "payload": _compact_payload(
                    output_type,
                    item.get("payload", item.get("data")),
                ),
                "summary": _trim_text(item.get("summary"), limit=1000),
                "confidence": item.get("confidence"),
            }
        )
    known_source_task_ids = {
        str(item.get("task_id") or "")
        for item in safe_items
        if str(item.get("task_id") or "")
    }

    output_schema = _entity_analysis_llm_schema()

    def validate(payload: dict[str, Any]) -> None:
        validate_schema(payload, output_schema)
        required = ["entity_refs", *_CLAIM_LIST_FIELDS, "conclusion", "source_task_ids", "completion_report"]
        missing = [key for key in required if key not in payload]
        if missing:
            raise RuntimeError(f"entity_analysis_missing_fields:{','.join(missing)}")
        if not isinstance(payload.get("entity_refs"), list) or any(
            not isinstance(item, dict) for item in payload.get("entity_refs") or []
        ):
            raise RuntimeError("entity_analysis_entity_refs_must_be_object_array")
        for field in _CLAIM_LIST_FIELDS:
            values = payload.get(field)
            if not isinstance(values, list):
                raise RuntimeError(f"entity_analysis_{field}_must_be_array")
            for index, item in enumerate(values):
                if not isinstance(item, dict):
                    raise RuntimeError(
                        f"entity_analysis_{field}_item_must_be_object:{index}"
                    )
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
        validate_completion_report(
            dict(payload.get("completion_report") or {}),
            dict(task.completion_contract or {}),
            path="$.completion_report",
        )

    system = (
        "你是金融实体分析 Worker。只能使用输入中的上游结构化结果，不能自行检索新闻、查询数据库、"
        "解析新实体或补造证券名称、行业、数值和事件。EvidenceCollectionResult 提供外部证据，"
        "ModelPredictionResult 等结果只提供模型或内部事实，GraphRelationResult 只证明关系路径存在。"
        "你负责解释这些材料对金融实体本身的含义，区分事实、分析、模型信号、关系解释和不确定性。"
        "关系存在不等于因果影响，不得生成组合风险结论、调仓建议、Proposal 或执行声明。"
        "facts、analysis、model_signals、relation_interpretations、uncertainties 的每个元素必须是对象，"
        "格式为 {\"statement\":\"...\",\"source_task_ids\":[\"真实上游task_id\"]}；"
        "uncertainties 可以使用空 source_task_ids，但其他声明必须引用真实上游任务。"
        "你还必须严格对照 completion_contract 输出 completion_report。规则不替你判断业务是否完成；"
        "只有你基于上游结构化结果确认全部 criteria 满足、全部 required_information_slots 已产生时，"
        "才能设置 expected_task_completed=true。若没有形成实体分析，只能产生 uncertainty，必须设置为 false。"
        "不得输出 should_freeze、reusable 或 replan 决策，这些只由程序流程规则计算。"
        "严格按照 entity_analysis_output_schema 输出 JSON，不要 Markdown。"
    )
    if language == "en":
        system = (
            "You are the financial-entity analysis Worker. Use only supplied structured upstream results. "
            "Do not retrieve data, query databases, resolve new entities, invent labels, or create portfolio advice. "
            "Separate facts, analysis, model signals, relation interpretation, and uncertainty. A graph relation is "
            "not proof of causal impact. Every item in facts, analysis, model_signals, relation_interpretations, and "
            "uncertainties must be an object shaped as {\"statement\":\"...\",\"source_task_ids\":[\"real upstream task id\"]}. "
            "Only uncertainty items may have an empty source_task_ids array. Evaluate every completion_contract criterion "
            "inside completion_report. Set expected_task_completed=true only when all criteria and required information slots "
            "are satisfied. Do not output freeze/reuse/replan decisions. Return only JSON matching entity_analysis_output_schema."
        )

    analysis = llm_service.generate_json(
        stage="graph_entity_analysis",
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "analysis_goal": str(task.args.get("analysis_goal") or task.objective),
                        "comparison_mode": task.task_type == "compare_financial_entities",
                        "allowed_source_task_ids": sorted(known_source_task_ids),
                        "authoritative_entity_refs": _authoritative_entity_refs(task, evidence_items),
                        "authoritative_entity_catalog": _authoritative_entity_catalog(task, evidence_items),
                        "upstream_results": safe_items,
                        "completion_contract": task.completion_contract,
                        "entity_analysis_output_schema": output_schema,
                        "reply_language": language,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
        max_output_tokens=2600,
        validator=validate,
        operation=task.task_type,
        repair_mode="targeted",
        repair_guidance=(
            "只修复 JSON 类型、对象字段、source_task_ids 和 completion_report 的结构一致性。"
            "所有声明数组元素必须是对象，只能引用 allowed_source_task_ids，不得新增事实或来源。"
            "completion_report 必须逐项覆盖 completion_contract.criteria，且不得输出流程控制字段。"
        ),
    )
    completion = dict(analysis.get("completion_report") or {})
    authoritative_refs = _authoritative_entity_refs(task, evidence_items)
    payload = {
        "entity_refs": authoritative_refs or safe_public_value(analysis.get("entity_refs") or []),
        "entity_catalog": _authoritative_entity_catalog(task, evidence_items),
        "facts": safe_public_value(analysis.get("facts") or []),
        "analysis": safe_public_value(analysis.get("analysis") or []),
        "model_signals": safe_public_value(analysis.get("model_signals") or []),
        "relation_interpretations": safe_public_value(
            analysis.get("relation_interpretations") or []
        ),
        "uncertainties": safe_public_value(analysis.get("uncertainties") or []),
        "conclusion": str(analysis.get("conclusion") or ""),
        "source_task_ids": sorted(known_source_task_ids),
    }
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=(
            ResultStatus.COMPLETED
            if bool(completion.get("expected_task_completed"))
            else ResultStatus.PARTIAL
        ),
        output_type="EntityAnalysisResult",
        payload_schema="entity_analysis_result.v1",
        payload=payload,
        data=payload,
        error=None,
        focus_refs=task.focus_refs,
        summary=(
            "已基于上游证据和结构化事实完成金融实体分析。"
            if bool(completion.get("expected_task_completed"))
            else "实体分析已返回结构化结果，但未满足全部预期任务条件。"
        ),
        findings=[
            {
                "kind": "entity_analysis",
                "fact_count": len(payload["facts"]),
                "analysis_count": len(payload["analysis"]),
                "uncertainty_count": len(payload["uncertainties"]),
            }
        ],
        confidence=0.85 if bool(completion.get("expected_task_completed")) else 0.4,
        completion=completion,
        metadata={
            "database_write": False,
            "source_task_ids": payload["source_task_ids"],
            "compacted_upstream_payload": True,
        },
    )


__all__ = ["run_entity_analysis"]
