"""Hybrid LLM + atomic-tool W04 Risk Analyst.

The Tool DAG calculates structured risk facts. The LLM Worker interprets those
facts into PortfolioRiskResult under prompt/schema constraints. Both stages are
READ and never generate or execute a proposal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.llm import LLMService

from agent.tool_dag import WorkerToolDagRuntime

from ..completion import validate_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from ..worker_contracts import (
    array_schema,
    completion_report_schema,
    object_schema,
    string_schema,
    validate_schema,
)
from .common import safe_public_value


def _risk_output_schema() -> dict[str, Any]:
    risk_item = object_schema(
        {
            "risk_id": string_schema(min_length=1),
            "category": string_schema(min_length=1),
            "level": string_schema(enum=["low", "medium", "high", "unknown"]),
            "statement": string_schema(min_length=1),
            "source_refs": array_schema(string_schema(min_length=1), min_items=1),
            "scope": {"type": "string"},
        },
        required=["risk_id", "category", "level", "statement", "source_refs", "scope"],
        additional_properties=False,
    )
    constraint = object_schema(
        {
            "constraint_id": string_schema(min_length=1),
            "description": string_schema(min_length=1),
            "source_risk_ids": array_schema(string_schema(min_length=1)),
        },
        required=["constraint_id", "description", "source_risk_ids"],
        additional_properties=False,
    )
    return object_schema(
        {
            "portfolio_task_ids": array_schema(string_schema(min_length=1), min_items=1),
            "risk_analysis": object_schema(
                {
                    "summary": string_schema(min_length=1),
                    "risk_items": array_schema(risk_item),
                    "limitations": array_schema({"type": "string"}),
                },
                required=["summary", "risk_items", "limitations"],
                additional_properties=False,
            ),
            "records": array_schema(risk_item),
            "risk_constraints": array_schema(constraint),
            "source_tool_result_refs": array_schema(string_schema(min_length=1), min_items=1),
            "completion_report": completion_report_schema(),
        },
        required=[
            "portfolio_task_ids",
            "risk_analysis",
            "records",
            "risk_constraints",
            "source_tool_result_refs",
            "completion_report",
        ],
        additional_properties=False,
    )


def _final_facts(dag_result: Any) -> tuple[dict[str, Any], list[str]]:
    for result in list(getattr(dag_result, "final_results", []) or []):
        data = dict(getattr(result, "data", {}) or {})
        if "risk_facts" in data:
            return data, [f"tool_result:{task_id}" for task_id in dag_result.final_output_task_ids]
    return {}, []


def run_risk(
    llm_service: LLMService,
    tool_dag_runtime: WorkerToolDagRuntime,
    task: GraphAgentTask,
    output_dir: str | Path,
    db_path: str | Path | None,
    *,
    resolved_inputs: dict[str, Any] | None = None,
    worker_prompt: str,
    allowed_tool_names: list[str],
    language: str = "zh",
) -> GraphWorkerResult:
    resolved = dict(resolved_inputs or {})
    portfolio_binding = resolved.get("portfolio_state")
    if isinstance(portfolio_binding, list):
        portfolio_binding = portfolio_binding[0] if portfolio_binding else {}
    portfolio_payload = (
        dict(portfolio_binding.get("payload") or {})
        if isinstance(portfolio_binding, dict)
        else {}
    )
    portfolio_task_ids = task.input_task_ids("portfolio_state")
    if not portfolio_payload:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            output_type="PortfolioRiskResult",
            data=None,
            error=None,
            focus_refs=task.focus_refs,
            summary="缺少结构化组合状态，无法进行组合风险分析。",
        )

    available_context = {
        "portfolio_state": safe_public_value(portfolio_payload),
        "risk_question": str(task.args.get("risk_question") or task.objective or ""),
        "user_id": task.user_id,
    }
    dag_result = tool_dag_runtime.run(
        worker_task_id=task.task_id,
        worker_role=task.assigned_agent,
        boundary_id=task.boundary_id,
        worker_objective=task.objective,
        worker_prompt=worker_prompt,
        available_context=available_context,
        required_output_keys=["risk_facts", "source_refs", "limitations"],
        completion_criteria=[
            "根据风险问题选择必要的原子风险事实工具，不使用固定工具链。",
            "最终节点汇总所选工具的结构化风险事实、来源和限制。",
            "所有工具只读，不形成 Proposal，不修改业务状态。",
        ],
        allowed_tool_names=list(allowed_tool_names),
        execution_context={
            "user_id": task.user_id,
            "conversation_id": task.session_id,
            "session_id": task.session_id,
            "run_id": task.run_id,
            "task_id": task.task_id,
            "agent_role": task.assigned_agent,
            "output_dir": output_dir,
            "db_path": db_path,
        },
        read_only=True,
        max_replans=1,
    )
    facts, source_tool_refs = _final_facts(dag_result)
    if not dag_result.success or not facts:
        failed = [record.to_dict() for record in dag_result.node_records if not record.success]
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.FAILED,
            output_type="PortfolioRiskResult",
            data=None,
            error={
                "code": "risk_tool_dag_failed",
                "message": "W04 私有风险 Tool DAG 未形成结构化风险事实。",
                "component": task.assigned_agent,
                "retryable": any(bool(item.get("retryable")) for item in failed),
                "failure_details": failed[:10],
            },
            focus_refs=task.focus_refs,
            summary="组合风险事实计算失败。",
            warnings=[str(item) for item in facts.get("limitations") or []],
        )

    allowed_source_refs = set(source_tool_refs) | {
        str(item) for item in facts.get("source_refs") or [] if str(item)
    }

    def validate(payload: dict[str, Any]) -> None:
        validate_schema(payload, _risk_output_schema())
        risk_ids = {
            str(item.get("risk_id") or "")
            for item in payload.get("records") or []
            if isinstance(item, dict)
        }
        for item in payload.get("records") or []:
            unknown = sorted(
                set(str(ref) for ref in item.get("source_refs") or []) - allowed_source_refs
            )
            if unknown:
                raise RuntimeError("risk_unknown_source_refs:" + ",".join(unknown))
        for item in payload.get("risk_constraints") or []:
            unknown = sorted(
                set(str(ref) for ref in item.get("source_risk_ids") or []) - risk_ids
            )
            if unknown:
                raise RuntimeError("risk_constraint_unknown_risk_ids:" + ",".join(unknown))
        validate_completion_report(
            dict(payload.get("completion_report") or {}),
            dict(task.completion_contract or {}),
            path="$.completion_report",
        )

    payload = llm_service.generate_json(
        stage="graph_risk_analyst",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是 W04 Risk Analyst。你只基于 atomic_risk_facts 形成组合层风险分析和风险约束。"
                    "不得重新查询业务状态，不得补造风险事实，不得生成具体买卖动作或 Proposal。"
                    "风险分析和约束是当前 Run 内的 READ 结果。每条 risk item 必须引用 allowed_source_refs；"
                    "每条 risk constraint 必须引用已输出的 risk_id。逐项对照 completion_contract 返回"
                    "completion_report，report_source 必须为 llm。程序仅检查 Schema、引用和流程，"
                    "风险含义由你基于结构化事实判断。严格输出 risk_output_schema 对应 JSON。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "risk_question": str(task.args.get("risk_question") or task.objective or ""),
                        "portfolio_task_ids": portfolio_task_ids,
                        "atomic_risk_facts": safe_public_value(facts),
                        "allowed_source_refs": sorted(allowed_source_refs),
                        "completion_contract": dict(task.completion_contract or {}),
                        "reply_language": "en" if language == "en" else "zh",
                        "risk_output_schema": _risk_output_schema(),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
        max_output_tokens=3200,
        validator=validate,
        operation=task.boundary_id,
        repair_mode="targeted",
        disable_thinking=False,
        repair_guidance=(
            "只修复 JSON Schema、risk/source 引用和 completion_report。不得修改原子风险事实或生成 Proposal。"
        ),
    )
    completion = dict(payload.get("completion_report") or {})
    completed = bool(completion.get("expected_task_completed"))
    result_status = ResultStatus.COMPLETED if completed else ResultStatus.PARTIAL
    data = {
        "portfolio_task_ids": [str(item) for item in payload.get("portfolio_task_ids") or portfolio_task_ids],
        "risk_analysis": safe_public_value(payload.get("risk_analysis") or {}),
        "records": safe_public_value(payload.get("records") or []),
        "risk_constraints": safe_public_value(payload.get("risk_constraints") or []),
        "source_tool_result_refs": [str(item) for item in payload.get("source_tool_result_refs") or []],
        "access_mode": "read",
        "persistent_write_performed": False,
    }
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=result_status,
        output_type="PortfolioRiskResult",
        data=data,
        error=None,
        focus_refs=task.focus_refs,
        summary=str((data.get("risk_analysis") or {}).get("summary") or "已完成组合风险分析。"),
        findings=[
            {
                "kind": "portfolio_risk",
                "risk_item_count": len(data.get("records") or []),
                "constraint_count": len(data.get("risk_constraints") or []),
            }
        ],
        confidence=0.9 if completed else 0.6,
        warnings=[str(item) for item in (data.get("risk_analysis") or {}).get("limitations") or []],
        completion=completion,
        metadata={
            "tool_dag_used": True,
            "tool_task_count": len(dag_result.plan.tasks),
            "tool_dag_replan_count": int(dag_result.replan_count),
            "access_mode": "read",
            "persistent_write_performed": False,
        },
    )


__all__ = ["run_risk"]
