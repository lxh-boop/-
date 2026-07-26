"""Atomic Worker-private graph connectivity diagnostic."""

from __future__ import annotations

from typing import Any

from agent.tool_runtime import (
    AGENT_WORKER,
    OP_SYSTEM,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    description,
    result_schema,
    schema,
)

from .backends import DiagnosticToolBackend


DIAGNOSTIC_GRAPH_CONNECTIVITY_TOOL = "graph.system.check_connectivity"


def build_diagnostic_tool_definitions(
    provider: DiagnosticToolBackend,
) -> list[ToolDefinition]:
    def check_connectivity(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        del arguments, context
        return provider.check_connectivity()

    return [
        ToolDefinition(
            name=DIAGNOSTIC_GRAPH_CONNECTIVITY_TOOL,
            display_name="Check Financial Graph Connectivity",
            description=description(
                "Verify connectivity to the configured financial graph.",
                "The assigned diagnostic capability needs a bounded connectivity check.",
                "Full system diagnosis, repair, configuration changes, or service restarts.",
                "No business input.",
                "Connectivity status and graph identifier.",
            ),
            input_schema=schema({}),
            output_schema=result_schema(["status", "graph_id"]),
            execution_handler=check_connectivity,
            argument_builder=lambda _: {},
            supported_actions=["check_graph_connectivity"],
            supported_objects=["financial_graph_runtime"],
            produced_outputs=["diagnostic_analysis"],
            operation_type=OP_SYSTEM,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=[
                "system.check_graph_connectivity"
            ],
            permission_scope=OP_SYSTEM,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            mutates_business_state=False,
            idempotency="read_only",
            audit_level="full",
            tags=["worker_private", "system", "atomic"],
        )
    ]
