"""Generate a final Markdown report from terminal structured Worker results.

W06 is presentation-only. It does not re-read raw evidence, perform financial
analysis, or duplicate the structured claims already produced by a specialist.
The LLM returns section objects; the runtime composes the final Markdown after
schema validation so a large duplicated ``claims + content`` JSON response is
not required.
"""

from __future__ import annotations

import json
from typing import Any

from core.llm import LLMService
from core.llm.prompt_compaction import compact_json_dumps, schema_for_prompt

from agent.graph.contracts import GraphNodeKind, GraphPathRef

from ..completion import build_completion_report, validate_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from ..report_validation import ReportPolicy, build_report_policy, validate_report_output
from ..worker_contracts import (
    WorkerContractViolation,
    array_schema,
    completion_report_schema,
    object_schema,
    string_schema,
    validate_schema,
)
from .common import dependency_results as dependency_result_items
from .common import refs_from_dependencies, safe_public_value


_REPORT_MAX_OUTPUT_TOKENS = 3200
_REPORT_MAX_SECTIONS = 8
_REPORT_MAX_SECTION_CHARS = 3500


def _scalar_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): safe_public_value(item)
        for key, item in value.items()
        if item is None or isinstance(item, (bool, int, float, str))
    }


def _compact_account_state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove duplicate transport fields while preserving account facts."""

    account = dict(payload.get("account") or {})
    if not account:
        account = dict(payload.get("account_summary") or payload.get("summary") or {})
    return safe_public_value({
        "user_id": payload.get("user_id"),
        "account_metrics": _scalar_mapping(account),
        "as_of_date": payload.get("as_of_date"),
        "snapshot_id": payload.get("snapshot_id"),
        "cash_semantics": payload.get("cash_semantics"),
        "consistency_status": payload.get("consistency_status"),
        "consistency_warnings": payload.get("consistency_warnings") or [],
        "consistency_errors": payload.get("consistency_errors") or [],
    })


def _compact_portfolio_state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep every reportable position and account fact without duplicates."""

    entity_catalog = []
    for item in payload.get("entity_catalog") or []:
        if not isinstance(item, dict):
            continue
        entity_catalog.append({
            "public_code": item.get("public_code"),
            "display_label": item.get("display_label"),
            "exchange": item.get("exchange"),
            "identity_source": item.get("identity_source"),
            "identity_locked": item.get("identity_locked"),
        })
    positions = []
    for item in payload.get("display_positions") or []:
        if not isinstance(item, dict):
            continue
        positions.append({
            key: safe_public_value(item.get(key))
            for key in (
                "public_code", "display_label", "exchange", "identity_source",
                "identity_locked", "quantity", "cost_price", "current_price",
                "market_value", "position_ratio", "unrealized_pnl", "updated_at",
            )
            if item.get(key) not in (None, "", [], {})
        })
    summary = dict(payload.get("portfolio_summary") or {})
    summary_view = {
        key: safe_public_value(summary.get(key))
        for key in (
            "as_of_date", "snapshot_id", "consistency_status",
            "consistency_warnings", "consistency_errors", "cash_state",
        )
        if summary.get(key) not in (None, "", [], {})
    }
    return safe_public_value({
        "entity_catalog": entity_catalog,
        "display_positions": positions,
        "account_snapshot": _scalar_mapping(payload.get("account_snapshot")),
        "portfolio_totals": payload.get("portfolio_totals") or {},
        "portfolio_summary": summary_view,
        "unresolved_positions": payload.get("unresolved_positions") or [],
        "as_of_time": payload.get("as_of_time"),
        "graph_snapshot_materialized": payload.get("graph_snapshot_materialized"),
    })


def _compact_report_payload(output_type: str, payload: Any) -> Any:
    """Keep the terminal specialist result needed by W06.

    EntityAnalysisResult is already the terminal synthesis of W01 evidence and
    W02 internal data. Only its structured analysis contract is forwarded; raw
    EvidenceCollectionResult records are not expanded here.
    """

    if not isinstance(payload, dict):
        return safe_public_value(payload)
    if output_type == "AccountStateResult":
        return _compact_account_state_payload(payload)
    if output_type == "PortfolioAnalysisResult":
        return _compact_portfolio_state_payload(payload)
    if output_type == "EntityAnalysisResult":
        return safe_public_value({
            "entity_refs": payload.get("entity_refs") or [],
            "entity_catalog": payload.get("entity_catalog") or [],
            "facts": payload.get("facts") or [],
            "analysis": payload.get("analysis") or [],
            "model_signals": payload.get("model_signals") or [],
            "relation_interpretations": payload.get("relation_interpretations") or [],
            "uncertainties": payload.get("uncertainties") or [],
            "conclusion": payload.get("conclusion") or "",
            "source_task_ids": payload.get("source_task_ids") or [],
            "input_diagnostics": payload.get("input_diagnostics") or {},
        })
    return safe_public_value(payload)


