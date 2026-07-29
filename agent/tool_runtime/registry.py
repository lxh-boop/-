"""In-memory registry for canonical tool definitions and legacy aliases."""

from __future__ import annotations

from typing import Any

from .contracts import (
    OP_PROPOSAL,
    OP_READ,
    OP_SYSTEM,
    OP_WRITE,
    TOOL_VISIBILITIES,
    ToolDefinition,
)


class ToolRegistry:
    """Validate and index tool contracts without executing business logic."""

    def __init__(self, definitions: list[ToolDefinition] | None = None) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._aliases: dict[str, str] = {}
        for definition in definitions or []:
            self.register(definition)

    def register(self, definition: ToolDefinition) -> None:
        self._validate_definition(definition)
        if definition.name in self._definitions or definition.name in self._aliases:
            raise ValueError(f"duplicate_tool_name:{definition.name}")
        self._definitions[definition.name] = definition
        for alias in definition.legacy_names:
            if alias in self._definitions or alias in self._aliases:
                raise ValueError(f"duplicate_tool_name:{alias}")
            self._aliases[alias] = definition.name

    def _validate_definition(self, definition: ToolDefinition) -> None:
        if (
            not definition.name
            or not definition.description
            or not callable(definition.execution_handler)
        ):
            raise ValueError("tool_definition_requires_name_description_handler")
        required_markers = [
            "Function:",
            "Applies when:",
            "Not for:",
            "Preconditions:",
            "Main inputs:",
            "Main outputs:",
            "Side effects:",
        ]
        if any(marker not in definition.description for marker in required_markers):
            raise ValueError(f"invalid_tool_description_template:{definition.name}")
        if (
            not isinstance(definition.input_schema, dict)
            or definition.input_schema.get("type") != "object"
        ):
            raise ValueError(f"invalid_input_schema:{definition.name}")
        if definition.operation_type not in {
            OP_READ,
            OP_PROPOSAL,
            OP_WRITE,
            OP_SYSTEM,
        }:
            raise ValueError(f"invalid_operation_type:{definition.name}")
        if definition.visibility not in TOOL_VISIBILITIES:
            raise ValueError(f"invalid_tool_visibility:{definition.name}")
        if definition.mutates_business_state and not definition.requires_approval:
            raise ValueError(
                f"business_state_mutation_requires_approval:{definition.name}"
            )

    def get(self, name: str) -> ToolDefinition | None:
        key = str(name or "")
        canonical = self._aliases.get(key, key)
        return self._definitions.get(canonical)

    def canonical_name(self, name: str) -> str:
        return self._aliases.get(str(name or ""), str(name or ""))

    def list(
        self,
        *,
        agent_type: str | None = None,
        operation_type: str | None = None,
        visibility: str | None = None,
    ) -> list[ToolDefinition]:
        rows = list(self._definitions.values())
        if agent_type:
            rows = [
                row
                for row in rows
                if agent_type in set(row.allowed_agent_types)
            ]
        if operation_type:
            rows = [row for row in rows if row.operation_type == operation_type]
        if visibility:
            rows = [row for row in rows if row.visibility == visibility]
        return rows

    def public_index_records(
        self,
        *,
        agent_type: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "tool_name": definition.name,
                "description_summary": definition.description.splitlines()[0],
                "supported_actions": list(definition.supported_actions),
                "required_inputs": list(
                    definition.input_schema.get("required") or []
                ),
                "produced_outputs": list(definition.produced_outputs),
                "operation_type": definition.operation_type,
                "allowed_agent_types": list(definition.allowed_agent_types),
                "requires_approval": bool(definition.requires_approval),
                "version": definition.version,
                "test_status": "passed",
                "enabled": bool(definition.enabled),
                "legacy_names": list(definition.legacy_names),
                "visibility": definition.visibility,
                "side_effects": list(definition.side_effects),
                "mutates_business_state": bool(
                    definition.mutates_business_state
                ),
                "idempotency": definition.idempotency,
                "audit_level": definition.audit_level,
            }
            for definition in self.list(agent_type=agent_type)
        ]
