"""W09 financial-entity analysis from the current ContextBundle working memory."""
from __future__ import annotations

from typing import Any

from core.llm import LLMService
from core.llm.contracts import LLMJSONError
from core.llm.prompt_compaction import compact_json_dumps, schema_for_prompt

from ..completion import build_completion_report, non_success_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from ..worker_contracts import array_schema, object_schema, string_schema, validate_schema
from .common import execution_safe_value, materialize_promised_data, safe_public_value
from .structured_output import generate_json_with_local_structural_repair

_MAX_PRIMARY_OUTPUT_TOKENS = 2600
_MAX_REPAIR_OUTPUT_TOKENS = 2200
_MAX_REPAIR_INPUT_CHARS = 12000


def _claim_schema() -> dict[str, Any]:
    return object_schema(
        {
            "claim_id": string_schema(min_length=1, max_length=80),
            "statement": string_schema(min_length=1, max_length=320),
        },
        required=["claim_id", "statement"],
        additional_properties=False,
    )


def _analysis_schema() -> dict[str, Any]:
    claim = _claim_schema()
    return object_schema(
        {
            "context_sufficient": {"type": "boolean"},
            "missing_information": array_schema(string_schema(min_length=1, max_length=160), max_items=8),
            "facts": array_schema(claim, max_items=10),
            "analysis": array_schema(claim, max_items=8),
            "uncertainties": array_schema(claim, max_items=6),
            "conclusion": string_schema(max_length=600),
        },
        required=["context_sufficient", "missing_information", "facts", "analysis", "uncertainties", "conclusion"],
        additional_properties=False,
    )


def _validate_analysis(payload: dict[str, Any]) -> None:
    validate_schema(payload, _analysis_schema())
    for field in ("facts", "analysis", "uncertainties"):
        seen: set[str] = set()
        for index, item in enumerate(payload.get(field) or []):
            claim_id = str(item.get("claim_id") or "").strip()
            if not claim_id:
                raise RuntimeError(f"entity_analysis_{field}_claim_id_required:{index}")
            if claim_id in seen:
                raise RuntimeError(f"entity_analysis_duplicate_claim_id:{claim_id}")
            seen.add(claim_id)
            if not str(item.get("statement") or "").strip():
                raise RuntimeError(f"entity_analysis_{field}_statement_required:{index}")


