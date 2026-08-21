from __future__ import annotations

from typing import Any

from agent.collaboration.worker_contracts import WorkerContractViolation

from .data_names import data_name_matches_patterns, validate_data_name
from .models import CapabilityTask

_RUNTIME_OWNED_PARAMETER_NAMES = {
    "user_id", "session_id", "conversation_id", "run_id", "language", "reply_language",
    "as_of_time", "focus_ref_ids", "context_ref_ids", "graph_ref_ids", "approval_token",
    "confirmation_token", "worker_id", "agent_id", "tool_id", "tool_name", "model",
    "timeout", "retry",
}


class CapabilityPlanValidator:
    """Rule-only validator for Worker-scope business-data contracts."""

    def __init__(self, registry: Any, worker_directory: Any) -> None:
        self.registry = registry
        self.worker_directory = worker_directory

    def validate(
        self,
        payload: dict[str, Any],
    ) -> list[CapabilityTask]:
        if not isinstance(payload, dict):
            raise WorkerContractViolation("capability_plan_not_object", "$")
        if not isinstance(payload.get("goal_contract"), dict):
            raise WorkerContractViolation("capability_goal_contract_missing", "$.goal_contract")
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise WorkerContractViolation("capability_plan_empty", "$.tasks")

        tasks: list[CapabilityTask] = []
        task_ids: set[str] = set()
        for index, raw in enumerate(raw_tasks, start=1):
            if not isinstance(raw, dict):
                raise WorkerContractViolation("capability_task_not_object", f"$.tasks[{index-1}]")
            task_id = str(raw.get("task_id") or f"T{index:02d}")
            task = CapabilityTask.from_dict({**raw, "task_id": task_id}, task_id=task_id)
            if not task.task_id or task.task_id in task_ids:
                raise WorkerContractViolation("duplicate_or_empty_capability_task_id", "$.tasks")
            task_ids.add(task.task_id)
            if not task.worker_id:
                raise WorkerContractViolation("main_agent_worker_id_required", f"$.tasks[{index-1}].worker_id")
            if not task.objective:
                raise WorkerContractViolation("capability_task_objective_missing", f"$.tasks[{index-1}].objective")
            if not task.contracts:
                raise WorkerContractViolation("capability_contract_list_empty", f"$.tasks[{index-1}].contracts")

            try:
                card = self.worker_directory.get(task.worker_id)
            except KeyError as exc:
                raise WorkerContractViolation("unknown_main_agent_selected_worker", f"$.tasks[{index-1}].worker_id", task.worker_id) from exc
            scope = self.registry.aggregate_scope(card.supported_boundary_ids)
            if task.boundary_id not in {str(card.role), *[str(x) for x in card.supported_boundary_ids]}:
                raise WorkerContractViolation("worker_scope_id_mismatch", f"$.tasks[{index-1}].boundary_id", task.boundary_id)

            for contract in task.contracts:
                for item in contract.required_data:
                    validate_data_name(item.name)
                for item in contract.promised_data:
                    validate_data_name(item.name)
                unsupported_inputs = sorted(
                    name for name in contract.input_data_names()
                    if not data_name_matches_patterns(name, scope.get("accepted_data_patterns") or [])
                )
                unsupported_outputs = sorted(
                    name for name in contract.output_data_names()
                    if not data_name_matches_patterns(name, scope.get("produced_data_patterns") or [])
                )
                if unsupported_inputs or unsupported_outputs:
                    raise WorkerContractViolation(
                        "capability_contract_outside_worker_scope", f"$.tasks[{index-1}]",
                        f"inputs={unsupported_inputs},outputs={unsupported_outputs}",
                    )
                allowed_rules = set(scope.get("allowed_acceptance_rule_ids") or [])
                invalid_rules = sorted(set(contract.acceptance_rule_ids) - allowed_rules)
                if invalid_rules:
                    raise WorkerContractViolation(
                        "capability_acceptance_rule_outside_scope", f"$.tasks[{index-1}]", ",".join(invalid_rules)
                    )
                if contract.mutation_allowed and not bool(card.can_mutate):
                    raise WorkerContractViolation("capability_mutation_not_allowed_for_worker", f"$.tasks[{index-1}]", card.worker_id)
                if contract.mutation_allowed and not bool(scope.get("mutation_allowed", False)):
                    raise WorkerContractViolation("capability_mutation_not_allowed_for_boundary", f"$.tasks[{index-1}]", task.boundary_id)
                for requirement in contract.required_parameters:
                    if requirement.parameter_id in _RUNTIME_OWNED_PARAMETER_NAMES:
                        raise WorkerContractViolation(
                            "runtime_parameter_cannot_be_business_parameter", f"$.tasks[{index-1}]", requirement.parameter_id
                        )
            tasks.append(task)
        return tasks


__all__ = ["CapabilityPlanValidator"]
