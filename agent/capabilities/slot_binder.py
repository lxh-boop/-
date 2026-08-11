from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.collaboration.worker_contracts import WorkerContractViolation

from .models import CapabilityTask, InputOutputBinding


@dataclass(frozen=True)
class SlotBindingResult:
    bindings_by_task: dict[str, list[InputOutputBinding]] = field(default_factory=dict)
    dependency_ids_by_task: dict[str, list[str]] = field(default_factory=dict)
    producer_index: dict[str, list[dict[str, str]]] = field(default_factory=dict)


class SlotBinder:
    """Derive all data/control dependencies from output-to-input contracts."""

    def bind(
        self,
        tasks: list[CapabilityTask],
        *,
        initial_information_slots: set[str],
        external_producers: dict[str, list[dict[str, str]]] | None = None,
    ) -> SlotBindingResult:
        producer_index: dict[str, list[dict[str, str]]] = {
            str(slot): [
                {
                    "source_type": "runtime_context",
                    "producer_task_id": "",
                    "producer_contract_id": "",
                    "schema_id": "",
                    "entity_scope": "runtime",
                }
            ]
            for slot in initial_information_slots
        }
        for slot, rows in dict(external_producers or {}).items():
            producer_index.setdefault(str(slot), []).extend(dict(item) for item in rows)

        for task in tasks:
            for contract in task.contracts:
                for output in contract.promised_outputs:
                    producer_index.setdefault(output.slot_id, []).append(
                        {
                            "source_type": "upstream_task",
                            "producer_task_id": task.task_id,
                            "producer_contract_id": contract.contract_id,
                            "schema_id": output.schema_id,
                            "entity_scope": output.entity_scope,
                        }
                    )

        # Planning-stage preflight: collect every required Slot that has no
        # producer before binding anything. SlotBinder reports the information
        # gap but never chooses or inserts a Worker; Worker selection remains a
        # MainAgent responsibility.
        planning_gaps: list[dict[str, str]] = []
        for task in tasks:
            for contract in task.contracts:
                for required_input in contract.required_inputs:
                    candidates = [
                        item
                        for item in producer_index.get(required_input.slot_id, [])
                        if str(item.get("producer_task_id") or "") != task.task_id
                    ]
                    if required_input.required and not candidates:
                        planning_gaps.append({
                            "gap_type": "required_input_has_no_producer",
                            "consumer_task_id": task.task_id,
                            "consumer_contract_id": contract.contract_id,
                            "consumer_worker_id": task.worker_id,
                            "input_slot_id": required_input.slot_id,
                            "repair_scope": "worker_selection",
                        })
        if planning_gaps:
            first = planning_gaps[0]
            raise WorkerContractViolation(
                "capability_required_input_has_no_producer",
                f"$.tasks[{first['consumer_task_id']}].contracts[{first['consumer_contract_id']}]",
                first["input_slot_id"],
                metadata={"planning_gaps": planning_gaps},
            )

        bindings: dict[str, list[InputOutputBinding]] = {task.task_id: [] for task in tasks}
        dependencies: dict[str, list[str]] = {task.task_id: [] for task in tasks}
        for task in tasks:
            for contract in task.contracts:
                for required_input in contract.required_inputs:
                    candidates = [
                        item
                        for item in producer_index.get(required_input.slot_id, [])
                        if str(item.get("producer_task_id") or "") != task.task_id
                    ]
                    if not candidates:
                        if required_input.required:
                            raise WorkerContractViolation(
                                "capability_required_input_has_no_producer",
                                f"$.tasks[{task.task_id}].contracts[{contract.contract_id}]",
                                required_input.slot_id,
                            )
                        continue

                    upstream = [
                        item for item in candidates if item.get("source_type") == "upstream_task"
                    ]
                    runtime = [
                        item for item in candidates if item.get("source_type") != "upstream_task"
                    ]
                    # An explicit upstream producer takes precedence over the
                    # broad runtime catalog.  Multiple upstream producers are
                    # ambiguous unless they are the same task/contract.
                    selected_pool = upstream or runtime
                    unique = {
                        (
                            str(item.get("source_type") or ""),
                            str(item.get("producer_task_id") or ""),
                            str(item.get("producer_contract_id") or ""),
                        ): item
                        for item in selected_pool
                    }
                    if len(unique) > 1:
                        raise WorkerContractViolation(
                            "capability_input_has_ambiguous_producers",
                            f"$.tasks[{task.task_id}].contracts[{contract.contract_id}]",
                            required_input.slot_id,
                        )
                    selected = next(iter(unique.values()))
                    producer_task_id = str(selected.get("producer_task_id") or "")
                    binding = InputOutputBinding(
                        source_type=str(selected.get("source_type") or "runtime_context"),
                        output_slot_id=required_input.slot_id,
                        consumer_task_id=task.task_id,
                        consumer_contract_id=contract.contract_id,
                        input_slot_id=required_input.slot_id,
                        schema_id=required_input.schema_id or str(selected.get("schema_id") or ""),
                        producer_task_id=producer_task_id,
                        producer_contract_id=str(selected.get("producer_contract_id") or ""),
                        entity_scope=required_input.entity_scope,
                        required_paths=list(required_input.required_paths),
                        optional_paths=list(required_input.optional_paths),
                    )
                    bindings[task.task_id].append(binding)
                    if producer_task_id and producer_task_id not in dependencies[task.task_id]:
                        dependencies[task.task_id].append(producer_task_id)

        self._validate_acyclic(dependencies)
        return SlotBindingResult(
            bindings_by_task=bindings,
            dependency_ids_by_task=dependencies,
            producer_index=producer_index,
        )

    @staticmethod
    def _validate_acyclic(dependencies: dict[str, list[str]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            if task_id in visiting:
                raise WorkerContractViolation("capability_dag_cycle", "$.tasks", task_id)
            visiting.add(task_id)
            for dependency_id in dependencies.get(task_id, []):
                if dependency_id in dependencies:
                    visit(dependency_id)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in dependencies:
            visit(task_id)
