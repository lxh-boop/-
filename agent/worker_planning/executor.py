"""Execute a validated Worker-private tool DAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.collaboration.models import (
    ContextRequestCategory,
    GraphAgentTask,
    MissingContextItem,
)
from agent.dag_validation import DagNode, DagValidator
from agent.tool_runtime import AGENT_WORKER, ToolExecutor, UnifiedToolResult
from agent.worker_tools.registry import WorkerToolDirectory

from .contracts import WorkerExecutionPlan
from .errors import WorkerContextRequired
from .validator import WorkerPlanValidator


@dataclass
class WorkerPlanExecution:
    success: bool
    ordered_step_ids: list[str]
    step_results: dict[str, UnifiedToolResult] = field(default_factory=dict)
    missing_items: list[MissingContextItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def tool_call_count(self) -> int:
        return len(self.step_results)


class WorkerPlanExecutor:
    """Bind inputs deterministically and execute only capability-allowed tools."""

    def __init__(
        self,
        *,
        directory: WorkerToolDirectory,
        tool_executor: ToolExecutor,
    ) -> None:
        self.directory = directory
        self.tool_executor = tool_executor
        self.validator = WorkerPlanValidator(directory)

    def execute(
        self,
        plan: WorkerExecutionPlan,
        *,
        task: GraphAgentTask,
        user_request: str,
        dependency_results: dict[str, dict[str, Any]],
        output_dir: Any,
        db_path: Any,
        default_top_k: int,
        memory_values: dict[str, Any] | None = None,
        execution_context: dict[str, Any] | None = None,
    ) -> WorkerPlanExecution:
        validated = self.validator.parse_and_validate(
            plan.to_dict(),
            capability_id=task.capability_id,
        )
        ordered = DagValidator(max_nodes=8).validate(
            [
                DagNode.from_values(
                    step.step_id,
                    step.dependency_step_ids,
                )
                for step in validated.steps
            ]
        ).ordered_node_ids
        by_id = {step.step_id: step for step in validated.steps}
        results: dict[str, UnifiedToolResult] = {}
        warnings: list[str] = []
        for step_id in ordered:
            step = by_id[step_id]
            failed_dependencies = [
                dependency_id
                for dependency_id in step.dependency_step_ids
                if not results[dependency_id].success
            ]
            if failed_dependencies:
                warnings.append(
                    f"worker_step_skipped_failed_dependency:{step_id}:"
                    + ",".join(failed_dependencies)
                )
                continue
            definition = self.directory.get_allowed(
                task.capability_id,
                step.tool_name,
            )
            if definition is None:
                raise RuntimeError(f"worker_tool_not_allowed:{step.tool_name}")
            try:
                arguments = (
                    definition.argument_builder(
                        {
                            "task": task,
                            "user_request": user_request,
                            "dependency_results": dependency_results,
                            "step_results": results,
                            "memory_values": dict(memory_values or {}),
                            "default_top_k": default_top_k,
                            "output_dir": output_dir,
                            "db_path": db_path,
                            "execution_context": dict(
                                execution_context or {}
                            ),
                            "proposed_arguments": dict(
                                step.proposed_arguments
                            ),
                        }
                    )
                    if definition.argument_builder is not None
                    else {}
                )
                if step.proposed_arguments:
                    arguments.update(step.proposed_arguments)
                arguments.pop("confirmation_token", None)
                arguments.pop("confirmation_token_hash", None)
                arguments["user_id"] = task.user_id
            except WorkerContextRequired as exc:
                return WorkerPlanExecution(
                    success=False,
                    ordered_step_ids=list(ordered),
                    step_results=results,
                    missing_items=exc.items,
                    warnings=warnings,
                )
            missing_required = self._missing_required_inputs(
                definition.input_schema,
                arguments,
            )
            if missing_required:
                return WorkerPlanExecution(
                    success=False,
                    ordered_step_ids=list(ordered),
                    step_results=results,
                    missing_items=missing_required,
                    warnings=warnings,
                )
            result = self.tool_executor.execute(
                step.tool_name,
                arguments,
                context={
                    **dict(execution_context or {}),
                    "user_id": task.user_id,
                    "conversation_id": task.session_id,
                    "session_id": task.session_id,
                    "run_id": task.run_id,
                    "task_id": task.task_id,
                    "agent_role": task.assigned_agent,
                    "capability_id": task.capability_id,
                    "dependency_results": dependency_results,
                    "graph_refs": [
                        ref.to_dict()
                        for ref in task.focus_refs + task.context_refs
                    ],
                    "output_dir": output_dir,
                    "db_path": db_path,
                },
                agent_type=AGENT_WORKER,
                capability_id=task.capability_id,
                approval_granted=False,
            )
            results[step_id] = result
            if not result.success:
                warnings.extend(result.errors or [result.error_type])
        return WorkerPlanExecution(
            success=bool(results)
            and all(result.success for result in results.values())
            and len(results) == len(validated.steps),
            ordered_step_ids=list(ordered),
            step_results=results,
            warnings=warnings,
        )

    @staticmethod
    def _missing_required_inputs(
        input_schema: dict[str, Any],
        arguments: dict[str, Any],
    ) -> list[MissingContextItem]:
        properties = dict(input_schema.get("properties") or {})
        missing: list[MissingContextItem] = []
        for key in list(input_schema.get("required") or []):
            value = arguments.get(key)
            if key in arguments and value is not None and (
                not isinstance(value, str) or value.strip()
            ):
                continue
            schema = dict(properties.get(key) or {})
            lowered = str(key).lower()
            sensitive = any(
                marker in lowered
                for marker in ("api_key", "password", "secret", "token")
            )
            memory_backed = (
                lowered == "account_id"
                or lowered.endswith("_id")
                or lowered.endswith("_version")
            )
            missing.append(
                MissingContextItem(
                    key=str(key),
                    description=str(
                        schema.get("description")
                        or f"工具执行需要参数 {key}"
                    ),
                    expected_format=str(
                        schema.get("type") or "string"
                    ),
                    reason="required_worker_tool_input_missing",
                    searched_sources=[
                        "confirmed_session_memory",
                        "execution_context",
                        "worker_tool_plan",
                    ],
                    category=(
                        ContextRequestCategory.SYSTEM_CONFIG_REQUIRED
                        if sensitive
                        else ContextRequestCategory.MEMORY_LOOKUP_REQUIRED
                        if memory_backed
                        else ContextRequestCategory.USER_INPUT_REQUIRED
                    ),
                    value_schema=schema,
                    sensitivity="secret" if sensitive else "normal",
                    allow_memory_lookup=not sensitive,
                )
            )
        return missing


__all__ = [
    "WorkerContextRequired",
    "WorkerPlanExecution",
    "WorkerPlanExecutor",
]
