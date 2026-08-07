"""DeepAgents-inspired Worker input projection middleware.

The runtime keeps orchestration metadata separate from execution context.  A
Worker receives only CapabilityContract-bound slots, materialized from the
run-scoped slot store.  Coordinator/audit summaries are never reused as Worker
execution payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.runtime_state import RunSlotStore

from .models import GraphAgentTask


@dataclass(frozen=True)
class ProjectedWorkerInput:
    slot_id: str
    value: Any
    source_type: str
    producer_task_id: str = ""
    value_ref: str = ""


class WorkerInputProjectionMiddleware:
    """Materialize contract-bound Worker inputs from authoritative runtime state.

    This mirrors the context-isolation pattern used by Deep Agents: orchestration
    context stays small while delegated workers receive the concrete context
    required for their task.  No fallback to coordinator-visible WorkerResult
    summaries is allowed.
    """

    def __init__(self, slot_store: RunSlotStore) -> None:
        self.slot_store = slot_store

    @staticmethod
    def _runtime_values(
        task: GraphAgentTask,
        execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        all_refs = [*task.focus_refs, *task.context_refs]
        source_roles = {"source", "cause", "event", "relation_source"}
        target_roles = {"target", "impact_target", "portfolio", "holding", "relation_target"}
        source_ids = {str(item) for item in task.args.get("source_ref_ids") or [] if str(item)}
        target_ids = {str(item) for item in task.args.get("target_ref_ids") or [] if str(item)}
        source_refs = [
            ref for ref in all_refs
            if (source_ids and ref.node_id in source_ids)
            or (not source_ids and str(ref.role or "") in source_roles)
        ]
        target_refs = [
            ref for ref in all_refs
            if (target_ids and ref.node_id in target_ids)
            or (not target_ids and str(ref.role or "") in target_roles)
        ]
        return {
            "current_user_request": execution_context.get("current_user_request"),
            "user_identity": {"user_id": task.user_id},
            "permission_context": execution_context.get("permission_context") or {},
            "reply_language": execution_context.get("language") or "zh",
            "as_of_time": task.as_of_time,
            "runtime_context": execution_context,
            "business_parameters": task.business_parameters,
            "authoritative_entity_refs": [ref.to_dict() for ref in task.focus_refs],
            "context_entity_refs": [ref.to_dict() for ref in task.context_refs],
            "source_entity_refs": [ref.to_dict() for ref in source_refs],
            "target_entity_refs": [ref.to_dict() for ref in target_refs],
            "session_summary": execution_context.get("memory_summary") or "",
        }

    def project(
        self,
        task: GraphAgentTask,
        *,
        execution_context: dict[str, Any],
    ) -> tuple[dict[str, Any], list[ProjectedWorkerInput]]:
        runtime_values = self._runtime_values(task, execution_context)
        resolved: dict[str, Any] = {}
        audit_rows: list[ProjectedWorkerInput] = []

        for binding in task.resolved_input_bindings:
            slot_id = str(binding.get("input_slot_id") or "").strip()
            if not slot_id:
                continue
            source_type = str(binding.get("source_type") or "").strip()
            producer_task_id = str(binding.get("producer_task_id") or "").strip()
            output_slot_id = str(binding.get("output_slot_id") or slot_id).strip()
            value_ref = ""

            if source_type in {"runtime_context", "user_parameter"}:
                value = runtime_values.get(slot_id)
            elif source_type == "upstream_task":
                record = self.slot_store.read_bound(
                    run_id=task.run_id,
                    task_id=producer_task_id,
                    slot_id=output_slot_id,
                )
                value = record.value if record is not None else None
                value_ref = record.value_ref if record is not None else ""
            else:
                value = None

            # Multiple bindings to one consumer slot remain an ordered collection.
            if slot_id in resolved:
                current = resolved[slot_id]
                resolved[slot_id] = [*current, value] if isinstance(current, list) else [current, value]
            else:
                resolved[slot_id] = value

            audit_rows.append(ProjectedWorkerInput(
                slot_id=slot_id,
                value=value,
                source_type=source_type,
                producer_task_id=producer_task_id,
                value_ref=value_ref,
            ))

        return resolved, audit_rows


__all__ = ["ProjectedWorkerInput", "WorkerInputProjectionMiddleware"]
