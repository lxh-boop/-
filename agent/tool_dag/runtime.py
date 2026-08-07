"""Shared Worker-private Tool DAG runtime with bounded local replanning."""

from __future__ import annotations

from typing import Any

from agent.console_trace import flow_event
from agent.tool_runtime import UnifiedToolResult

from .contracts import ToolDagExecutionResult, ToolNodeExecutionRecord
from .executor import ToolDagExecutor
from .planner import WorkerToolDagPlanner


class WorkerToolDagRuntime:
    def __init__(
        self,
        *,
        planner: WorkerToolDagPlanner,
        executor: ToolDagExecutor,
    ) -> None:
        self.planner = planner
        self.executor = executor

    def run(
        self,
        *,
        worker_task_id: str,
        worker_role: str,
        boundary_id: str,
        worker_objective: str,
        worker_prompt: str,
        available_context: dict[str, Any],
        required_output_keys: list[str],
        completion_criteria: list[str],
        allowed_tool_names: list[str],
        execution_context: dict[str, Any],
        read_only: bool = True,
        max_replans: int = 1,
    ) -> ToolDagExecutionResult:
        run_id = str(execution_context.get("run_id") or "")
        plan = self.planner.plan(
            worker_task_id=worker_task_id,
            worker_role=worker_role,
            worker_objective=worker_objective,
            boundary_id=boundary_id,
            worker_prompt=worker_prompt,
            available_context=available_context,
            required_output_keys=required_output_keys,
            completion_criteria=completion_criteria,
            allowed_tool_names=allowed_tool_names,
            run_id=run_id,
            read_only=read_only,
        )
        flow_event(
            "TOOL_DAG_ACCEPTED",
            {
                "worker_role": worker_role,
                "tool_task_count": len(plan.tasks),
                "final_output_task_ids": plan.final_output_task_ids,
                "single_node": len(plan.tasks) == 1,
                "validator_action": "accept_only_no_mutation",
            },
            run_id=run_id,
            task_id=worker_task_id,
        )
        current = self.executor.execute(
            plan,
            available_context=available_context,
            execution_context=execution_context,
        )
        all_records: list[ToolNodeExecutionRecord] = list(current.node_records)
        replan_audit: list[dict[str, Any]] = []
        replan_count = 0

        while not current.success and replan_count < max(0, int(max_replans)):
            records_by_id = {record.tool_task_id: record for record in all_records}
            reusable: dict[str, UnifiedToolResult] = {
                task_id: result
                for task_id, result in current.results.items()
                if task_id in records_by_id
                and records_by_id[task_id].should_freeze
                and records_by_id[task_id].reusable
            }
            if not all_records:
                break
            replanned = self.planner.replan(
                previous_plan=current.plan,
                node_records=[record.to_dict() for record in all_records],
                reusable_results=reusable,
                available_context=available_context,
                worker_prompt=worker_prompt,
                allowed_tool_names=allowed_tool_names,
                run_id=run_id,
                read_only=read_only,
            )
            new_ids = {
                task.tool_task_id
                for task in replanned.tasks
                if task.tool_task_id not in reusable
            }
            if not new_ids:
                break
            next_result = self.executor.execute(
                replanned,
                available_context=available_context,
                execution_context=execution_context,
                existing_results=reusable,
                only_task_ids=new_ids,
            )
            replan_count += 1
            replan_audit.append(
                {
                    "round": replan_count,
                    "frozen_reusable_tool_task_ids": sorted(reusable),
                    "new_tool_task_ids": sorted(new_ids),
                    "success": bool(next_result.success),
                    "node_records": [item.to_dict() for item in next_result.node_records],
                }
            )
            all_records.extend(next_result.node_records)
            current = ToolDagExecutionResult(
                plan=next_result.plan,
                results=next_result.results,
                node_records=list(all_records),
                execution_batches=[*current.execution_batches, *next_result.execution_batches],
                final_output_task_ids=next_result.final_output_task_ids,
                final_results=next_result.final_results,
                success=next_result.success,
                replan_count=replan_count,
                replan_audit=list(replan_audit),
            )

        flow_event(
            "TOOL_DAG_EXECUTION_COMPLETED",
            {
                "worker_role": worker_role,
                "success": bool(current.success),
                "tool_task_count": len(current.plan.tasks),
                "replan_count": int(current.replan_count),
                "execution_batches": current.execution_batches,
                "node_records": [record.to_dict() for record in current.node_records],
            },
            run_id=run_id,
            task_id=worker_task_id,
            level="INFO" if current.success else "WARNING",
        )
        return current


__all__ = ["WorkerToolDagRuntime"]
