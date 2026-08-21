"""Validate MainAgent-selected Worker assignments.

This module never chooses a Worker. It validates public capability scope and
mutation permission, then attaches execution-order dependencies produced by the
runtime dependency compiler. Business-data bindings do not exist here.
"""
from __future__ import annotations

from typing import Any

from agent.collaboration.worker_contracts import WorkerContractViolation

from .data_names import data_name_matches_patterns
from .models import CapabilityTask, ResolvedCapabilityTask


class WorkerAssignmentValidator:
    def __init__(self, capability_registry: Any, worker_directory: Any) -> None:
        self.capability_registry = capability_registry
        self.worker_directory = worker_directory

    def validate(
        self,
        tasks: list[CapabilityTask],
        *,
        dependencies: dict[str, list[str]],
        worker_runtime_state: dict[str, dict[str, Any]] | None = None,
    ) -> list[ResolvedCapabilityTask]:
        runtime_state = dict(worker_runtime_state or {})
        resolved: list[ResolvedCapabilityTask] = []
        known_task_ids = {task.task_id for task in tasks}

        for task in tasks:
            if not task.worker_id:
                raise WorkerContractViolation("main_agent_worker_id_required", f"$.tasks[{task.task_id}].worker_id")
            try:
                card = self.worker_directory.get(task.worker_id)
            except KeyError as exc:
                raise WorkerContractViolation(
                    "unknown_main_agent_selected_worker", f"$.tasks[{task.task_id}].worker_id", task.worker_id
                ) from exc

            state = dict(runtime_state.get(card.worker_id) or {})
            if card.availability != "available" or state.get("available") is False:
                raise WorkerContractViolation("selected_worker_unavailable", f"$.tasks[{task.task_id}].worker_id", card.worker_id)

            compatible_scope_ids = {str(card.role), *[str(item) for item in card.supported_boundary_ids]}
            if task.boundary_id not in compatible_scope_ids:
                raise WorkerContractViolation(
                    "selected_worker_does_not_support_boundary", f"$.tasks[{task.task_id}]",
                    f"worker={card.worker_id},scope={task.boundary_id},expected={card.role}",
                )

            worker_scope = self.capability_registry.aggregate_scope(card.supported_boundary_ids)
            unsupported_inputs = sorted(
                name for name in task.input_data_names()
                if not data_name_matches_patterns(name, worker_scope["accepted_data_patterns"])
            )
            unsupported_outputs = sorted(
                name for name in task.output_data_names()
                if not data_name_matches_patterns(name, worker_scope["produced_data_patterns"])
            )
            if unsupported_inputs or unsupported_outputs:
                raise WorkerContractViolation(
                    "selected_worker_contract_outside_scope", f"$.tasks[{task.task_id}]",
                    f"inputs={unsupported_inputs},outputs={unsupported_outputs}",
                )

            contract_mutation = task.mutation_allowed()
            if contract_mutation and not bool(card.can_mutate):
                raise WorkerContractViolation(
                    "selected_worker_mutation_permission_denied", f"$.tasks[{task.task_id}]", card.worker_id
                )
            if contract_mutation and not bool(worker_scope.get("mutation_allowed", False)):
                raise WorkerContractViolation(
                    "selected_boundary_mutation_permission_denied", f"$.tasks[{task.task_id}]", task.boundary_id
                )

            dependency_ids = list(dict.fromkeys(str(x) for x in dependencies.get(task.task_id, []) if str(x)))
            unknown_dependencies = sorted(set(dependency_ids) - known_task_ids)
            if unknown_dependencies:
                raise WorkerContractViolation(
                    "unknown_task_dependency", f"$.tasks[{task.task_id}].dependency_task_ids",
                    ",".join(unknown_dependencies),
                )
            resolved.append(ResolvedCapabilityTask(
                task=task,
                assigned_worker_id=card.worker_id,
                assigned_agent_id=card.agent_id,
                allowed_tool_ids=list(card.private_tool_ids),
                execution_mode=card.execution_mode,
                dependency_task_ids=dependency_ids,
                resolution_reason="main_agent_selected_worker;runtime_assignment_validated",
                score=1.0,
            ))
        return resolved


__all__ = ["WorkerAssignmentValidator"]
