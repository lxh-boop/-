from __future__ import annotations

from typing import Any

from agent.collaboration.worker_contracts import WorkerContractViolation

from .models import CapabilityTask


_EFFECT_ORDER = {"read": 0, "proposal": 1, "write": 2}
_RUNTIME_OWNED_PARAMETER_NAMES = {
    "user_id", "session_id", "conversation_id", "run_id", "language",
    "reply_language", "as_of_time", "focus_ref_ids", "context_ref_ids",
    "graph_ref_ids", "approval_token", "confirmation_token", "worker_id",
    "agent_id", "tool_id", "tool_name", "model", "timeout", "retry",
}


class CapabilityPlanValidator:
    """Rule-only validator for MainAgent capability/contract plans."""

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    def validate(
        self,
        payload: dict[str, Any],
        *,
        request_mode: str,
        initial_information_slots: set[str],
    ) -> list[CapabilityTask]:
        if not isinstance(payload, dict):
            raise WorkerContractViolation("capability_plan_not_object", "$")
        goal = payload.get("goal_contract")
        if not isinstance(goal, dict):
            raise WorkerContractViolation("capability_goal_contract_missing", "$.goal_contract")
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise WorkerContractViolation("capability_plan_empty", "$.tasks")

        mode = str(request_mode or "analysis").lower()
        request_max = "proposal" if mode == "proposal" else "read"
        goal_effect = str(goal.get("effect_limit") or "read").lower()
        if _EFFECT_ORDER.get(goal_effect, 99) > _EFFECT_ORDER[request_max]:
            raise WorkerContractViolation(
                "capability_goal_effect_exceeds_request_mode",
                "$.goal_contract.effect_limit",
                f"mode={mode},effect={goal_effect}",
            )

        tasks: list[CapabilityTask] = []
        task_ids: set[str] = set()
        produced_slots: set[str] = set(initial_information_slots)
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
                boundary = self.registry.get_boundary(task.boundary_id)
            except KeyError as exc:
                raise WorkerContractViolation(
                    "unknown_capability_boundary",
                    f"$.tasks[{index-1}].boundary_id",
                    task.boundary_id,
                ) from exc

            if _EFFECT_ORDER.get(task.effect_limit, 99) > _EFFECT_ORDER.get(goal_effect, 99):
                raise WorkerContractViolation(
                    "capability_task_effect_exceeds_goal",
                    f"$.tasks[{index-1}].effect_limit",
                    task.effect_limit,
                )
            if _EFFECT_ORDER.get(task.effect_limit, 99) > _EFFECT_ORDER.get(boundary.max_effect_level, 99):
                raise WorkerContractViolation(
                    "capability_task_effect_exceeds_boundary",
                    f"$.tasks[{index-1}].effect_limit",
                    task.boundary_id,
                )

            forbidden_params = sorted(
                key
                for key in task.business_parameters
                if str(key).lower() in _RUNTIME_OWNED_PARAMETER_NAMES
                or str(key).lower().endswith("_ref_ids")
            )
            if forbidden_params:
                raise WorkerContractViolation(
                    "runtime_owned_parameter_in_capability_plan",
                    f"$.tasks[{index-1}].business_parameters",
                    ",".join(forbidden_params),
                )

            contract_ids: set[str] = set()
            for cindex, contract in enumerate(task.contracts, start=1):
                if not contract.contract_id:
                    raise WorkerContractViolation(
                        "capability_contract_id_missing",
                        f"$.tasks[{index-1}].contracts[{cindex-1}]",
                    )
                if contract.contract_id in contract_ids:
                    raise WorkerContractViolation(
                        "duplicate_capability_contract_id",
                        f"$.tasks[{index-1}].contracts",
                        contract.contract_id,
                    )
                contract_ids.add(contract.contract_id)
                if not contract.promised_outputs:
                    raise WorkerContractViolation(
                        "capability_contract_outputs_empty",
                        f"$.tasks[{index-1}].contracts[{cindex-1}].promised_outputs",
                    )
                if _EFFECT_ORDER.get(contract.effect_limit, 99) > _EFFECT_ORDER.get(task.effect_limit, 99):
                    raise WorkerContractViolation(
                        "capability_contract_effect_exceeds_task",
                        f"$.tasks[{index-1}].contracts[{cindex-1}].effect_limit",
                    )

                input_slots = set(contract.input_slots())
                output_slots = set(contract.output_slots())
                unsupported_inputs = sorted(input_slots - set(boundary.accepted_input_slots))
                unsupported_outputs = sorted(output_slots - set(boundary.produced_output_slots))
                if unsupported_inputs:
                    raise WorkerContractViolation(
                        "capability_input_slot_outside_boundary",
                        f"$.tasks[{index-1}].contracts[{cindex-1}].required_inputs",
                        ",".join(unsupported_inputs),
                    )
                if unsupported_outputs:
                    raise WorkerContractViolation(
                        "capability_output_slot_outside_boundary",
                        f"$.tasks[{index-1}].contracts[{cindex-1}].promised_outputs",
                        ",".join(unsupported_outputs),
                    )
                overlap = sorted(output_slots.intersection(contract.forbidden_output_slots))
                if overlap:
                    raise WorkerContractViolation(
                        "capability_forbidden_output_requested",
                        f"$.tasks[{index-1}].contracts[{cindex-1}].forbidden_output_slots",
                        ",".join(overlap),
                    )
                unknown_rules = sorted(
                    rule
                    for rule in contract.acceptance_rule_ids
                    if rule not in boundary.allowed_acceptance_rule_ids
                    or not self.registry.acceptance_rule_exists(rule)
                )
                if unknown_rules:
                    raise WorkerContractViolation(
                        "capability_acceptance_rule_outside_boundary",
                        f"$.tasks[{index-1}].contracts[{cindex-1}].acceptance_rule_ids",
                        ",".join(unknown_rules),
                    )
                produced_slots.update(output_slots)
            tasks.append(task)

        desired = {str(item) for item in goal.get("desired_outputs") or [] if str(item)}
        required = {
            str(item) for item in goal.get("required_information_slots") or [] if str(item)
        }
        missing = sorted((desired | required) - produced_slots)
        if missing:
            raise WorkerContractViolation(
                "capability_goal_slots_uncovered",
                "$.goal_contract",
                ",".join(missing),
            )
        if "user_facing_report" in desired | required and not any(
            task.boundary_id == "result.composition" for task in tasks
        ):
            raise WorkerContractViolation("capability_plan_missing_result_composition", "$.tasks")
        return tasks
