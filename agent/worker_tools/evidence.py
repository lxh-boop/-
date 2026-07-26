"""Atomic Worker-private tools for evidence analysis, search, and ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.collaboration.models import (
    ContextRequestCategory,
    MissingContextItem,
)
from agent.graph.contracts import GraphNodeKind, GraphRef, refs_from
from agent.tool_runtime import (
    AGENT_WORKER,
    OP_READ,
    OP_SYSTEM,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    UnifiedToolResult,
    description,
    result_schema,
    schema,
)
from agent.worker_planning.errors import WorkerContextRequired

from .backends import EvidenceToolBackend


EVIDENCE_ANALYZE_ENTITIES_TOOL = "graph.evidence.analyze_entities"
EVIDENCE_SEARCH_TOOL = "graph.evidence.search"
EVIDENCE_INGEST_TOOL = "graph.evidence.ingest"


def _path(
    context: dict[str, Any],
    key: str,
    default: str | Path,
) -> str | Path:
    return context.get(key) or default


def _object_refs_from_plan(plan_context: dict[str, Any]) -> list[GraphRef]:
    task = plan_context["task"]
    refs = [
        ref
        for ref in refs_from(
            [
                *[item.to_dict() for item in task.focus_refs],
                *[item.to_dict() for item in task.context_refs],
                *list(
                    dict(plan_context.get("memory_values") or {}).get(
                        "active_graph_refs",
                        [],
                    )
                ),
            ]
        )
        if ref.node_kind == GraphNodeKind.OBJECT
    ]
    if refs:
        return refs
    raise WorkerContextRequired(
        [
            MissingContextItem(
                key="active_graph_refs",
                description="需要明确要分析的金融对象",
                expected_format="选择一个已识别的金融对象",
                reason="证据工具只能处理权威 GraphRef，不能从自由文本猜测对象",
                searched_sources=[
                    "task.focus_refs",
                    "task.context_refs",
                    "session_memory",
                ],
                category=ContextRequestCategory.MEMORY_LOOKUP_REQUIRED,
                value_schema={"type": "array", "items": {"type": "GraphRef"}},
            )
        ]
    )


def _object_ref_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
    task = plan_context["task"]
    return {
        "object_refs": [
            ref.to_dict() for ref in _object_refs_from_plan(plan_context)
        ],
        "user_id": task.user_id,
    }


def _search_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
    task = plan_context["task"]
    return {
        **_object_ref_arguments(plan_context),
        "query": str(
            plan_context.get("user_request") or task.objective or ""
        ),
        "top_k": max(
            1,
            min(int(plan_context.get("default_top_k") or 20), 100),
        ),
        "as_of_time": task.as_of_time,
    }


def _ingest_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
    task = plan_context["task"]
    search_results: list[dict[str, Any]] = []
    for result in dict(plan_context.get("step_results") or {}).values():
        if not isinstance(result, UnifiedToolResult):
            continue
        search_results.extend(
            dict(item)
            for item in result.data.get("results") or []
            if isinstance(item, dict)
        )
    if not search_results:
        raise RuntimeError("evidence_search_results_required")
    return {
        "search_results": search_results,
        "source_task_id": task.task_id,
        "source_agent_id": task.assigned_agent,
    }


def build_evidence_tool_definitions(
    provider: EvidenceToolBackend,
) -> list[ToolDefinition]:
    """Bind atomic evidence tools to one run-scoped provider."""

    def analyze_entities(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return provider.analyze_entities(
            refs_from(arguments.get("object_refs") or []),
            user_id=str(
                arguments.get("user_id") or context.get("user_id") or ""
            ),
            output_dir=_path(context, "output_dir", "outputs"),
            db_path=context.get("db_path"),
        )

    def search_evidence(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return provider.search_evidence(
            refs_from(arguments.get("object_refs") or []),
            query=str(arguments.get("query") or ""),
            top_k=max(1, min(int(arguments.get("top_k") or 20), 100)),
            output_dir=_path(context, "output_dir", "outputs"),
            db_path=context.get("db_path"),
            as_of_time=str(arguments.get("as_of_time") or ""),
        )

    def ingest_evidence(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        del context
        return provider.ingest_evidence(
            [
                dict(item)
                for item in arguments.get("search_results") or []
                if isinstance(item, dict)
            ],
            source_task_id=str(arguments.get("source_task_id") or ""),
            source_agent_id=str(arguments.get("source_agent_id") or ""),
        )

    object_ref_properties = {
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
                "Analyze evidence already associated with authoritative financial objects.",
                "The assigned capability needs per-entity evidence analysis.",
                "Evidence search, ingestion, portfolio analysis, or business writes.",
                "object_refs and user_id.",
                "Normalized per-entity evidence analysis.",
            ),
            input_schema=schema(
                object_ref_properties,
                required=["object_refs", "user_id"],
            ),
            output_schema=result_schema(["results"]),
            execution_handler=analyze_entities,
            argument_builder=_object_ref_arguments,
            supported_actions=["analyze_entity_evidence"],
            supported_objects=["financial_object_graph_ref"],
            produced_outputs=[
                "evidence_observations",
                "entity_evidence_results",
            ],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=["evidence.research"],
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            idempotency="read_only",
            audit_level="full",
            tags=["worker_private", "graph", "evidence", "atomic"],
        ),
        ToolDefinition(
            name=EVIDENCE_SEARCH_TOOL,
            display_name="Search Financial Evidence",
            description=description(
                "Search evidence records for authoritative financial objects.",
                "The assigned capability needs news, RAG, announcement, or research records.",
                "Graph ingestion, portfolio analysis, proposals, or business writes.",
                "object_refs, query, top_k, and time boundary.",
                "Evidence records and source metadata without graph mutation.",
            ),
            input_schema=schema(
                {
                    **object_ref_properties,
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "as_of_time": {"type": "string"},
                },
                required=["object_refs", "query"],
            ),
            output_schema=result_schema(["results"]),
            execution_handler=search_evidence,
            argument_builder=_search_arguments,
            supported_actions=["search_evidence"],
            supported_objects=["financial_object_graph_ref"],
            produced_outputs=[
                "evidence_observations",
                "evidence_results",
            ],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=["evidence.research"],
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            idempotency="read_only",
            audit_level="full",
            tags=["worker_private", "graph", "evidence", "atomic"],
        ),
        ToolDefinition(
            name=EVIDENCE_INGEST_TOOL,
            display_name="Ingest Financial Evidence",
            description=description(
                "Materialize searched evidence records in the derived financial graph.",
                "A preceding evidence-search step returned records that need traceable GraphRefs.",
                "Evidence search, entity analysis, portfolio mutation, or unrestricted graph writes.",
                "search_results and source task metadata.",
                "Evidence GraphRefs and idempotent ingestion results.",
                "Idempotently upserts derived evidence only.",
            ),
            input_schema=schema(
                {
                    "search_results": {"type": "array"},
                    "source_task_id": {"type": "string"},
                    "source_agent_id": {"type": "string"},
                },
                required=[
                    "search_results",
                    "source_task_id",
                    "source_agent_id",
                ],
            ),
            output_schema=result_schema(
                ["evidence_refs", "ingestion_results"]
            ),
            execution_handler=ingest_evidence,
            argument_builder=_ingest_arguments,
            supported_actions=["ingest_evidence"],
            supported_objects=["evidence_record"],
            produced_outputs=[
                "evidence_observations",
                "evidence_refs",
                "ingestion_results",
            ],
            required_dependency_outputs=["evidence_results"],
            operation_type=OP_SYSTEM,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=["evidence.research"],
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            side_effects=["derived_evidence_graph_upsert"],
            mutates_business_state=False,
            idempotency="provider_source_ref_upsert",
            audit_level="full",
            tags=["worker_private", "graph", "evidence", "atomic"],
        ),
    ]


__all__ = [
    "EVIDENCE_ANALYZE_ENTITIES_TOOL",
    "EVIDENCE_INGEST_TOOL",
    "EVIDENCE_SEARCH_TOOL",
    "build_evidence_tool_definitions",
]
