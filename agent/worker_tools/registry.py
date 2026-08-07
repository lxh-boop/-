"""Run-scoped registry and progressive private Tool catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.graph.impact_service import GraphImpactService
from agent.graph.provider_adapter import GraphProviderAdapter
from agent.tool_runtime import TOOL_VISIBILITY_WORKER_PRIVATE, ToolRegistry
from agent.tool_runtime.validation import input_contracts_for, output_contracts_for

from .evidence import build_evidence_tool_definitions
from .graph_context import build_graph_context_tool_definitions
from .graph_relation import build_graph_relation_tool_definitions
from .internal_system import build_internal_system_tool_definitions
from .risk import build_risk_tool_definitions


@dataclass(frozen=True)
class WorkerToolDirectory:
    """Private role-to-Tool projection with progressive disclosure."""

    registry: ToolRegistry

    def allowed_tool_names(self, worker_role: str) -> list[str]:
        return [
            definition.name
            for definition in self.registry.list(
                agent_type=str(worker_role or ""),
                visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            )
        ]

    def compatible_tool_names(
        self,
        worker_role: str,
        *,
        available_context_keys: set[str],
        allowed_tool_names: list[str] | set[str] | None = None,
    ) -> list[str]:
        available = {str(item) for item in available_context_keys if str(item)}
        allowed = {str(item) for item in (allowed_tool_names or []) if str(item)}
        rows: list[str] = []
        for definition in self.registry.list(
            agent_type=str(worker_role or ""),
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
        ):
            if allowed and definition.name not in allowed:
                continue
            required = {str(item) for item in definition.required_input_slots if str(item)}
            if required.issubset(available):
                rows.append(definition.name)
        return rows

    @staticmethod
    def _required_slots(definition: Any) -> set[str]:
        return {
            str(item.slot_id)
            for item in input_contracts_for(definition)
            if item.required and str(item.slot_id)
        }

    @staticmethod
    def _produced_slots(definition: Any) -> set[str]:
        return {
            str(item.slot_id)
            for item in output_contracts_for(definition)
            if str(item.slot_id)
        }

    def reachable_tool_names(
        self,
        worker_role: str,
        *,
        available_context_keys: set[str],
        allowed_tool_names: list[str] | set[str] | None = None,
    ) -> list[str]:
        """Return private Tools reachable through a Worker-local Tool DAG.

        A Tool does not need to be executable from the *initial* Worker context.
        Its required slots may be produced by another private Tool earlier in the
        same DAG.  This keeps domain planning inside the Worker instead of making
        Runtime pre-decide the Tool sequence.
        """

        available = {str(item) for item in available_context_keys if str(item)}
        allowed = {str(item) for item in (allowed_tool_names or []) if str(item)}
        definitions = [
            definition
            for definition in self.registry.list(
                agent_type=str(worker_role or ""),
                visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            )
            if not allowed or definition.name in allowed
        ]
        reachable: list[str] = []
        pending = list(definitions)
        while pending:
            progressed = False
            next_pending: list[Any] = []
            for definition in pending:
                required = self._required_slots(definition)
                if required.issubset(available):
                    reachable.append(definition.name)
                    available.update(self._produced_slots(definition))
                    progressed = True
                else:
                    next_pending.append(definition)
            if not progressed:
                break
            pending = next_pending
        return reachable

    def allows(self, worker_role: str, tool_name: str) -> bool:
        definition = self.registry.get(tool_name)
        return bool(
            definition
            and definition.visibility == TOOL_VISIBILITY_WORKER_PRIVATE
            and str(worker_role or "") in set(definition.allowed_agent_types)
        )

    @staticmethod
    def _short_description(value: str) -> str:
        text = " ".join(str(value or "").split())
        for marker in ("。", ". ", "\n"):
            if marker in text:
                text = text.split(marker, 1)[0]
                break
        return text[:220]

    def summary_catalog(
        self,
        worker_role: str,
        *,
        tool_names: list[str] | set[str] | None = None,
    ) -> list[dict[str, Any]]:
        selected = {str(item) for item in (tool_names or []) if str(item)}
        rows: list[dict[str, Any]] = []
        for definition in self.registry.list(
            agent_type=str(worker_role or ""),
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
        ):
            if selected and definition.name not in selected:
                continue
            input_contracts = input_contracts_for(definition)
            output_contracts = output_contracts_for(definition)
            rows.append({
                "tool_id": definition.name,
                "short_description": self._short_description(definition.description),
                "required_input_slots": [item.slot_id for item in input_contracts if item.required],
                "optional_input_slots": [item.slot_id for item in input_contracts if not item.required],
                "produced_output_slots": [item.slot_id for item in output_contracts],
                "effect_limit": definition.operation_type,
                "side_effect_count": len(definition.side_effects or []),
                "io_contract_version": "tool-io-contract.v1" if definition.input_contracts or definition.output_contracts else "legacy",
            })
        return rows

    def load_details(self, worker_role: str, tool_ids: list[str]) -> list[dict[str, Any]]:
        requested = list(dict.fromkeys(str(item) for item in tool_ids if str(item)))
        rows: list[dict[str, Any]] = []
        for tool_id in requested:
            definition = self.registry.get(tool_id)
            if definition is None or not self.allows(worker_role, tool_id):
                raise KeyError(f"worker_private_tool_not_available:{worker_role}:{tool_id}")
            semantic_inputs = input_contracts_for(definition)
            semantic_outputs = output_contracts_for(definition)
            rows.append({
                "tool_id": definition.name,
                "description": definition.description,
                "input_schema": dict(definition.input_schema or {}),
                "input_contract": [item.planner_view() for item in semantic_inputs],
                "output_contract": [item.planner_view() for item in semantic_outputs],
                "required_input_slots": [item.slot_id for item in semantic_inputs if item.required],
                "optional_input_slots": [item.slot_id for item in semantic_inputs if not item.required],
                "produced_output_slots": [item.slot_id for item in semantic_outputs],
                "side_effects": list(definition.side_effects or []),
                "operation_type": definition.operation_type,
                "io_contract_version": "tool-io-contract.v1" if definition.input_contracts or definition.output_contracts else "legacy",
            })
        return rows


def build_worker_tool_registry(
    *,
    provider: GraphProviderAdapter,
    impact_service: GraphImpactService | None = None,
) -> ToolRegistry:
    graph_relation_tools = (
        build_graph_relation_tool_definitions(impact_service)
        if impact_service is not None
        else []
    )
    return ToolRegistry([
        *build_evidence_tool_definitions(provider),
        *build_internal_system_tool_definitions(provider),
        *build_graph_context_tool_definitions(provider),
        *build_risk_tool_definitions(),
        *graph_relation_tools,
    ])
