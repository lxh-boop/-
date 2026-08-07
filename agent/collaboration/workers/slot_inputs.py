"""Slot-native input projection for specialist Workers.

SlotBinder is authoritative. Workers receive only the information slots that
their CapabilityContract declares and the runtime actually resolves.
"""

from __future__ import annotations

from typing import Any

from ..models import GraphAgentTask
from .common import execution_safe_value, safe_public_value


def producer_task_ids(task: GraphAgentTask, slot_id: str) -> list[str]:
    ids: list[str] = []
    for binding in task.resolved_input_bindings:
        if str(binding.get("input_slot_id") or "") != str(slot_id):
            continue
        producer = str(binding.get("producer_task_id") or "").strip()
        if producer and producer not in ids:
            ids.append(producer)
    return ids


def slot_envelopes(
    task: GraphAgentTask,
    resolved_inputs: dict[str, Any] | None,
    *,
    include_slots: set[str] | None = None,
    projection: str = "execution",
) -> list[dict[str, Any]]:
    """Return provenance-aware envelopes for resolved information slots.

    ``execution`` preserves the materialized business payload for the delegated
    Worker. ``audit`` applies the lossy observer-safe projection.
    """

    rows: list[dict[str, Any]] = []
    for slot_id, value in dict(resolved_inputs or {}).items():
        slot_id = str(slot_id or "").strip()
        if not slot_id or (include_slots is not None and slot_id not in include_slots):
            continue
        if value is None:
            continue
        rows.append({
            "slot_id": slot_id,
            "source_task_ids": producer_task_ids(task, slot_id),
            "source_type": "upstream_task" if producer_task_ids(task, slot_id) else "runtime_context",
            "payload": (
                safe_public_value(value)
                if projection == "audit"
                else execution_safe_value(value)
            ),
            "status": "available",
        })
    return rows



def contract_input_slot_ids(task: GraphAgentTask) -> set[str]:
    """Return every input slot explicitly declared by the task contracts."""

    slots: set[str] = set()
    for contract in list(task.contracts or []):
        if not isinstance(contract, dict):
            continue
        for item in list(contract.get("required_inputs") or []):
            if not isinstance(item, dict):
                continue
            slot_id = str(item.get("slot_id") or "").strip()
            if slot_id:
                slots.add(slot_id)
    return slots

def contract_required_slot_ids(task: GraphAgentTask) -> set[str]:
    """Return only inputs that the public CapabilityContract marks as required.

    Worker implementations must not promote their preferred enrichment inputs to
    blocking requirements. The contract is the sole authority for minimum input
    sufficiency.
    """

    required: set[str] = set()
    for contract in list(task.contracts or []):
        if not isinstance(contract, dict):
            continue
        for item in list(contract.get("required_inputs") or []):
            if not isinstance(item, dict) or not bool(item.get("required", True)):
                continue
            slot_id = str(item.get("slot_id") or "").strip()
            if slot_id:
                required.add(slot_id)
    return required


def available_slot_ids(resolved_inputs: dict[str, Any] | None) -> set[str]:
    """Return slot ids actually bound by Runtime; empty containers remain valid values."""

    return {
        str(slot_id)
        for slot_id, value in dict(resolved_inputs or {}).items()
        if str(slot_id) and value is not None
    }


def missing_contract_required_slot_ids(
    task: GraphAgentTask,
    resolved_inputs: dict[str, Any] | None,
) -> set[str]:
    """Return missing required bindings before a Worker is invoked.

    This is a Runtime-side sufficiency primitive. Domain Workers should not
    inspect hypothetical unbound information domains; they only receive the
    resolved inputs that pass this gate. Empty containers are valid bound
    values and only ``None`` is treated as absent.
    """

    return contract_required_slot_ids(task) - available_slot_ids(resolved_inputs)


__all__ = ["available_slot_ids", "contract_input_slot_ids", "contract_required_slot_ids", "missing_contract_required_slot_ids", "producer_task_ids", "slot_envelopes"]
