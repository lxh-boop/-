"""Execute W03 graph-relation retrieval through its private Tool DAG.

The Worker receives authoritative entity context from Runtime. Private Tool compatibility remains internal to W03; entity count is never used as a task type.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tool_dag import WorkerToolDagRuntime

from ..completion import runtime_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from agent.capabilities.data_names import LEGACY_OUTPUT_NAME_MAP
from .common import contract_acceptance_rules, contract_output_data_names, execution_safe_value


def _publish_business_data(task: GraphAgentTask, dag_result: Any) -> tuple[dict[str, Any], list[str], list[str]]:
    wanted = set(contract_output_data_names(task))
    business_data: dict[str, Any] = {}
    warnings: list[str] = []
    for tool_result in list(getattr(dag_result, "final_results", []) or []):
        data = dict(getattr(tool_result, "data", {}) or {})
        tool_data = data.get("business_data") if isinstance(data.get("business_data"), dict) else data.get("slots") if isinstance(data.get("slots"), dict) else {}
        for raw_name, value in tool_data.items():
            name = LEGACY_OUTPUT_NAME_MAP.get(str(raw_name), str(raw_name))
            if name in wanted:
                business_data[name] = execution_safe_value(value)
        warnings.extend(str(item) for item in getattr(tool_result, "warnings", []) or [] if str(item))
        warnings.extend(str(item) for item in getattr(tool_result, "errors", []) or [] if str(item))
    produced = [name for name in contract_output_data_names(task) if name in business_data]
    missing = [name for name in contract_output_data_names(task) if name not in business_data]
    return business_data, produced, list(dict.fromkeys([*warnings, *missing]))


def run_graph_impact(
    tool_dag_runtime: WorkerToolDagRuntime,
    task: GraphAgentTask,
    *,
    working_memory_context: dict[str, Any] | None = None,
    worker_prompt: str,
    allowed_tool_names: list[str],
    output_dir: str | Path,
    db_path: str | Path | None,
) -> GraphWorkerResult:
    available_context = {
        str(key): execution_safe_value(value)
        for key, value in dict(working_memory_context or {}).items()
        if value is not None
    }
    required_outputs = contract_output_data_names(task)
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
    business_data, produced, warnings = _publish_business_data(task, dag_result)
    success = bool(dag_result.success and len(produced) == len(required_outputs))
    status = ResultStatus.COMPLETED if success else ResultStatus.PARTIAL if produced else ResultStatus.FAILED
    data = {
        "business_data": business_data,
        "produced_data_names": produced,
        "missing_data_names": [name for name in required_outputs if name not in produced],
        "business_empty": bool(produced and all(
            isinstance(value, dict) and value.get("business_empty") is True
            for value in business_data.values()
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
            "message": "W03 private Tool DAG did not publish the promised relation data.",
            "component": task.assigned_agent,
            "retryable": True,
        },
        focus_refs=task.focus_refs,
        summary=(
            "已通过W03私有Tool DAG读取图关系信息。"
            if produced else "图关系读取未产生合同承诺的数据。"
        ),
        findings=[{"kind": "capability_business_data", "data_names": produced}],
        confidence=1.0 if success else 0.6 if produced else 0.0,
        warnings=warnings,
        metadata={
            "boundary_id": task.boundary_id,
            "tool_dag_task_count": len(getattr(getattr(dag_result, "plan", None), "tasks", []) or []),
            "produced_data_names": produced,
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