def _safe_results(
    task: GraphAgentTask,
    dependency_results: dict[str, dict[str, Any]],
    resolved_inputs: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str], list[dict[str, Any]]]:
    requested_task_ids = task.input_task_ids("upstream_results")
    selected_dependency_results = {
        task_id: payload
        for task_id, payload in dependency_results.items()
        if not requested_task_ids or task_id in set(requested_task_ids)
    }
    explicit_items: list[dict[str, Any]] = []
    for role_value in dict(resolved_inputs or {}).values():
        values = role_value if isinstance(role_value, list) else [role_value]
        explicit_items.extend(value for value in values if isinstance(value, dict))

    source_items = explicit_items or dependency_result_items(selected_dependency_results)
    safe_results: list[dict[str, Any]] = []
    for item in source_items:
        output_type = str(item.get("output_type") or "")
        safe_results.append(
            {
                "contract_version": str(
                    item.get("contract_version") or "graph_worker_result.v1"
                ),
                "task_id": str(item.get("from_task_id") or item.get("task_id") or ""),
                "agent_id": str(item.get("agent_id") or ""),
                "status": str(item.get("status") or ""),
                "output_type": output_type,
                "payload_schema": str(item.get("payload_schema") or ""),
                "payload_version": str(item.get("payload_version") or ""),
                "payload": _compact_report_payload(
                    output_type,
                    item.get("payload", item.get("data")),
                ),
                "summary": str(item.get("summary") or "")[:2000],
                "evidence_refs": safe_public_value(item.get("evidence_refs") or []),
                "artifact_refs": safe_public_value(item.get("artifact_refs") or []),
                "graph_path_refs": safe_public_value(item.get("graph_path_refs") or []),
                "confidence": item.get("confidence"),
                "completion": safe_public_value(item.get("completion") or {}),
            }
        )
    return safe_results, selected_dependency_results, requested_task_ids, [
        dict(item) for item in source_items if isinstance(item, dict)
    ]


def _claim_catalog(safe_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}

    def visit(value: Any, source_task_id: str = "") -> None:
        if isinstance(value, dict):
            claim_id = str(value.get("claim_id") or "").strip()
            if claim_id:
                catalog[claim_id] = {
                    "claim_id": claim_id,
                    "statement": str(value.get("statement") or ""),
                    "direction": str(value.get("direction") or ""),
                    "causality": str(value.get("causality") or ""),
                    "source_task_id": source_task_id,
                }
            for item in value.values():
                visit(item, source_task_id)
        elif isinstance(value, list):
            for item in value:
                visit(item, source_task_id)

    for result in safe_results:
        visit(result.get("payload"), str(result.get("task_id") or ""))
    return catalog


