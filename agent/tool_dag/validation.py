"""Deterministic, accept-or-reject validation for Worker-private Tool DAGs."""

from __future__ import annotations

from typing import Any, Iterable

from agent.tool_runtime import OP_READ, ToolRegistry
from agent.worker_tools import WorkerToolDirectory

from .contracts import ToolDagContractViolation, ToolDagPlan, ToolDagTask


def _iter_input_refs(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "from_context" in value or "from_tool_task_id" in value:
            yield value
            return
        for item in value.values():
            yield from _iter_input_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_input_refs(item)


def _validate_input_binding_shape(value: Any, *, path: str) -> None:
    """Accept only the canonical context/tool-result reference structures."""

    items = value if isinstance(value, list) else [value]
    if not items:
        raise ToolDagContractViolation("tool_task_input_binding_empty", path)
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]" if isinstance(value, list) else path
        if not isinstance(item, dict):
            raise ToolDagContractViolation("tool_task_input_binding_must_be_object", item_path)
        has_context = "from_context" in item
        has_tool = "from_tool_task_id" in item
        if has_context == has_tool:
            raise ToolDagContractViolation("tool_input_ref_requires_one_source", item_path)
        if has_context:
            if set(item) != {"from_context"}:
                raise ToolDagContractViolation(
                    "tool_context_ref_has_unknown_fields", item_path, ",".join(sorted(set(item) - {"from_context"}))
                )
            if not str(item.get("from_context") or "").strip():
                raise ToolDagContractViolation("tool_context_ref_key_required", item_path)
        else:
            unknown = set(item) - {"from_tool_task_id", "data_key"}
            if unknown:
                raise ToolDagContractViolation(
                    "tool_result_ref_has_unknown_fields", item_path, ",".join(sorted(unknown))
                )
            if not str(item.get("from_tool_task_id") or "").strip():
                raise ToolDagContractViolation("tool_result_ref_task_id_required", item_path)


def _matches_schema_type(value: Any, schema: dict[str, Any]) -> bool:
    wanted = str((schema or {}).get("type") or "")
    if not wanted:
        return True
    mapping: dict[str, Any] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    allowed = mapping.get(wanted)
    if allowed is None:
        return True
    if wanted in {"integer", "number"} and isinstance(value, bool):
        return False
    return isinstance(value, allowed)

