"""Generate a final report from sanitized upstream Worker results.

The report LLM is constrained by a Worker-private prompt, structured input,
structured JSON output, and schema validation. Program rules only route the
validated completion report; they do not infer completion from free-form text.
"""

from __future__ import annotations

import json
from typing import Any

from core.llm import LLMService

from agent.graph.contracts import GraphNodeKind, GraphPathRef

from ..completion import validate_completion_report
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
        explicit_items.extend(value for value in values if isinstance(value, dict))

    source_items = explicit_items or dependency_result_items(selected_dependency_results)
    safe_results: list[dict[str, Any]] = []
    for item in source_items:
        safe_results.append(
            {
                "contract_version": str(
                    item.get("contract_version") or "graph_worker_result.v1"
                ),
                "task_id": str(item.get("from_task_id") or item.get("task_id") or ""),
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
                "completion": safe_public_value(item.get("completion") or {}),
            }
        )
    return safe_results, selected_dependency_results, requested_task_ids


def _system_prompt(language: str, policy: ReportPolicy) -> str:
    if language == "en":
        return (
            "You are the financial Agent report writer. Use only the supplied "
            "GraphWorkerResult contracts. Do not re-parse raw evidence or invent "
            "entity identities, evidence, numbers, causal paths, specialist judgments, "
            "or recommendations. Clearly separate validated facts, claims, indirect "
            "relations, and uncertainty. Do not expose internal agents, task IDs, tools, "
            "GraphRef fields, or storage details. Structured fields and authoritative_entities "
            "are the only factual source. Risk conclusions require an upstream PortfolioRiskResult. "
            "Portfolio adjustment content requires an upstream ReviewedProposal and must state that "
            "the proposal is pending approval and has not been executed. Put the complete user-facing "
            "report in the JSON content field. Evaluate every completion criterion from the structured "
            "inputs. Do not output freeze, reuse, or replan decisions."
        )
    return (
        "你是金融 Agent 的 Report Writer。你只能使用输入中的 GraphWorkerResult，不能重新解析原始新闻正文，"
        "不能猜证券代码，不能引用未提供的实体、证据、数值或影响路径。明确区分已验证事实、来源声明、"
        "间接关系和不确定性。不要暴露内部 Agent 名称、task_id、GraphRef 技术字段、工具名或数据库实现。"
        "结构化字段和 report_policy.authoritative_entities 是唯一事实来源。风险结论必须来自上游 PortfolioRiskResult；"
        "持仓调整方案必须来自上游 ReviewedProposal，并明确待审批且尚未执行。把完整用户报告放入 JSON 的 content 字段。"
        "必须逐项对照 completion_contract 评估任务是否完成；字段存在不等于用户目标已完成。"
        "不得输出 should_freeze、reusable 或 replan 等流程控制字段。"
    )


def _report_llm_schema() -> dict[str, Any]:
    return object_schema(
        {
            "content": string_schema(min_length=1),
            "limitations": array_schema({"type": "string"}),
            "completion_report": completion_report_schema(),
        },
        required=["content", "limitations", "completion_report"],
        additional_properties=False,
    )


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
    output_schema = _report_llm_schema()
    validation_snapshot: dict[str, Any] = {}

    def validate(candidate: dict[str, Any]) -> None:
        nonlocal validation_snapshot
        validate_schema(candidate, output_schema)
        validate_completion_report(
            dict(candidate.get("completion_report") or {}),
            dict(task.completion_contract or {}),
            path="$.completion_report",
        )
        report_validation = validate_report_output(
            str(candidate.get("content") or ""),
            policy,
        )
        validation_snapshot = report_validation.to_dict()
        if not report_validation.valid:
            codes = ",".join(item.code for item in report_validation.issues)
            raise WorkerContractViolation(
                "report_output_validation_failed",
                "$.content",
                codes,
            )

    generated = llm_service.generate_json(
        stage="graph_report_writer",
        messages=[
            {"role": "system", "content": _system_prompt(language, policy)},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "objective": objective,
                        "report_policy": policy.to_prompt_dict(),
                        "resolved_worker_inputs": safe_results,
                        "completion_contract": task.completion_contract,
                        "report_output_schema": output_schema,
                        "reply_language": language,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
        max_output_tokens=3200,
        validator=validate,
        operation="write_graph_grounded_report",
        repair_mode="targeted",
        repair_guidance=(
            "只修复 report_output_schema、completion_report 或报告校验指出的问题。"
            "保留合法上游事实，不新增实体、数值、风险、建议或来源。返回完整 JSON。"
        ),
    )

    answer = str(generated.get("content") or "")
    completion = dict(generated.get("completion_report") or {})
    source_task_ids = requested_task_ids or list(selected_dependency_results.keys())
    upstream_limitations = [
        str(item.get("summary") or "")[:500]
        for item in safe_results
        if str(item.get("status") or "") not in {"completed", "proposal_ready"}
    ]
    limitations = list(
        dict.fromkeys(
            [
                *[
                    str(item)
                    for item in generated.get("limitations") or []
                    if str(item).strip()
                ],
                *[item for item in upstream_limitations if item],
            ]
        )
    )
    completed = bool(completion.get("expected_task_completed"))
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED if completed else ResultStatus.PARTIAL,
        output_type="FinalReport",
        data={
            "title": objective[:300],
            "language": "en" if language == "en" else "zh",
            "source_task_ids": source_task_ids,
            "content": answer,
            "limitations": limitations,
        },
        error=None,
        focus_refs=task.focus_refs,
        summary=answer,
        findings=[{"kind": "report", "text": answer}],
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
            "full_dag_replan_used": False,
        },
    )


__all__ = ["run_report_writer"]
