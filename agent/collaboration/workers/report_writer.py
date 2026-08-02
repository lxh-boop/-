"""Generate the final report from sanitized upstream Worker results.

The report writer receives only ``GraphWorkerResult`` contracts and uses the
run-scoped LLM service for synthesis. It does not query providers, re-read raw
evidence, resolve entities, call business tools, perform specialist analysis,
or mutate state. Generated text is validated before it can become the public
FinalReport.
"""

from __future__ import annotations

import json
from typing import Any

from core.llm import LLMService

from agent.console_trace import flow_event
from agent.graph.contracts import GraphNodeKind, GraphPathRef

from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from ..report_validation import (
    ReportPolicy,
    build_report_policy,
    validate_report_output,
)
from .common import dependency_results as dependency_result_items
from .common import refs_from_dependencies, safe_public_value


def _safe_results(
    task: GraphAgentTask,
    dependency_results: dict[str, dict[str, Any]],
    resolved_inputs: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    requested_task_ids = task.input_task_ids("upstream_results")
    selected_dependency_results = {
        task_id: payload
        for task_id, payload in dependency_results.items()
        if not requested_task_ids or task_id in set(requested_task_ids)
    }
    explicit_items: list[dict[str, Any]] = []
    for role_value in dict(resolved_inputs or {}).values():
        values = role_value if isinstance(role_value, list) else [role_value]
        for value in values:
            if isinstance(value, dict):
                explicit_items.append(value)
    if explicit_items:
        safe_results = [
            {
                "task_id": str(item.get("from_task_id") or ""),
                "status": str(item.get("status") or ""),
                "output_type": str(item.get("output_type") or ""),
                "payload_schema": str(item.get("payload_schema") or ""),
                "payload_version": str(item.get("payload_version") or ""),
                "payload": safe_public_value(item.get("payload")),
                "summary": str(item.get("summary") or "")[:2000],
                "evidence_refs": safe_public_value(item.get("evidence_refs") or []),
                "artifact_refs": safe_public_value(item.get("artifact_refs") or []),
                "graph_path_refs": safe_public_value(item.get("graph_path_refs") or []),
                "confidence": item.get("confidence"),
            }
            for item in explicit_items
        ]
    else:
        safe_results = [
            {
                "contract_version": str(
                    item.get("contract_version") or "graph_worker_result.v1"
                ),
                "task_id": str(item.get("task_id") or ""),
                "agent_id": str(item.get("agent_id") or ""),
                "status": str(item.get("status") or ""),
                "output_type": str(item.get("output_type") or ""),
                "payload_schema": str(item.get("payload_schema") or ""),
                "payload_version": str(item.get("payload_version") or ""),
                "payload": safe_public_value(item.get("payload", item.get("data"))),
                "summary": str(item.get("summary") or "")[:2000],
                "evidence_refs": safe_public_value(item.get("evidence_refs") or []),
                "artifact_refs": safe_public_value(item.get("artifact_refs") or []),
                "graph_path_refs": safe_public_value(item.get("graph_path_refs") or []),
                "confidence": item.get("confidence"),
            }
            for item in dependency_result_items(selected_dependency_results)
        ]
    return safe_results, selected_dependency_results, requested_task_ids


def _system_prompt(language: str, policy: ReportPolicy) -> str:
    if language == "en":
        base = (
            "You are the financial Agent report writer. Use only the supplied "
            "GraphWorkerResult contracts. Do not re-parse raw evidence or invent "
            "entity identities, evidence, numbers, causal paths, specialist judgments, "
            "or recommendations. Clearly separate validated facts, claims, indirect "
            "relations, and uncertainty. Do not expose internal agents, task IDs, tools, "
            "GraphRef fields, or storage details. Return only the complete user-facing "
            "report body, not JSON or a WorkerResult envelope."
        )
        strict = (
            " Structured fields and authoritative_entities are the only factual source. "
            "Never derive a company name from a code, position_id, memory, or general "
            "knowledge. When a display label is missing, show the public code and state "
            "that the name was not provided. A view-only request may only display verified "
            "account/position facts, data time, and limitations. It must not add risk "
            "assessment, industry judgment, causal analysis, or action advice. Risk "
            "conclusions require an upstream PortfolioRiskResult. Portfolio adjustment content "
            "requires an upstream ReviewedProposal. Clearly state that the proposal is pending "
            "approval and has not been executed. Keep the report concise."
        )
        return base + strict

    base = (
        "你是金融 Agent 的 Report Writer。你只能使用输入中的 GraphWorkerResult，不能重新解析原始新闻正文，"
        "不能猜证券代码，不能引用未提供的实体、证据、数值或影响路径。明确区分已验证事实、来源声明、"
        "间接关系和不确定性。若没有影响路径，必须明确说当前证据不足，不能把新闻提及当作因果影响。"
        "不要暴露内部 Agent 名称、task_id、GraphRef 技术字段、工具名或数据库实现。"
        "使用中文回答。输出完整的用户可读报告正文，不要输出 WorkerResult 外壳或 JSON。"
    )
    strict = (
        "在上述职责基础上增加以下强约束：结构化字段和 report_policy.authoritative_entities 是唯一事实来源；"
        "禁止根据证券代码、position_id、上下文记忆或常识自行补充证券名称。权威名称缺失时，只展示代码并注明"
        "“名称未提供”。禁止自行补充行业、新闻影响、风险结论或建议。若 report_policy.view_only=true，"
        "只展示用户要求的账户和持仓事实、数据时间及明确限制；除非用户目标明确要求，否则不要展开订单、"
        "风险、行业、策略或建议。风险结论必须来自上游 PortfolioRiskResult；持仓调整方案必须同时满足用户明确要求"
        "且上游存在 ReviewedProposal，并明确说明该预案待审批且尚未执行。"
        "当用户明确询问持仓如何调整时，必须忠实呈现上游 ReviewedProposal，不能把目标弱化为仅展示持仓，"
        "也不能声称用户未请求建议。缺失字段写“数据未提供”，不得推测。报告应简洁，避免重复。"
    )
    return base + strict


def _generation_payload(
    task: GraphAgentTask,
    safe_results: list[dict[str, Any]],
    policy: ReportPolicy,
) -> dict[str, Any]:
    return {
        "objective": str(task.args.get("report_goal") or task.objective),
        "report_policy": policy.to_prompt_dict(),
        "resolved_worker_inputs": safe_results,
    }


def _repair_messages(
    *,
    system: str,
    generation_payload: dict[str, Any],
    previous_answer: str,
    validation: dict[str, Any],
    language: str,
) -> list[dict[str, Any]]:
    if language == "en":
        instruction = (
            "The previous report failed output validation. Return a complete replacement "
            "report, not a patch. Remove every unsupported claim listed below. Preserve "
            "only facts in resolved_worker_inputs and obey report_policy exactly."
        )
    else:
        instruction = (
            "上一次报告未通过输出校验。请生成一份完整替换稿，不要只输出修改片段。"
            "必须删除下列所有无依据内容，只保留 resolved_worker_inputs 中的事实，并严格遵守 report_policy。"
        )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                {
                    **generation_payload,
                    "repair_instruction": instruction,
                    "validation_result": validation,
                    "previous_report": str(previous_answer or "")[:12000],
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]


def run_report_writer(
    llm_service: LLMService,
    task: GraphAgentTask,
    dependency_results: dict[str, dict[str, Any]],
    language: str,
    *,
    resolved_inputs: dict[str, Any] | None = None,
) -> GraphWorkerResult:
    safe_results, selected_dependency_results, requested_task_ids = _safe_results(
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
    policy = build_report_policy(objective, safe_results)
    system = _system_prompt(language, policy)
    generation_payload = _generation_payload(task, safe_results, policy)
    answer = llm_service.generate_text(
        stage="graph_report_writer",
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    generation_payload,
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
        max_output_tokens=3000,
        temperature=0.0,
        operation="write_graph_grounded_report",
    )
    validation = validate_report_output(str(answer or ""), policy)
    recovery = (
        "none"
        if validation.valid
        else "targeted_w06_repair"
        if validation.repairable
        else "required_upstream_recovery"
    )
    flow_event(
        "REPORT_OUTPUT_VALIDATION_COMPLETED",
        {
            "task_id": task.task_id,
            "attempt": "primary",
            "valid": validation.valid,
            "issue_count": len(validation.issues),
            "issues": [item.to_dict() for item in validation.issues],
            "recovery": recovery,
            "upstream_tasks_reused": requested_task_ids
            or list(selected_dependency_results.keys()),
        },
        run_id=task.run_id,
        level="INFO" if validation.valid else "WARNING",
    )

    generation_attempts = 1
    repair_attempted = False
    repair_succeeded = False
    if not validation.valid and validation.repairable:
        repair_attempted = True
        flow_event(
            "REPORT_OUTPUT_REPAIR_STARTED",
            {
                "task_id": task.task_id,
                "issue_count": len(validation.issues),
                "full_dag_replan": False,
                "upstream_results_reused": True,
            },
            run_id=task.run_id,
            level="WARNING",
        )
        repaired_answer = llm_service.generate_text(
            stage="graph_report_writer_repair",
            messages=_repair_messages(
                system=system,
                generation_payload=generation_payload,
                previous_answer=str(answer or ""),
                validation=validation.to_dict(),
                language=language,
            ),
            max_output_tokens=3000,
            temperature=0.0,
            operation="repair_graph_grounded_report",
        )
        generation_attempts = 2
        repaired_validation = validate_report_output(str(repaired_answer or ""), policy)
        flow_event(
            "REPORT_OUTPUT_VALIDATION_COMPLETED",
            {
                "task_id": task.task_id,
                "attempt": "targeted_repair",
                "valid": repaired_validation.valid,
                "issue_count": len(repaired_validation.issues),
                "issues": [item.to_dict() for item in repaired_validation.issues],
                "full_dag_replan": False,
                "upstream_results_reused": True,
            },
            run_id=task.run_id,
            level="INFO" if repaired_validation.valid else "ERROR",
        )
        if repaired_validation.valid:
            answer = repaired_answer
            validation = repaired_validation
            repair_succeeded = True
        else:
            validation = repaired_validation

    statuses = {str(item.get("status") or "") for item in safe_results}
    upstream_partial = bool(statuses & {"partial", "need_context", "failed"})
    validation_failed = not validation.valid
    if validation_failed:
        missing_required_upstream = any(
            item.code in {
                "missing_required_risk_worker_output",
                "missing_required_strategy_worker_output",
            }
            for item in validation.issues
        )
        answer = (
            (
                "当前持仓调整链路缺少必要的风险或策略 Worker 结果。已保留成功的上游查询，"
                "但不会由 W06 自行补写调整建议；需要先恢复失败或缺失的上游专业任务。"
            )
            if language != "en" and missing_required_upstream
            else (
                "本次自然语言报告未通过事实与职责边界校验，或未满足用户目标。上游结果已保留，"
                "系统未返回未经验证的实体、结论或建议。"
            )
            if language != "en"
            else (
                "The adjustment chain is missing a required risk or strategy Worker result. "
                "Successful upstream results were preserved, and W06 did not invent advice."
            )
            if missing_required_upstream
            else (
                "The generated report did not pass grounding, scope, or goal-completion validation. "
                "Upstream results were preserved and unsupported content was not returned."
            )
        )

    final_status = (
        ResultStatus.PARTIAL
        if upstream_partial or validation_failed
        else ResultStatus.COMPLETED
    )
    source_task_ids = requested_task_ids or list(selected_dependency_results.keys())
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=final_status,
        output_type="FinalReport",
        data={
            "title": objective[:300],
            "language": "en" if language == "en" else "zh",
            "source_task_ids": source_task_ids,
            "content": str(answer or ""),
            "limitations": [
                *[
                    str(item.get("summary") or "")[:500]
                    for item in safe_results
                    if str(item.get("status") or "")
                    in {"partial", "need_context", "failed"}
                ],
                *(
                    ["report_output_validation_failed"]
                    if validation_failed
                    else []
                ),
            ],
        },
        error=(
            {
                "code": (
                    "report_required_upstream_missing"
                    if any(
                        item.code in {
                            "missing_required_risk_worker_output",
                            "missing_required_strategy_worker_output",
                        }
                        for item in validation.issues
                    )
                    else "report_output_validation_failed"
                ),
                "message": "W06 output failed grounding, scope, or goal-completion validation.",
                "component": "REPORT_WRITER",
                "retryable": validation.repairable,
                "repairable": validation.repairable,
            }
            if validation_failed
            else None
        ),
        focus_refs=task.focus_refs,
        summary=str(answer or ""),
        findings=[{"kind": "report", "text": str(answer or "")}],
        confidence=(
            0.0
            if validation_failed
            else min(
                [float(item.get("confidence") or 0.0) for item in safe_results]
                or [0.0]
            )
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
        warnings=(
            [item.code for item in validation.issues]
            if validation_failed
            else []
        ),
        metadata={
            "report_policy": policy.to_prompt_dict(),
            "report_validation": validation.to_dict(),
            "report_generation_attempts": generation_attempts,
            "targeted_repair_used": repair_attempted,
            "targeted_repair_succeeded": repair_succeeded,
            "full_dag_replan_used": False,
            "upstream_recovery_required": bool(
                validation_failed and not validation.repairable
            ),
            # Kept for older trace readers. Planning-time contract repair now
            # prevents an incomplete adjustment DAG from being accepted; a
            # runtime provider failure is not blindly sent back to the planner.
            "partial_dag_replan_required": False,
            "upstream_results_reused": True,
        },
    )
