"""Validate MainAgent-selected Worker assignments.

This module never chooses a Worker. It only verifies that the selected Worker
exists, is available, supports the requested boundary, respects the request
side-effect limit, and can legally receive the task contract.
"""

from __future__ import annotations

from typing import Any

from agent.collaboration.worker_contracts import WorkerContractViolation

from .models import CapabilityTask, ResolvedCapabilityTask
from .slot_binder import SlotBindingResult
from .semantic_slots import slot_matches_patterns

_EFFECT_ORDER = {"read": 0, "proposal": 1, "write": 2}


class WorkerAssignmentValidator:
    def __init__(self, capability_registry: Any, worker_directory: Any) -> None:
        self.capability_registry = capability_registry
        self.worker_directory = worker_directory

    def validate(
        self,
        tasks: list[CapabilityTask],
        *,
        bindings: SlotBindingResult,
        request_mode: str,
        worker_runtime_state: dict[str, dict[str, Any]] | None = None,
    ) -> list[ResolvedCapabilityTask]:
        runtime_state = dict(worker_runtime_state or {})
        request_limit = "proposal" if str(request_mode or "analysis").lower() == "proposal" else "read"
        resolved: list[ResolvedCapabilityTask] = []

        for task in tasks:
            if not task.worker_id:
                raise WorkerContractViolation(
                    "main_agent_worker_id_required",
                    f"$.tasks[{task.task_id}].worker_id",
                )
            try:
                card = self.worker_directory.get(task.worker_id)
            except KeyError as exc:
                raise WorkerContractViolation(
                    "unknown_main_agent_selected_worker",
                    f"$.tasks[{task.task_id}].worker_id",
                    task.worker_id,
                ) from exc

            state = dict(runtime_state.get(card.worker_id) or {})
            if card.availability != "available" or state.get("available") is False:
                raise WorkerContractViolation(
                    "selected_worker_unavailable",
                    f"$.tasks[{task.task_id}].worker_id",
                    card.worker_id,
                )
            if task.boundary_id not in set(card.supported_boundary_ids):
                raise WorkerContractViolation(
                    "selected_worker_does_not_support_boundary",
                    f"$.tasks[{task.task_id}]",
                    f"worker={card.worker_id},boundary={task.boundary_id}",
                )

            boundary = self.capability_registry.get_boundary(task.boundary_id)
            if _EFFECT_ORDER.get(task.effect_limit, 99) > _EFFECT_ORDER.get(card.max_effect_level, 99):
                raise WorkerContractViolation(
                    "selected_worker_effect_limit_insufficient",
                    f"$.tasks[{task.task_id}].effect_limit",
                    card.worker_id,
                )
            if _EFFECT_ORDER.get(task.effect_limit, 99) > _EFFECT_ORDER[request_limit]:
                raise WorkerContractViolation(
                    "selected_worker_effect_exceeds_request_mode",
                    f"$.tasks[{task.task_id}].effect_limit",
                    request_limit,
                )

            task_inputs = set(task.input_slots())
            task_outputs = set(task.output_slots())
            unsupported_inputs = sorted(
                slot for slot in task_inputs
                if not slot_matches_patterns(slot, boundary.accepted_input_patterns)
            )
            unsupported_outputs = sorted(
                slot for slot in task_outputs
                if not slot_matches_patterns(slot, boundary.produced_output_patterns)
            )
            if unsupported_inputs or unsupported_outputs:
                raise WorkerContractViolation(
                    "selected_worker_contract_outside_boundary",
                    f"$.tasks[{task.task_id}]",
                    f"inputs={unsupported_inputs},outputs={unsupported_outputs}",
                )

            resolved.append(
                ResolvedCapabilityTask(
                    task=task,
                    assigned_worker_id=card.worker_id,
                    assigned_agent_id=card.agent_id,
                    allowed_tool_ids=list(card.private_tool_ids),
                    execution_mode=card.execution_mode,
                    input_bindings=list(bindings.bindings_by_task.get(task.task_id, [])),
                    dependency_task_ids=list(bindings.dependency_ids_by_task.get(task.task_id, [])),
                    resolution_reason="main_agent_selected_worker;runtime_assignment_validated",
                    score=1.0,
                )
            )
        return resolved


__all__ = ["WorkerAssignmentValidator"]
