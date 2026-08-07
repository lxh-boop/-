"""Execute W02 capability contracts through its private Tool DAG."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.graph.contracts import GraphNodeKind
from agent.tool_dag import WorkerToolDagRuntime

from ..completion import runtime_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import contract_acceptance_rules, contract_output_slots, execution_safe_value, safe_public_value


_TOOL_SLOT_MAP = {
    "internal.prediction.get_stock": ["entity_model_signals"],
    "internal.ranking.get_latest": ["market_ranking_signals"],
    "internal.model.get_metrics": ["model_quality_metrics"],
    "internal.backtest.get_summary": ["backtest_summary"],
    "internal.strategy.get_selected": ["selected_strategy_state"],
    "internal.portfolio.get_state": ["current_portfolio_state", "portfolio_positions"],
    "internal.account.get_state": ["account_financial_state"],
    "internal.user_profile.get": ["user_profile_state", "user_constraints"],
}


def _available_context(
    task: GraphAgentTask,
    *,
    default_top_k: int,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "user_id": task.user_id,
        "top_k": int(task.business_parameters.get("top_k") or default_top_k or 10),
        "model_name": str(task.business_parameters.get("model_name") or ""),
        "trade_date": str(task.business_parameters.get("trade_date") or ""),
        "holding_period": int(task.business_parameters.get("holding_period") or 0),
        "as_of_time": str(task.as_of_time or ""),
    }
    securities = [
        ref for ref in [*task.focus_refs, *task.context_refs]
        if ref.node_kind == GraphNodeKind.OBJECT and str(ref.node_id).startswith("cn:security:")
    ]
    if len(securities) == 1:
        context["security_node_id"] = securities[0].node_id
    for index, ref in enumerate(securities, start=1):
        context[f"security_node_id_{index}"] = ref.node_id
    return context


def _publish_slots(task: GraphAgentTask, dag_result: Any) -> tuple[dict[str, Any], list[str], list[str]]:
    wanted = set(contract_output_slots(task))
    slots: dict[str, Any] = {}
    warnings: list[str] = []
    for tool_result in list(getattr(dag_result, "final_results", []) or []):
        tool_name = str(getattr(tool_result, "tool_name", "") or "")
        data = execution_safe_value(dict(getattr(tool_result, "data", {}) or {}))
        semantic_slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        for slot, value in semantic_slots.items():
            if str(slot) in wanted:
                slots[str(slot)] = execution_safe_value(value)
        # Backward-compatible fallback for Tools not yet migrated to Tool IO Contract v1.
        if not semantic_slots:
            for slot in _TOOL_SLOT_MAP.get(tool_name, []):
                if slot in wanted:
                    slots[slot] = data
        warnings.extend(str(item) for item in getattr(tool_result, "warnings", []) or [] if str(item))
        warnings.extend(str(item) for item in getattr(tool_result, "errors", []) or [] if str(item))
    produced = [slot for slot in contract_output_slots(task) if slot in slots]
    missing = [slot for slot in contract_output_slots(task) if slot not in slots]
    return slots, produced, list(dict.fromkeys([*warnings, *missing]))


def run_internal_system(
    tool_dag_runtime: WorkerToolDagRuntime,
    task: GraphAgentTask,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    *,
    worker_prompt: str,
    allowed_tool_names: list[str],
    provider: Any = None,
) -> GraphWorkerResult:
    del provider
    required_outputs = contract_output_slots(task)
    available_context = _available_context(task, default_top_k=default_top_k)
    dag_result = tool_dag_runtime.run(
        worker_task_id=task.task_id,
        worker_role=task.assigned_agent,
        boundary_id=task.boundary_id,
        worker_objective=task.objective,
        worker_prompt=worker_prompt,
        available_context=available_context,
        required_output_keys=required_outputs,
        completion_criteria=contract_acceptance_rules(task),
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
    slots, produced, warnings = _publish_slots(task, dag_result)
    success = bool(dag_result.success and not [slot for slot in required_outputs if slot not in produced])
    status = ResultStatus.COMPLETED if success else ResultStatus.PARTIAL if produced else ResultStatus.FAILED
    payload = {
        "boundary_id": task.boundary_id,
        "slots": slots,
        "produced_information_slots": produced,
        "missing_information_slots": [slot for slot in required_outputs if slot not in produced],
        "business_empty": bool(produced and all(value in ({}, [], None) for value in slots.values())),
    }
    result = GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=status,
        output_type="CapabilityResult",
        payload_schema="capability_result.v1",
        payload=payload if produced else None,
        data=payload if produced else None,
        error=None if produced else {
            "code": "internal_capability_tool_dag_failed",
            "message": "W02 私有 Tool DAG 未产生合同承诺的信息槽位。",
            "component": task.assigned_agent,
            "retryable": True,
        },
        focus_refs=task.focus_refs,
        summary=(
            "已通过 W02 私有 Tool DAG 读取内部权威事实。"
            if produced else "内部权威事实读取失败。"
        ),
        findings=[{"kind": "capability_slots", "slots": produced}],
        confidence=1.0 if success else 0.6 if produced else 0.0,
        warnings=warnings,
        metadata={
            "boundary_id": task.boundary_id,
            "tool_dag_task_count": len(getattr(getattr(dag_result, "plan", None), "tasks", []) or []),
            "produced_information_slots": produced,
        },
    )
    result.completion = runtime_completion_report(
        task,
        result_status=result.status,
        output_type=result.output_type,
        data=result.data,
        error=result.error,
    )
    return result


__all__ = ["run_internal_system"]
