"""Atomic private tools used by the evidence-retrieval Worker.

The handlers translate registered tool inputs into calls on the stable graph
provider facade.  They do not select Workers, plan task graphs, or expose
provider identifiers to the coordinator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.collaboration.agent_directory import EVIDENCE_RETRIEVER
from agent.graph.contracts import GraphNodeKind, GraphRef, refs_from
from agent.graph.provider_adapter import GraphProviderAdapter
from agent.tool_runtime import (
    OP_READ,
    OP_SYSTEM,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    description,
    result_schema,
    schema,
)


EVIDENCE_ANALYZE_ENTITIES_TOOL = "graph.evidence.analyze_entities"
EVIDENCE_RETRIEVE_TOOL = "graph.evidence.retrieve"


def _object_refs(arguments: dict[str, Any]) -> list[GraphRef]:
    refs = [
        ref
        for ref in refs_from(arguments.get("object_refs") or [])
        if ref.node_kind == GraphNodeKind.OBJECT
    ]
    if not refs:
        raise ValueError("object_refs_required")
    return refs


def _path(
    context: dict[str, Any],
    key: str,
    default: str | Path,
) -> str | Path:
    return context.get(key) or default


def build_evidence_tool_definitions(
    provider: GraphProviderAdapter,
) -> list[ToolDefinition]:
    """Bind evidence tools to one run-scoped provider dependency."""

    def analyze_entities(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return provider.analyze_entities(
            _object_refs(arguments),
            user_id=str(arguments.get("user_id") or context.get("user_id") or ""),
            output_dir=_path(context, "output_dir", "outputs"),
            db_path=context.get("db_path"),
        )

    def retrieve_evidence(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return provider.retrieve_evidence(
            _object_refs(arguments),
            query=str(arguments.get("query") or ""),
            top_k=max(1, min(int(arguments.get("top_k") or 20), 100)),
            output_dir=_path(context, "output_dir", "outputs"),
            db_path=context.get("db_path"),
            source_task_id=str(
                arguments.get("source_task_id")
                or context.get("task_id")
                or ""
            ),
            source_agent_id=str(
                arguments.get("source_agent_id")
                or context.get("agent_role")
                or ""
            ),
            as_of_time=str(arguments.get("as_of_time") or ""),
        )

    object_ref_property = {
        "object_refs": {
            "type": "array",
            "description": "Authoritative financial-object GraphRefs.",
        },
        "user_id": {"type": "string"},
    }
    return [
        ToolDefinition(
            name=EVIDENCE_ANALYZE_ENTITIES_TOOL,
            display_name="Analyze Entity Evidence",
            description=description(
                "Analyze evidence for authoritative financial-object GraphRefs.",
                "An Evidence Worker must run the existing entity-analysis path.",
                "Free-text entity resolution, portfolio impact, or business writes.",
                "object_refs and user_id.",
                "Per-entity analysis results and normalized evidence sources.",
            ),
            input_schema=schema(
                object_ref_property,
                required=["object_refs", "user_id"],
            ),
            output_schema=result_schema(["results"]),
            execution_handler=analyze_entities,
            supported_actions=["analyze_entity_evidence"],
            supported_objects=["financial_object_graph_ref"],
            produced_outputs=["entity_evidence_results"],
            operation_type=OP_READ,
            allowed_agent_types=[EVIDENCE_RETRIEVER],
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            side_effects=[],
            mutates_business_state=False,
            idempotency="read_only",
            audit_level="full",
            tags=["worker_private", "graph", "evidence"],
        ),
        ToolDefinition(
            name=EVIDENCE_RETRIEVE_TOOL,
            display_name="Retrieve Graph Evidence",
            description=description(
                "Retrieve evidence for authoritative financial-object GraphRefs.",
                "An Evidence Worker needs news, RAG, announcement, or research evidence.",
                "Portfolio mutation, strategy proposals, or unrestricted provider access.",
                "object_refs, query, top_k, source task metadata, and time boundary.",
                "Evidence results, GraphRefs, and ingestion records.",
                "May idempotently upsert derived evidence into the financial fact graph.",
            ),
            input_schema=schema(
                {
                    **object_ref_property,
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "source_task_id": {"type": "string"},
                    "source_agent_id": {"type": "string"},
                    "as_of_time": {"type": "string"},
                },
                required=[
                    "object_refs",
                    "query",
                    "source_task_id",
                    "source_agent_id",
                ],
            ),
            output_schema=result_schema(
                ["results", "evidence_refs", "ingestion_results"]
            ),
            execution_handler=retrieve_evidence,
            supported_actions=[
                "retrieve_evidence",
                "ingest_evidence",
                "resolve_context",
            ],
            supported_objects=["financial_object_graph_ref"],
            produced_outputs=[
                "evidence_results",
                "evidence_refs",
                "ingestion_results",
            ],
            operation_type=OP_SYSTEM,
            allowed_agent_types=[EVIDENCE_RETRIEVER],
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            side_effects=["derived_evidence_graph_upsert"],
            mutates_business_state=False,
            idempotency="provider_source_ref_upsert",
            audit_level="full",
            tags=["worker_private", "graph", "evidence", "derived_write"],
        ),
    ]