def _report_input_diagnostics(
    safe_results: list[dict[str, Any]],
    upstream_claims: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output_types = [str(item.get("output_type") or "") for item in safe_results]
    entity_counts = {
        "fact_count": 0,
        "analysis_count": 0,
        "model_signal_count": 0,
        "relation_interpretation_count": 0,
        "uncertainty_count": 0,
    }
    entity_input_diagnostics: list[dict[str, Any]] = []
    for item in safe_results:
        if str(item.get("output_type") or "") != "EntityAnalysisResult":
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        entity_counts["fact_count"] += len(payload.get("facts") or [])
        entity_counts["analysis_count"] += len(payload.get("analysis") or [])
        entity_counts["model_signal_count"] += len(payload.get("model_signals") or [])
        entity_counts["relation_interpretation_count"] += len(
            payload.get("relation_interpretations") or []
        )
        entity_counts["uncertainty_count"] += len(payload.get("uncertainties") or [])
        if isinstance(payload.get("input_diagnostics"), dict):
            entity_input_diagnostics.append(
                safe_public_value(payload.get("input_diagnostics") or {})
            )
    encoded = json.dumps(safe_results, ensure_ascii=False, default=str)
    return {
        "upstream_task_ids": [str(item.get("task_id") or "") for item in safe_results],
        "upstream_output_types": output_types,
        "upstream_result_count": len(safe_results),
        "raw_evidence_result_count": sum(
            1 for value in output_types if value == "EvidenceCollectionResult"
        ),
        "entity_analysis_result_count": sum(
            1 for value in output_types if value == "EntityAnalysisResult"
        ),
        "upstream_claim_count": len(upstream_claims),
        "llm_input_chars": len(encoded),
        "max_output_tokens": _REPORT_MAX_OUTPUT_TOKENS,
        "output_contract": "sectioned_markdown_report.v1",
        "entity_analysis_counts": entity_counts,
        "entity_analysis_input_diagnostics": entity_input_diagnostics,
    }


def _system_prompt(language: str, policy: ReportPolicy) -> str:
    del policy
    if language == "en":
        return (
            "You are W06, the presentation-only report writer. Use only terminal structured WorkerResults. "
            "Do not retrieve data, re-read raw news/RAG records, perform specialist analysis, invent entities, "
            "numbers, risks, recommendations, or causal claims. When the upstream result is EntityAnalysisResult, "
            "only reorganize its facts, analysis, model_signals, relation_interpretations, uncertainties, conclusion, "
            "and source claim ids. Return concise section objects matching the schema; do not duplicate all upstream "
            "claims into a second claim list and do not put a complete report in an additional field. "
            "Do not expose internal worker names, task ids, tools, GraphRef fields, or storage details. "
            "completion_report.report_source must be llm."
        )
    return (
        "你是 W06，只负责把终端专业 WorkerResult 整理为用户可读 Markdown，不承担任何专业分析。"
        "不得检索数据、重新读取原始新闻或 RAG 记录、补造实体、数值、风险、建议或因果结论。"
        "当上游是 EntityAnalysisResult 时，只能重组其中 facts、analysis、model_signals、"
        "relation_interpretations、uncertainties、conclusion 和 source claim 引用。"
        "严格输出分节结构，每个分节给出 heading、markdown 和 source_claim_ids；不要再复制一份完整 claims 列表，"
        "也不要额外输出另一份完整报告。不得暴露内部 Worker 名称、task_id、工具、GraphRef 或数据库实现。"
        "必须逐项评估 completion_contract，completion_report.report_source 必须为 llm。"
    )


def _report_llm_schema() -> dict[str, Any]:
    section_schema = object_schema(
        {
            "heading": string_schema(min_length=1),
            "markdown": string_schema(min_length=1),
            "source_claim_ids": array_schema(string_schema(min_length=1), max_items=30),
        },
        required=["heading", "markdown", "source_claim_ids"],
        additional_properties=False,
    )
    return object_schema(
        {
            "title": string_schema(min_length=1),
            "sections": array_schema(
                section_schema,
                min_items=1,
                max_items=_REPORT_MAX_SECTIONS,
            ),
            "limitations": array_schema({"type": "string"}, max_items=20),
            "completion_report": completion_report_schema(),
        },
        required=["title", "sections", "limitations", "completion_report"],
        additional_properties=False,
    )


def _compose_markdown(
    title: str,
    sections: list[dict[str, Any]],
    limitations: list[str],
    language: str,
) -> str:
    parts = [f"# {title.strip()}"]
    for row in sections:
        heading = str(row.get("heading") or "").strip()
        markdown = str(row.get("markdown") or "").strip()
        if heading and markdown:
            parts.append(f"## {heading}\n\n{markdown}")
    if limitations:
        limit_title = "Limitations" if language == "en" else "局限与不确定性"
        bullets = "\n".join(f"- {item}" for item in limitations if str(item).strip())
        if bullets:
            parts.append(f"## {limit_title}\n\n{bullets}")
    return "\n\n".join(parts).strip()


def _failed_completion(task: GraphAgentTask, message: str) -> dict[str, Any]:
    criteria = [
        {
            "criterion_id": str(item.get("criterion_id") or ""),
            "satisfied": False,
            "reason": message[:1000],
            "source_refs": [],
        }
        for item in task.completion_contract.get("criteria") or []
        if isinstance(item, dict)
    ]
    return build_completion_report(
        task,
        execution_status="failed",
        contract_status="not_evaluated",
        business_status="unknown",
        completion_status="not_completed",
        expected_task_completed=False,
        produced_information_slots=[],
        criterion_results=criteria,
        limitations=[message],
        failure_kind="worker_execution_failure",
    )


def run_report_writer(
    llm_service: LLMService,
    task: GraphAgentTask,
    dependency_results: dict[str, dict[str, Any]],
    language: str,
    *,
    resolved_inputs: dict[str, Any] | None = None,
) -> GraphWorkerResult:
    safe_results, selected_dependency_results, requested_task_ids, authority_results = _safe_results(
        task, dependency_results, resolved_inputs
    )
    if not safe_results:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            output_type="FinalReport",
            data=None,
            error=None,
            focus_refs=task.focus_refs,
            summary="报告生成缺少上游 GraphWorkerResult。",
            missing_items=[
                MissingContextItem(
                    key="worker_results",
                    description="需要上游专业 Worker 的标准结果。",
                    searched_sources=["dependency_results"],
                )
            ],
        )

    objective = str(task.args.get("report_goal") or task.objective)
    policy = build_report_policy(
        objective,
        safe_results,
        request_mode=str(task.metadata.get("request_mode") or ""),
        goal_contract=dict(task.metadata.get("goal_contract") or {}),
        authority_results=authority_results,
    )
    output_schema = _report_llm_schema()
    upstream_claims = _claim_catalog(safe_results)
    allowed_source_task_ids = set(requested_task_ids or selected_dependency_results.keys())
    input_diagnostics = _report_input_diagnostics(safe_results, upstream_claims)
    validation_snapshot: dict[str, Any] = {}
    composed_snapshot: dict[str, str] = {}

    def validate(candidate: dict[str, Any]) -> None:
        nonlocal validation_snapshot, composed_snapshot
        validate_schema(candidate, output_schema)
        validate_completion_report(
            dict(candidate.get("completion_report") or {}),
            dict(task.completion_contract or {}),
            path="$.completion_report",
        )
        seen_headings: set[str] = set()
        used_claim_ids: list[str] = []
        for index, row in enumerate(candidate.get("sections") or []):
            heading = str(row.get("heading") or "").strip()
            if heading in seen_headings:
                raise WorkerContractViolation(
                    "duplicate_report_section_heading", "$.sections", heading
                )
            seen_headings.add(heading)
            markdown = str(row.get("markdown") or "")
            if len(markdown) > _REPORT_MAX_SECTION_CHARS:
                raise WorkerContractViolation(
                    "report_section_too_long", f"$.sections[{index}].markdown", str(len(markdown))
                )
            for source_claim_id in row.get("source_claim_ids") or []:
                source_claim_id = str(source_claim_id)
                if source_claim_id not in upstream_claims:
                    raise WorkerContractViolation(
                        "report_section_unknown_source_claim_id",
                        f"$.sections[{index}].source_claim_ids",
                        source_claim_id,
                    )
                if source_claim_id not in used_claim_ids:
                    used_claim_ids.append(source_claim_id)
        limitations = [
            str(item).strip()
            for item in candidate.get("limitations") or []
            if str(item).strip()
        ]
        answer = _compose_markdown(
            str(candidate.get("title") or objective),
            list(candidate.get("sections") or []),
            limitations,
            language,
        )
        report_validation = validate_report_output(answer, policy)
        validation_snapshot = report_validation.to_dict()
        composed_snapshot = {
            "content": answer,
            "used_source_claim_ids": json.dumps(used_claim_ids, ensure_ascii=False),
        }
        if not report_validation.valid:
            codes = ",".join(item.code for item in report_validation.issues)
            raise WorkerContractViolation(
                "report_output_validation_failed",
                "$.sections",
                codes,
            )

    try:
        generated = llm_service.generate_json(
            stage="graph_report_writer",
            messages=[
                {"role": "system", "content": _system_prompt(language, policy)},
                {
                    "role": "user",
                    "content": compact_json_dumps(
                        {
                            "objective": objective,
                            "report_policy": policy.to_prompt_dict(),
                            "report_authority_context": {
                                "source_task_ids": requested_task_ids or list(selected_dependency_results.keys()),
                                "allowed_entities": [item.to_dict() for item in policy.entities],
                                "authority_compiled_from": "terminal_upstream_worker_results",
                            },
                            "terminal_worker_results": safe_results,
                            "available_source_claim_ids": sorted(upstream_claims.keys()),
                            "allowed_source_task_ids": sorted(allowed_source_task_ids),
                            "report_input_diagnostics": input_diagnostics,
                            "completion_contract": task.completion_contract,
                            "report_output_schema": schema_for_prompt(output_schema),
                            "reply_language": language,
                        },
                    ),
                },
            ],
            max_output_tokens=_REPORT_MAX_OUTPUT_TOKENS,
            validator=validate,
            operation="write_graph_grounded_report",
            repair_mode="targeted",
            repair_guidance=(
                "只修复 sectioned_markdown_report.v1 的 JSON 结构、source_claim_ids、completion_report 或报告校验问题。"
                "不得增加上游没有的事实、实体、数值、风险、建议或来源。每个 section 保持简洁并返回完整闭合 JSON。"
            ),
        )
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        incomplete_json = "incomplete json" in message.lower()
        failure_diagnostics = {
            **input_diagnostics,
            "failure_phase": "llm_json_generation_or_repair",
            "exception_type": exc.__class__.__name__,
            "exception_message": message[:2000],
            "incomplete_json_detected": incomplete_json,
            "repair_mode": "targeted",
            "schema_required_fields": ["title", "sections", "limitations", "completion_report"],
        }
        completion = _failed_completion(task, message)
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.FAILED,
            output_type="FinalReport",
            payload_schema="final_report.v1",
            payload=None,
            data=None,
            error={
                "code": "report_llm_generation_failed",
                "message": message[:2000],
                "component": task.assigned_agent,
                "retryable": True,
                "failure_phase": "llm_json_generation_or_repair",
                "incomplete_json_detected": incomplete_json,
            },
            focus_refs=task.focus_refs,
            summary="W06 未能生成完整、通过 Schema 校验的 Markdown 报告。",
            findings=[
                {"kind": "report_input_diagnostics", **safe_public_value(input_diagnostics)},
                {"kind": "report_failure_diagnostics", **safe_public_value(failure_diagnostics)},
            ],
            confidence=0.0,
            warnings=[message[:1000]],
            completion=completion,
            metadata={
                "structured_report_output": True,
                "sectioned_markdown_output": True,
                "report_failure_diagnostics_logged": True,
            },
        )

    completion = dict(generated.get("completion_report") or {})
    sections = [dict(item) for item in generated.get("sections") or [] if isinstance(item, dict)]
    limitations = list(
        dict.fromkeys(
            str(item).strip()
            for item in generated.get("limitations") or []
            if str(item).strip()
        )
    )
    upstream_limitations = [
        str(item.get("summary") or "")[:500]
        for item in safe_results
        if str(item.get("status") or "") not in {"completed", "proposal_ready"}
    ]
    limitations = list(dict.fromkeys([*limitations, *[item for item in upstream_limitations if item]]))
    title = str(generated.get("title") or objective).strip()
    answer = _compose_markdown(title, sections, limitations, language)
    used_source_claim_ids = list(
        dict.fromkeys(
            str(source_claim_id)
            for section in sections
            for source_claim_id in section.get("source_claim_ids") or []
            if str(source_claim_id).strip()
        )
    )
    source_task_ids = requested_task_ids or list(selected_dependency_results.keys())
    completed = bool(completion.get("expected_task_completed"))
    output_diagnostics = {
        "section_count": len(sections),
        "content_chars": len(answer),
        "limitation_count": len(limitations),
        "used_source_claim_count": len(used_source_claim_ids),
        "source_task_count": len(source_task_ids),
        "markdown_composed_by_runtime": True,
    }
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED if completed else ResultStatus.PARTIAL,
        output_type="FinalReport",
        payload_schema="final_report.v1",
        data={
            "title": title[:300],
            "language": "en" if language == "en" else "zh",
            "source_task_ids": source_task_ids,
            "used_source_claim_ids": used_source_claim_ids,
            "sections": safe_public_value(sections),
            "content": answer,
            "limitations": limitations,
        },
        error=None,
        focus_refs=task.focus_refs,
        summary=answer,
        findings=[
            {"kind": "report_input_diagnostics", **safe_public_value(input_diagnostics)},
            {"kind": "report_output_diagnostics", **safe_public_value(output_diagnostics)},
        ],
        confidence=(
            min([float(item.get("confidence") or 0.0) for item in safe_results] or [0.0])
            if completed
            else 0.0
        ),
        evidence_refs=refs_from_dependencies(
            selected_dependency_results,
            kinds={GraphNodeKind.EVIDENCE},
        ),
        graph_path_refs=[
            GraphPathRef(**path)
            for item in safe_results
            for path in item.get("graph_path_refs") or []
            if isinstance(path, dict)
        ],
        warnings=[],
        completion=completion,
        metadata={
            "report_policy": policy.to_prompt_dict(),
            "report_validation": validation_snapshot,
            "structured_report_output": True,
            "sectioned_markdown_output": True,
            "report_diagnostics_logged": True,
            "full_dag_replan_used": False,
        },
    )


__all__ = ["run_report_writer"]
