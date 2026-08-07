"""Execute W03 graph-relation retrieval through its private Tool DAG.

The Worker sees only SlotBinder-materialized inputs. Tool compatibility is
resolved from required input slots; entity count is never used as a task type.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tool_dag import WorkerToolDagRuntime

from ..completion import runtime_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import contract_acceptance_rules, contract_output_slots, execution_safe_value


def _publish_slots(task: GraphAgentTask, dag_result: Any) -> tuple[dict[str, Any], list[str], list[str]]:
    wanted = set(contract_output_slots(task))
    slots: dict[str, Any] = {}
    warnings: list[str] = []
    for tool_result in list(getattr(dag_result, "final_results", []) or []):
        data = dict(getattr(tool_result, "data", {}) or {})
        tool_slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        for slot_id, value in tool_slots.items():
            if slot_id in wanted:
                slots[str(slot_id)] = execution_safe_value(value)
        warnings.extend(str(item) for item in getattr(tool_result, "warnings", []) or [] if str(item))
        warnings.extend(str(item) for item in getattr(tool_result, "errors", []) or [] if str(item))
    produced = [slot for slot in contract_output_slots(task) if slot in slots]
    missing = [slot for slot in contract_output_slots(task) if slot not in slots]
    return slots, produced, list(dict.fromkeys([*warnings, *missing]))


def run_graph_impact(
    tool_dag_runtime: WorkerToolDagRuntime,
    task: GraphAgentTask,
    *,
    resolved_inputs: dict[str, Any] | None,
    worker_prompt: str,
    allowed_tool_names: list[str],
    output_dir: str | Path,
    db_path: str | Path | None,
) -> GraphWorkerResult:
    available_context = {
        str(key): execution_safe_value(value)
        for key, value in dict(resolved_inputs or {}).items()
        if value is not None
    }
    required_outputs = contract_output_slots(task)
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
    success = bool(dag_result.success and len(produced) == len(required_outputs))
    status = ResultStatus.COMPLETED if success else ResultStatus.PARTIAL if produced else ResultStatus.FAILED
    data = {
        "slots": slots,
        "produced_information_slots": produced,
        "missing_information_slots": [slot for slot in required_outputs if slot not in produced],
        "business_empty": bool(produced and all(
            isinstance(value, dict) and value.get("business_empty") is True
            for value in slots.values()
        )),
    }
    result = GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=status,
        output_type="CapabilityResult",
        payload_schema="capability_result.v1",
        payload=data if produced else None,
        data=data if produced else None,
        error=None if produced else {
            "code": "graph_relation_tool_dag_failed",
            "message": "W03 private Tool DAG did not publish the promised relation slots.",
            "component": task.assigned_agent,
            "retryable": True,
        },
        focus_refs=task.focus_refs,
        summary=(
            "已通过W03私有Tool DAG读取图关系信息。"
            if produced else "图关系读取未产生合同承诺的Slot。"
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


__all__ = ["run_graph_impact"]
