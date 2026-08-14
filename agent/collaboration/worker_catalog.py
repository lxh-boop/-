"""Upfront MainAgent-visible Worker capability-scope catalog.

The MainAgent receives every eligible Worker's full *public* professional scope
before it selects Worker calls.  The fine-grained legacy capability boundaries
remain Runtime validation material only; they are not exposed as a menu for the
MainAgent to choose from.  Private prompts and private Tool details remain hidden.
"""

from __future__ import annotations

from typing import Any

from .worker_directory import CapabilityWorkerDirectory

_EFFECT_ORDER = {"read": 0, "proposal": 1, "write": 2}


class WorkerDescriptionCatalog:
    def __init__(
        self,
        directory: CapabilityWorkerDirectory,
        capability_registry: Any,
        *,
        worker_tool_directory: Any | None = None,
    ) -> None:
        self.directory = directory
        self.capability_registry = capability_registry
        self.worker_tool_directory = worker_tool_directory

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
        """Return one broad public capability scope for every eligible Worker."""

        rows: list[dict[str, Any]] = []
        for card in self.directory.list():
            if not self._eligible(card, request_mode):
                continue
            scope = self.capability_registry.aggregate_scope(card.supported_boundary_ids)
            input_patterns = list(scope["accepted_input_patterns"])
            output_patterns = list(scope["produced_output_patterns"])
            input_examples = list(scope["input_slot_examples"])
            output_examples = list(scope["output_slot_examples"])
            private_tool_output_slots: list[str] = []
            if self.worker_tool_directory is not None and list(card.private_tool_ids or []):
                private_tool_output_slots = self.worker_tool_directory.semantic_output_slots(
                    card.agent_id,
                    tool_names=list(card.private_tool_ids),
                )
                output_examples.extend(private_tool_output_slots)
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
                "output_publication_mode": card.output_publication_mode,
                "effect_limit": card.max_effect_level,
                "accepted_input_patterns": list(dict.fromkeys(input_patterns)),
                "produced_output_patterns": list(dict.fromkeys(output_patterns)),
                "input_slot_examples": list(dict.fromkeys(input_examples)),
                "output_slot_examples": list(dict.fromkeys(output_examples)),
                "allowed_acceptance_rule_ids": list(scope["allowed_acceptance_rule_ids"]),
                "accepted_business_parameter_patterns": list(scope.get("accepted_business_parameter_patterns") or []),
                "capability_scope_mode": "worker_level",
                "private_tool_semantic_outputs": list(private_tool_output_slots),
                "private_tool_details_visible_to_main_agent": False,
            })
        return rows



__all__ = ["WorkerDescriptionCatalog"]
