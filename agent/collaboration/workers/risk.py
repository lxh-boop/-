"""Hybrid LLM + atomic-tool W04 Risk Analyst.

W04 consumes only Runtime-materialized capability slots.  Its private Tool DAG
produces deterministic risk facts; the LLM interprets those facts.  Successful
Worker outputs are published only through ``data["slots"]``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.llm import LLMService

from agent.tool_dag import WorkerToolDagRuntime

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from ..worker_contracts import array_schema, object_schema, string_schema, validate_schema
from .common import materialize_promised_slots, safe_public_value
from .structured_output import generate_json_with_local_structural_repair


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
        },
        required=[
            "portfolio_task_ids",
            "risk_analysis",
            "records",
            "risk_constraints",
            "source_tool_result_refs",
        ],
        additional_properties=False,
    )


def _final_facts(dag_result: Any) -> tuple[dict[str, Any], list[str]]:
    for result in list(getattr(dag_result, "final_results", []) or []):
        data = dict(getattr(result, "data", {}) or {})
        if "risk_facts" in data:
            return data, [f"tool_result:{task_id}" for task_id in dag_result.final_output_task_ids]
    return {}, []


def _portfolio_context(
    task: GraphAgentTask,
    resolved_inputs: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Build the private risk-tool context from direct Runtime Slot values.

    This deliberately does not understand old Worker envelopes such as
    ``{"payload": ...}``.  Runtime projection already materializes the Slot value.
    """

    resolved = dict(resolved_inputs or {})
    state: dict[str, Any] = {}
    positions: list[dict[str, Any]] | None = None
    source_task_ids: list[str] = []

    for slot_id, value in resolved.items():
        for task_id in task.input_task_ids(str(slot_id)):
            if task_id not in source_task_ids:
                source_task_ids.append(task_id)
        if isinstance(value, list) and "position" in str(slot_id).lower():
            positions = [dict(item) for item in value if isinstance(item, dict)]
            continue
        if not isinstance(value, dict):
            continue
        lowered = str(slot_id).lower()
        if not state and any(token in lowered for token in ("portfolio", "account", "state")):
            state = dict(value)
        if positions is None:
            rows = value.get("positions") or value.get("display_positions") or value.get("holdings")
            if isinstance(rows, list):
                positions = [dict(item) for item in rows if isinstance(item, dict)]

    if not state:
        # Risk is a portfolio-specific capability. If the contract uses a new
        # semantic key, accept the first structured Slot rather than requiring a
        # hard-coded business slot id.
        state = next((dict(value) for value in resolved.values() if isinstance(value, dict)), {})
    if positions is not None:
        state["positions"] = positions
    return state, source_task_ids


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
    portfolio_payload, portfolio_task_ids = _portfolio_context(task, resolved_inputs)
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

    output_schema = _risk_output_schema()

    def validate(payload: dict[str, Any]) -> None:
        validate_schema(payload, output_schema)
        risk_ids = {
            str(item.get("risk_id") or "")
            for item in payload.get("records") or []
            if isinstance(item, dict)
        }
        for item in payload.get("records") or []:
            unknown = sorted(set(str(ref) for ref in item.get("source_refs") or []) - allowed_source_refs)
            if unknown:
                raise RuntimeError("risk_unknown_source_refs:" + ",".join(unknown))
        for item in payload.get("risk_constraints") or []:
            unknown = sorted(set(str(ref) for ref in item.get("source_risk_ids") or []) - risk_ids)
            if unknown:
                raise RuntimeError("risk_constraint_unknown_risk_ids:" + ",".join(unknown))

    messages = [
        {
            "role": "system",
            "content": (
                "你是 W04 Risk Analyst。你只基于 atomic_risk_facts 形成组合层风险分析和风险约束。"
                "不得重新查询业务状态，不得补造风险事实，不得生成具体买卖动作或 Proposal。"
                "每条 risk item 必须引用 allowed_source_refs；每条 risk constraint 必须引用已输出的 risk_id。"
                "完成度与合同验收由Runtime负责。严格输出 risk_output_schema 对应 JSON。"
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
                    "reply_language": "en" if language == "en" else "zh",
                    "risk_output_schema": output_schema,
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    payload = generate_json_with_local_structural_repair(
        llm_service,
        stage="graph_risk_analyst",
        operation=task.boundary_id,
        messages=messages,
        output_schema=output_schema,
        validator=validate,
        immutable_repair_context={"allowed_source_refs": sorted(allowed_source_refs)},
        repair_guidance="Repair only JSON shape and risk/source references; never invent risk facts or proposals.",
        primary_max_output_tokens=3200,
        repair_max_output_tokens=1800,
        primary_disable_thinking=False,
    )

    risk_bundle = {
        "portfolio_task_ids": [str(item) for item in payload.get("portfolio_task_ids") or portfolio_task_ids],
        "risk_analysis": safe_public_value(payload.get("risk_analysis") or {}),
        "records": safe_public_value(payload.get("records") or []),
        "risk_constraints": safe_public_value(payload.get("risk_constraints") or []),
        "source_tool_result_refs": [str(item) for item in payload.get("source_tool_result_refs") or []],
        "access_mode": "read",
        "persistent_write_performed": False,
    }
    slots = materialize_promised_slots(task, risk_bundle)
    data = {**risk_bundle, "slots": slots}
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        output_type="PortfolioRiskResult",
        data=data,
        error=None,
        focus_refs=task.focus_refs,
        summary=str((risk_bundle.get("risk_analysis") or {}).get("summary") or "已完成组合风险分析。"),
        findings=[{
            "kind": "portfolio_risk",
            "risk_item_count": len(risk_bundle.get("records") or []),
            "constraint_count": len(risk_bundle.get("risk_constraints") or []),
        }],
        confidence=0.9,
        warnings=[str(item) for item in (risk_bundle.get("risk_analysis") or {}).get("limitations") or []],
        metadata={
            "tool_dag_used": True,
            "tool_task_count": len(dag_result.plan.tasks),
            "tool_dag_replan_count": int(dag_result.replan_count),
            "access_mode": "read",
            "persistent_write_performed": False,
        },
    )


__all__ = ["run_risk"]