def dependencies_from_inputs(inputs: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for ref in _iter_input_refs(inputs):
        task_id = str(ref.get("from_tool_task_id") or "").strip()
        if task_id and task_id not in rows:
            rows.append(task_id)
    return rows


class ToolDagValidator:
    """Validate private Tool selection, schemas, dependencies and goal coverage.

    The validator never inserts, deletes, replaces, or reorders Tool tasks.
    """

    def __init__(self, registry: ToolRegistry, directory: WorkerToolDirectory) -> None:
        self.registry = registry
        self.directory = directory

    def validate_payload(
        self,
        payload: dict[str, Any],
        *,
        worker_role: str,
        worker_task_id: str,
        available_context_keys: set[str],
        allowed_tool_names: set[str] | None = None,
        read_only: bool = False,
        frozen_task_signatures: dict[str, dict[str, Any]] | None = None,
        previous_task_ids: set[str] | None = None,
    ) -> ToolDagPlan:
        if not isinstance(payload, dict):
            raise ToolDagContractViolation("tool_dag_payload_must_be_object", "$")
        goal = payload.get("goal_contract")
        rows = payload.get("tasks")
        finals = payload.get("final_output_task_ids")
        if not isinstance(goal, dict):
            raise ToolDagContractViolation("tool_dag_goal_contract_required", "$.goal_contract")
        if not isinstance(rows, list) or not rows:
            raise ToolDagContractViolation("tool_dag_tasks_required", "$.tasks")
        if not isinstance(finals, list) or not finals:
            raise ToolDagContractViolation("tool_dag_final_outputs_required", "$.final_output_task_ids")

        required_goal_keys = {
            str(item).strip()
            for item in goal.get("required_output_keys") or []
            if str(item or "").strip()
        }
        if not str(goal.get("goal_summary") or "").strip():
            raise ToolDagContractViolation("tool_dag_goal_summary_required", "$.goal_contract.goal_summary")
        if not required_goal_keys:
            raise ToolDagContractViolation("tool_dag_required_output_keys_required", "$.goal_contract.required_output_keys")

        allowed = set(allowed_tool_names or self.directory.allowed_tool_names(worker_role))
        task_ids: list[str] = []
        tasks: list[ToolDagTask] = []
        definitions: dict[str, Any] = {}
        signatures = dict(frozen_task_signatures or {})
        previous = set(previous_task_ids or set())
        for index, row in enumerate(rows):
            path = f"$.tasks[{index}]"
            if not isinstance(row, dict):
                raise ToolDagContractViolation("tool_dag_task_must_be_object", path)
            task_id = str(row.get("tool_task_id") or "").strip()
            tool_name = str(row.get("tool_name") or "").strip()
            objective = str(row.get("objective") or "").strip()
            args = row.get("args")
            inputs = row.get("inputs")
            if not task_id:
                raise ToolDagContractViolation("tool_task_id_required", f"{path}.tool_task_id")
            if task_id in task_ids:
                raise ToolDagContractViolation("duplicate_tool_task_id", f"{path}.tool_task_id", task_id)
            if task_id in previous and task_id not in signatures:
                raise ToolDagContractViolation("tool_replan_reused_superseded_task_id", f"{path}.tool_task_id", task_id)
            if not objective:
                raise ToolDagContractViolation("tool_task_objective_required", f"{path}.objective")
            if tool_name not in allowed or not self.directory.allows(worker_role, tool_name):
                raise ToolDagContractViolation("worker_private_tool_not_allowed", f"{path}.tool_name", tool_name)
            definition = self.registry.get(tool_name)
            if definition is None or not definition.enabled:
                raise ToolDagContractViolation("tool_not_available", f"{path}.tool_name", tool_name)
            if read_only and definition.operation_type != OP_READ:
                raise ToolDagContractViolation("read_only_worker_selected_non_read_tool", f"{path}.tool_name", tool_name)
            if not isinstance(args, dict):
                raise ToolDagContractViolation("tool_task_args_must_be_object", f"{path}.args")
            if not isinstance(inputs, dict):
                raise ToolDagContractViolation("tool_task_inputs_must_be_object", f"{path}.inputs")
            properties = definition.input_schema.get("properties") or {}
            overlapping = sorted(set(args) & set(inputs))
            if overlapping:
                raise ToolDagContractViolation(
                    "tool_task_argument_declared_in_args_and_inputs",
                    path,
                    ",".join(overlapping),
                )
            supplied_keys = set(args) | set(inputs)
            unknown = sorted(supplied_keys - set(properties))
            if unknown:
                raise ToolDagContractViolation("tool_task_unknown_argument", path, ",".join(unknown))
            missing = sorted(set(definition.input_schema.get("required") or []) - supplied_keys)
            if missing:
                raise ToolDagContractViolation("tool_task_missing_required_argument", path, ",".join(missing))
            for name, value in args.items():
                if name in properties and not _matches_schema_type(value, properties.get(name) or {}):
                    raise ToolDagContractViolation(
                        "tool_task_argument_type_mismatch",
                        f"{path}.args.{name}",
                        str((properties.get(name) or {}).get("type") or ""),
                    )
            for name, spec in inputs.items():
                _validate_input_binding_shape(spec, path=f"{path}.inputs.{name}")
                if not list(_iter_input_refs(spec)):
                    raise ToolDagContractViolation(
                        "tool_task_input_must_reference_context_or_tool",
                        f"{path}.inputs.{name}",
                    )
            for ref in _iter_input_refs(inputs):
                context_key = str(ref.get("from_context") or "").strip()
                upstream_id = str(ref.get("from_tool_task_id") or "").strip()
                if bool(context_key) == bool(upstream_id):
                    raise ToolDagContractViolation("tool_input_ref_requires_one_source", path, str(ref)[:500])
                if context_key and context_key not in available_context_keys:
                    raise ToolDagContractViolation("tool_input_context_key_not_available", path, context_key)
            # Required Tool result fields are compiled from the registered Tool
            # output schema. The LLM does not choose or rename them.
            declared_outputs = {
                str(item)
                for item in definition.output_schema.get("required_data_keys") or []
                if str(item).strip()
            }
            task = ToolDagTask(
                tool_task_id=task_id,
                tool_name=tool_name,
                objective=objective,
                args=dict(args),
                inputs=dict(inputs),
                expected_output_keys=sorted(declared_outputs),
                priority=max(0, min(10, int(row.get("priority", 1)))),
            )
            if task_id in signatures and task.to_dict() != signatures[task_id]:
                raise ToolDagContractViolation("tool_replan_modified_frozen_task", path, task_id)
            task_ids.append(task_id)
            tasks.append(task)
            definitions[task_id] = definition

        known = set(task_ids)
        for index, task in enumerate(tasks):
            unknown_dependencies = sorted(set(dependencies_from_inputs(task.inputs)) - known)
            if unknown_dependencies:
                raise ToolDagContractViolation(
                    "tool_task_dependency_not_found",
                    f"$.tasks[{index}].inputs",
                    ",".join(unknown_dependencies),
                )

        final_ids = [str(item).strip() for item in finals if str(item or "").strip()]
        if len(final_ids) != len(set(final_ids)):
            raise ToolDagContractViolation("duplicate_final_tool_task_id", "$.final_output_task_ids")
        missing_finals = sorted(set(final_ids) - known)
        if missing_finals:
            raise ToolDagContractViolation("final_tool_task_not_found", "$.final_output_task_ids", ",".join(missing_finals))

        self._validate_acyclic(tasks)
        self._validate_contribution(tasks, final_ids)
        final_outputs: set[str] = set()
        task_by_id = {task.tool_task_id: task for task in tasks}
        for task_id in final_ids:
            final_outputs.update(task_by_id[task_id].expected_output_keys)
            final_outputs.update(definitions[task_id].produced_outputs or [])
        missing_goal_outputs = sorted(required_goal_keys - final_outputs)
        if missing_goal_outputs:
            raise ToolDagContractViolation(
                "tool_dag_goal_output_not_produced",
                "$.goal_contract.required_output_keys",
                ",".join(missing_goal_outputs),
            )

        return ToolDagPlan(
            worker_task_id=str(worker_task_id),
            worker_role=str(worker_role),
            goal_contract=dict(goal),
            tasks=tasks,
            final_output_task_ids=final_ids,
        )

    @staticmethod
    def _validate_acyclic(tasks: list[ToolDagTask]) -> None:
        by_id = {task.tool_task_id: task for task in tasks}
        remaining = set(by_id)
        completed: set[str] = set()
        while remaining:
            ready = [
                task_id
                for task_id in remaining
                if set(dependencies_from_inputs(by_id[task_id].inputs)).issubset(completed)
            ]
            if not ready:
                raise ToolDagContractViolation("tool_dag_cycle_or_stalled", "$.tasks", ",".join(sorted(remaining)))
            completed.update(ready)
            remaining.difference_update(ready)

    @staticmethod
    def _validate_contribution(tasks: list[ToolDagTask], final_ids: list[str]) -> None:
        by_id = {task.tool_task_id: task for task in tasks}
        needed = set(final_ids)
        stack = list(final_ids)
        while stack:
            task_id = stack.pop()
            for dependency in dependencies_from_inputs(by_id[task_id].inputs):
                if dependency not in needed:
                    needed.add(dependency)
                    stack.append(dependency)
        unused = sorted(set(by_id) - needed)
        if unused:
            raise ToolDagContractViolation("tool_dag_task_has_no_final_contribution", "$.tasks", ",".join(unused))


__all__ = ["ToolDagValidator", "dependencies_from_inputs"]
