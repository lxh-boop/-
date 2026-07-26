"""Deterministic validation for Worker-private tool plans."""

from __future__ import annotations

from agent.dag_validation import DagNode, DagValidationError, DagValidator
from agent.tool_runtime import OP_PROPOSAL, OP_READ, OP_SYSTEM
from agent.worker_tools.registry import WorkerToolDirectory

from .contracts import WorkerExecutionPlan


class WorkerPlanValidationError(RuntimeError):
    pass


class WorkerPlanValidator:
    """Validate tool authorization, output contracts, and the shared DAG."""

    def __init__(self, directory: WorkerToolDirectory) -> None:
        self.directory = directory
        self.dag_validator = DagValidator(max_nodes=8)

    def parse_and_validate(
        self,
        payload: dict,
        *,
        capability_id: str,
    ) -> WorkerExecutionPlan:
        rows = payload.get("steps")
        if not isinstance(rows, list) or not rows:
            raise WorkerPlanValidationError("worker_plan_missing_steps")
        plan = WorkerExecutionPlan(
            capability_id=capability_id,
            steps=rows,
        )
        if not plan.steps:
            raise WorkerPlanValidationError("worker_plan_missing_steps")
        if len(plan.steps) > self.directory.max_steps(capability_id):
            raise WorkerPlanValidationError(
                f"worker_plan_too_many_steps:{capability_id}"
            )

        definitions = {}
        for step in plan.steps:
            if not step.step_id or not step.tool_name or not step.objective:
                raise WorkerPlanValidationError("worker_plan_invalid_step")
            definition = self.directory.get_allowed(
                capability_id,
                step.tool_name,
            )
            if definition is None:
                raise WorkerPlanValidationError(
                    f"worker_tool_not_allowed:{step.tool_name}"
                )
            if definition.operation_type not in {
                OP_READ,
                OP_SYSTEM,
                OP_PROPOSAL,
            }:
                raise WorkerPlanValidationError(
                    f"worker_write_tool_forbidden:{step.tool_name}"
                )
            if (
                step.proposed_arguments
                and definition.operation_type != OP_PROPOSAL
            ):
                raise WorkerPlanValidationError(
                    f"worker_arguments_only_allowed_for_proposal:{step.step_id}"
                )
            blocked_argument_keys = {
                "account_id",
                "approval_granted",
                "confirmation_token",
                "confirmation_token_hash",
                "user_id",
            }.intersection(step.proposed_arguments)
            if blocked_argument_keys:
                raise WorkerPlanValidationError(
                    f"worker_proposal_argument_forbidden:{step.step_id}:"
                    + ",".join(sorted(blocked_argument_keys))
                )
            unsupported = set(step.required_outputs).difference(
                definition.produced_outputs
            )
            if unsupported:
                raise WorkerPlanValidationError(
                    f"worker_step_output_not_produced:{step.step_id}:"
                    + ",".join(sorted(unsupported))
                )
            definitions[step.step_id] = definition

        try:
            self.dag_validator.validate(
                [
                    DagNode.from_values(
                        step.step_id,
                        step.dependency_step_ids,
                    )
                    for step in plan.steps
                ]
            )
        except DagValidationError as exc:
            raise WorkerPlanValidationError(str(exc)) from exc

        for step in plan.steps:
            available: set[str] = set()
            for dependency_id in step.dependency_step_ids:
                available.update(
                    definitions[dependency_id].produced_outputs
                )
            missing = set(
                definitions[step.step_id].required_dependency_outputs
            ).difference(available)
            if missing:
                raise WorkerPlanValidationError(
                    f"worker_tool_dependency_output_missing:{step.step_id}:"
                    + ",".join(sorted(missing))
                )

        required_outputs = set(
            self.directory.required_outputs(capability_id)
        )
        produced = {
            output
            for definition in definitions.values()
            for output in definition.produced_outputs
        }
        missing_plan_outputs = required_outputs.difference(produced)
        if missing_plan_outputs:
            raise WorkerPlanValidationError(
                "worker_plan_required_output_missing:"
                + ",".join(sorted(missing_plan_outputs))
            )
        return plan


__all__ = [
    "WorkerPlanValidationError",
    "WorkerPlanValidator",
]
