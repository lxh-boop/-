"""Upfront MainAgent-visible Worker description catalog.

The MainAgent receives every eligible Worker's full *public* description before
it selects Worker calls. Private prompts and private Tool details remain hidden.
This keeps description-driven delegation while avoiding progressive, plan-as-you-go
Worker discovery.
"""

from __future__ import annotations

from typing import Any

from .worker_directory import CapabilityWorkerDirectory

_EFFECT_ORDER = {"read": 0, "proposal": 1, "write": 2}


class WorkerDescriptionCatalog:
    def __init__(self, directory: CapabilityWorkerDirectory, capability_registry: Any) -> None:
        self.directory = directory
        self.capability_registry = capability_registry

    @staticmethod
    def _mode_limit(request_mode: str) -> str:
        return "proposal" if str(request_mode or "analysis").lower() == "proposal" else "read"

    def _eligible(self, card: Any, request_mode: str) -> bool:
        return (
            str(card.availability or "available") == "available"
            and _EFFECT_ORDER.get(str(card.max_effect_level), 99)
            <= _EFFECT_ORDER[self._mode_limit(request_mode)]
        )

    def descriptions(self, *, request_mode: str) -> list[dict[str, Any]]:
        """Return the complete public delegation surface for every eligible Worker."""

        rows: list[dict[str, Any]] = []
        for card in self.directory.list():
            if not self._eligible(card, request_mode):
                continue
            boundaries = []
            input_slots: list[str] = []
            output_slots: list[str] = []
            for boundary_id in card.supported_boundary_ids:
                boundary = self.capability_registry.get_boundary(boundary_id)
                row = boundary.safe_for_main_agent()
                row["acceptance_rules"] = {
                    rule_id: self.capability_registry.acceptance_rule_description(rule_id)
                    for rule_id in boundary.allowed_acceptance_rule_ids
                }
                boundaries.append(row)
                input_slots.extend(boundary.accepted_input_slots)
                output_slots.extend(boundary.produced_output_slots)
            rows.append({
                "worker_id": card.worker_id,
                "public_role": card.role,
                "short_description": card.short_description,
                "delegation_description": card.delegation_description or card.short_description,
                "delegate_when": list(card.delegate_when),
                "full_description": card.full_description,
                "capability_tags": list(card.capability_tags),
                "supported_scenarios": list(card.supported_scenarios),
                "unsupported_scenarios": list(card.unsupported_scenarios),
                "limitations": list(card.limitations),
                "escalation_policy": card.escalation_policy,
                "execution_mode": card.execution_mode,
                "effect_limit": card.max_effect_level,
                "supported_boundary_ids": list(card.supported_boundary_ids),
                "accepted_input_slots": list(dict.fromkeys(input_slots)),
                "produced_output_slots": list(dict.fromkeys(output_slots)),
                "supported_boundaries": boundaries,
                "private_tool_details_visible_to_main_agent": False,
            })
        return rows

    # Compatibility helpers for older diagnostics/tests. They no longer define
    # the runtime planning sequence.
    def summaries(self, *, request_mode: str) -> list[dict[str, Any]]:
        return [
            {
                "worker_id": row["worker_id"],
                "short_description": row["short_description"],
                "delegation_description": row["delegation_description"],
                "delegate_when": row["delegate_when"],
                "capability_tags": row["capability_tags"],
                "supported_boundary_ids": row["supported_boundary_ids"],
                "accepted_input_slots": row["accepted_input_slots"],
                "produced_output_slots": row["produced_output_slots"],
                "effect_limit": row["effect_limit"],
            }
            for row in self.descriptions(request_mode=request_mode)
        ]

    def load_details(self, worker_ids: list[str], *, request_mode: str) -> list[dict[str, Any]]:
        wanted = {str(item or "").strip().upper() for item in worker_ids if str(item or "").strip()}
        return [
            row for row in self.descriptions(request_mode=request_mode)
            if row["worker_id"] in wanted
        ]


# Backward import compatibility only. The runtime itself uses
# WorkerDescriptionCatalog and performs upfront full-description loading.
ProgressiveWorkerCatalog = WorkerDescriptionCatalog

__all__ = ["WorkerDescriptionCatalog", "ProgressiveWorkerCatalog"]
