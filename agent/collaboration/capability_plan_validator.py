"""Deterministic validation for Main-Agent capability task plans."""

from __future__ import annotations

import re
from typing import Any

from agent.dag_validation import DagNode, DagValidationError, DagValidator

from .agent_directory import AgentDirectory, ResolvedWorkerCapability
from .capability_contracts import CapabilityTaskPlan


class CoordinatorPlanningError(RuntimeError):
    pass


_FORBIDDEN_LLM_PLAN_FIELDS = frozenset(
    {
        "assigned_agent",
        "agent_id",
        "agent_name",
        "worker_id",
        "worker_name",
        "task_type",
    }
)


def _contains_private_implementation(value: str) -> bool:
    text = str(value or "").lower()
    blocked = (
        "tool",
        "schema",
        "cypher",
        "sql",
        "api endpoint",
        "database table",
        "tool_registry",
        "stock_code",
        "stock_codes",
        "ts_code",
        "security_scope",
        "route_agent_query",
        "intent router",
    )
    return any(item in text for item in blocked) or bool(
        re.search(r"\b[a-z]+\.[a-z_]+\b", text)
    )


class CapabilityPlanValidator:
    """Validate capability IDs, dependencies, outputs, and final coverage."""

    def __init__(self, directory: AgentDirectory) -> None:
        self.directory = directory
        self.dag_validator = DagValidator(max_nodes=8)

    def parse_and_validate(
        self,
        payload: dict[str, Any],
        *,
        request_mode: str,
    ) -> list[CapabilityTaskPlan]:
        rows = payload.get("tasks")
        if not isinstance(rows, list) or not rows:
            raise CoordinatorPlanningError("coordinator_plan_missing_tasks")
        if len(rows) > 8:
            raise CoordinatorPlanningError("coordinator_plan_too_many_tasks")

        plans: list[CapabilityTaskPlan] = []
        known_ids: set[str] = set()
        bindings: dict[str, ResolvedWorkerCapability] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise CoordinatorPlanningError("coordinator_plan_task_not_object")
            forbidden = _FORBIDDEN_LLM_PLAN_FIELDS.intersection(row)
            if forbidden:
                raise CoordinatorPlanningError(
                    "coordinator_plan_exposes_worker_identity:"
                    + ",".join(sorted(forbidden))
                )

            task_id = str(row.get("task_id") or "").strip()
            if not task_id or task_id in known_ids:
                raise CoordinatorPlanningError("coordinator_plan_invalid_task_id")
            known_ids.add(task_id)

            capability_id = str(row.get("capability_id") or "").strip()
            try:
                binding = self.directory.resolve(
                    capability_id,
                    request_mode=request_mode,
                )
            except (KeyError, ValueError) as exc:
                detail = str(exc.args[0]) if exc.args else str(exc)
                raise CoordinatorPlanningError(detail) from exc
            bindings[task_id] = binding

            objective = str(row.get("objective") or "").strip()
            if not objective or _contains_private_implementation(objective):
                raise CoordinatorPlanningError(
                    f"invalid_capability_objective:{task_id}"
                )

            dependencies = row.get("dependency_task_ids") or []
            required_outputs = row.get("required_outputs") or []
            constraints = row.get("constraints") or []
            if not isinstance(dependencies, list):
                raise CoordinatorPlanningError(f"invalid_dependencies:{task_id}")
            if not isinstance(required_outputs, list):
                raise CoordinatorPlanningError(
                    f"invalid_required_outputs:{task_id}"
                )
            if not isinstance(constraints, list):
                raise CoordinatorPlanningError(f"invalid_constraints:{task_id}")

            plan = CapabilityTaskPlan(
                task_id=task_id,
                capability_id=capability_id,
                objective=objective,
                dependency_task_ids=[str(item) for item in dependencies],
                required_outputs=[str(item) for item in required_outputs],
                constraints=[str(item) for item in constraints],
                priority=row.get("priority", 1),
            )
            unsupported_outputs = set(plan.required_outputs).difference(
                binding.produced_output_types
            )
            if unsupported_outputs:
                raise CoordinatorPlanningError(
                    f"capability_required_output_not_produced:{task_id}:"
                    + ",".join(sorted(unsupported_outputs))
                )
            plans.append(plan)

        self._validate_dag(plans, bindings)
        self._validate_capability_dependencies(plans, bindings)
        self._validate_request_outputs(
            plans,
            bindings,
            request_mode=request_mode,
        )
        return plans

    def _validate_dag(
        self,
        plans: list[CapabilityTaskPlan],
        bindings: dict[str, ResolvedWorkerCapability],
    ) -> None:
        has_finalizer = any(
            bindings[plan.task_id].can_finalize for plan in plans
        )
        try:
            self.dag_validator.validate(
                [
                    DagNode.from_values(
                        plan.task_id,
                        plan.dependency_task_ids,
                        terminal=bindings[plan.task_id].can_finalize,
                    )
                    for plan in plans
                ],
                require_terminal_coverage=has_finalizer,
            )
        except DagValidationError as exc:
            if exc.code in {"dag_unknown_dependency", "dag_self_dependency"}:
                raise CoordinatorPlanningError(
                    "invalid_dependency_ref:" + ":".join(exc.node_ids)
                ) from exc
            if exc.code == "dag_dependency_cycle":
                raise CoordinatorPlanningError(
                    "capability_task_dependency_cycle"
                ) from exc
            if exc.code == "dag_terminal_has_dependents":
                raise CoordinatorPlanningError(
                    "finalizer_not_terminal:" + ",".join(exc.node_ids)
                ) from exc
            if exc.code == "dag_terminal_missing_branches":
                raise CoordinatorPlanningError(
                    "finalizer_missing_task_branches:"
                    + ",".join(exc.node_ids)
                ) from exc
            raise CoordinatorPlanningError(str(exc)) from exc

    @staticmethod
    def _validate_capability_dependencies(
        plans: list[CapabilityTaskPlan],
        bindings: dict[str, ResolvedWorkerCapability],
    ) -> None:
        for plan in plans:
            binding = bindings[plan.task_id]
            available_outputs: set[str] = set()
            for dependency_id in plan.dependency_task_ids:
                available_outputs.update(
                    bindings[dependency_id].produced_output_types
                )
            missing = set(
                binding.required_dependency_output_types
            ).difference(available_outputs)
            if missing:
                raise CoordinatorPlanningError(
                    f"capability_dependency_output_missing:{plan.task_id}:"
                    + ",".join(sorted(missing))
                )

            accepted = set(binding.accepted_dependency_output_types)
            if not accepted:
                continue
            for dependency_id in plan.dependency_task_ids:
                dependency_outputs = set(
                    bindings[dependency_id].produced_output_types
                )
                if dependency_outputs.isdisjoint(accepted):
                    raise CoordinatorPlanningError(
                        "capability_dependency_output_incompatible:"
                        f"{plan.task_id}:{dependency_id}"
                    )

    def _validate_request_outputs(
        self,
        plans: list[CapabilityTaskPlan],
        bindings: dict[str, ResolvedWorkerCapability],
        *,
        request_mode: str,
    ) -> None:
        produced = {
            output_type
            for plan in plans
            for output_type in bindings[plan.task_id].produced_output_types
        }
        missing = set(
            self.directory.required_outputs_for_mode(request_mode)
        ).difference(produced)
        if missing:
            raise CoordinatorPlanningError(
                "request_mode_output_missing:" + ",".join(sorted(missing))
            )

__all__ = [
    "CapabilityPlanValidator",
    "CoordinatorPlanningError",
]
