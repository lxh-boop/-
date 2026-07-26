"""Run-scoped registry and private capability view for Worker tools."""

from __future__ import annotations

from dataclasses import dataclass

from agent.graph.provider_adapter import GraphProviderAdapter
from agent.tool_runtime import (
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolRegistry,
)

from .evidence import build_evidence_tool_definitions


@dataclass(frozen=True)
class WorkerToolDirectory:
    """Private role-to-tool projection generated from registry metadata."""

    registry: ToolRegistry

    def allowed_tool_names(self, worker_role: str) -> list[str]:
        return [
            definition.name
            for definition in self.registry.list(
                agent_type=str(worker_role or ""),
                visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            )
        ]

    def allows(self, worker_role: str, tool_name: str) -> bool:
        definition = self.registry.get(tool_name)
        return bool(
            definition
            and definition.visibility == TOOL_VISIBILITY_WORKER_PRIVATE
            and str(worker_role or "") in set(definition.allowed_agent_types)
        )


def build_worker_tool_registry(
    *,
    provider: GraphProviderAdapter,
) -> ToolRegistry:
    """Build private tool definitions against run-scoped dependencies."""

    return ToolRegistry(build_evidence_tool_definitions(provider))