def run_entity_analysis(
    llm_service: LLMService,
    task: GraphAgentTask,
    *,
    working_memory_context: dict[str, Any] | None = None,
    language: str = "zh",
) -> GraphWorkerResult:
    """Analyze only the supplied target-entity working memory.

    W09 never sees producer Worker/Tool/Request identities. It decides whether
    the available business data is sufficient for the concrete analysis goal.
    """
    context = execution_safe_value(dict(working_memory_context or {}))
    authoritative_refs = [ref.to_dict() for ref in task.focus_refs]
    available_names = [str(x) for x in context.get("available_names") or [] if str(x)]
    output_schema = _analysis_schema()

    system = (
        "你是W09金融实体分析Worker。你只负责分析已确定身份的目标金融实体。Runtime已经把本轮ContextBundle中属于这些实体的已查询业务数据整理在working_memory中。"
        "你不需要也不得判断数据来自哪个Worker、Tool、RAG或Request，不自行检索，也不指定下一步应调用谁。"
        "标签存在代表该查询/生成已经成功结束；即使值为空，也代表已查询但结果为空。"
        "你必须根据具体analysis_goal自行判断现有数据的质量和充分性。若不足，context_sufficient=false，只说明缺什么业务信息以及原因；不要输出无依据分析。"
        "若足够，严格区分facts、analysis、uncertainties，并且不得引入working_memory中不存在的业务事实。只输出JSON。"
        if language != "en" else
        "You are W09, a financial entity-analysis Worker. Analyze only the resolved target entities using the supplied ContextBundle working memory. "
        "Do not care which Worker, Tool, RAG flow, or Request produced the data. Do not retrieve more data or select another Worker. "
        "An existing data name means the operation completed even when its value is empty. Judge data quality and sufficiency for the specific analysis goal yourself. "
        "If insufficient, set context_sufficient=false and state only what business information is missing. Return JSON only."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": compact_json_dumps({
            "analysis_goal": str(task.args.get("analysis_goal") or task.objective),
            "comparison_mode": len(task.focus_refs) > 1,
            "authoritative_entity_refs": authoritative_refs,
            "working_memory": context,
            "entity_analysis_output_schema": schema_for_prompt(output_schema),
            "reply_language": language,
        })},
    ]
    try:
        analysis = generate_json_with_local_structural_repair(
            llm_service,
            stage="graph_entity_analysis",
            operation=task.boundary_id,
            messages=messages,
            output_schema=output_schema,
            validator=_validate_analysis,
            immutable_repair_context={
                "authoritative_entity_refs": authoritative_refs,
                "available_names": available_names,
            },
            repair_guidance="只修复JSON结构；不得新增Working Memory中不存在的事实。",
            primary_max_output_tokens=_MAX_PRIMARY_OUTPUT_TOKENS,
            repair_max_output_tokens=_MAX_REPAIR_OUTPUT_TOKENS,
            max_invalid_output_chars=_MAX_REPAIR_INPUT_CHARS,
            primary_disable_thinking=True,
        )
    except LLMJSONError as exc:
        completion = build_completion_report(
            task,
            execution_status="failed",
            contract_status="not_satisfied",
            business_status="unknown",
            completion_status="not_completed",
            expected_task_completed=False,
            produced_data_names=[],
            limitations=[str(exc)[:1000]],
            failure_kind="worker_structured_output_failure",
        )
        return GraphWorkerResult(
            task_id=task.task_id, agent_id=task.assigned_agent, status=ResultStatus.FAILED,
            output_type="EntityAnalysisResult", data=None,
            error={"code": "worker_structured_output_failed", "message": str(exc), "component": task.assigned_agent, "retryable": False},
            focus_refs=task.focus_refs,
            summary="W09结构化输出修复失败。" if language != "en" else "W09 structured-output repair failed.",
            warnings=[f"LLMJSONError:{exc}"], completion=completion,
            metadata={"database_write": False, "working_memory_mode": True},
        )

    if not bool(analysis.get("context_sufficient")):
        missing_information = [str(x).strip() for x in analysis.get("missing_information") or [] if str(x).strip()]
        reason = str(analysis.get("conclusion") or "当前实体工作记忆不足以支持可靠分析。")
        completion = non_success_completion_report(
            task, execution_status="need_context", reason=reason, failure_kind="entity_context_insufficient"
        )
        return GraphWorkerResult(
            task_id=task.task_id, agent_id=task.assigned_agent, status=ResultStatus.NEED_CONTEXT,
            output_type="EntityAnalysisResult", data=None,
            error={"error_id": "entity_context_insufficient", "operation": task.objective or task.boundary_id, "reason": reason, "retryable": True},
            focus_refs=task.focus_refs,
            summary="当前实体工作记忆不足以支持可靠分析，已反馈缺失的业务信息。",
            missing_items=[
                MissingContextItem(
                    key=f"entity_information_{index}", description=value,
                    expected_format="business information", reason="W09 judged current entity working memory insufficient",
                    searched_sources=["ContextBundle"], blocking=True,
                )
                for index, value in enumerate(missing_information or [reason], start=1)
            ],
            completion=completion,
            metadata={
                "working_memory_mode": True,
                "working_memory_available_names": available_names,
                "context_sufficient": False,
                "missing_information": missing_information,
                "replan_recommended": True,
                "failure_kind": "entity_context_insufficient",
                "database_write": False,
            },
        )

    analysis_record = {
        "entity_refs": authoritative_refs,
        "facts": safe_public_value(analysis.get("facts") or []),
        "analysis": safe_public_value(analysis.get("analysis") or []),
        "uncertainties": safe_public_value(analysis.get("uncertainties") or []),
        "conclusion": str(analysis.get("conclusion") or ""),
        "context_assessment": {
            "sufficient": True,
            "missing_information": [],
            "available_names": available_names,
        },
    }
    uncertainty_record = {
        "entity_refs": authoritative_refs,
        "uncertainties": analysis_record["uncertainties"],
        "available_names": available_names,
    }
    business_data = materialize_promised_data(
        task,
        analysis_record,
        per_name={"analysis": analysis_record, "analysis_uncertainty": uncertainty_record},
    )
    completion = build_completion_report(
        task,
        execution_status="succeeded",
        contract_status="valid",
        business_status="sufficient",
        completion_status="completed",
        expected_task_completed=True,
        produced_data_names=list(business_data),
        limitations=[],
        failure_kind="none",
    )
    payload = {**analysis_record, "business_data": business_data, "produced_data_names": list(business_data)}
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        output_type="EntityAnalysisResult",
        payload_schema="entity_analysis_result.v2",
        payload=payload,
        data=payload,
        error=None,
        focus_refs=task.focus_refs,
        summary="已基于目标实体当前ContextBundle工作记忆完成金融实体分析。",
        findings=[{
            "kind": "entity_analysis_output_diagnostics",
            "fact_count": len(payload["facts"]),
            "analysis_count": len(payload["analysis"]),
            "uncertainty_count": len(payload["uncertainties"]),
            "working_memory_available_names": available_names,
        }],
        confidence=0.85,
        completion=completion,
        metadata={
            "database_write": False,
            "working_memory_mode": True,
            "working_memory_available_names": available_names,
            "context_sufficient": True,
        },
    )


__all__ = ["run_entity_analysis"]
