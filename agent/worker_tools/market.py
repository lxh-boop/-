"""Atomic Worker-private reads for local market observations."""

from __future__ import annotations

from typing import Any

from agent.collaboration.models import (
    ContextRequestCategory,
    MissingContextItem,
)
from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.tool_runtime import (
    AGENT_WORKER,
    OP_READ,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    description,
    result_schema,
    schema,
)
from agent.worker_planning.errors import WorkerContextRequired

from .backends import MarketToolBackend


MARKET_READ_RANKING_TOOL = "market.read_ranking"
MARKET_LOOKUP_STOCKS_TOOL = "market.lookup_stocks"
MARKET_READ_SIGNAL_SUMMARY_TOOL = "market.read_signal_summary"
MARKET_CAPABILITY_ID = "market.stock_analysis"


def _object_refs(plan_context: dict[str, Any]) -> list[GraphRef]:
    task = plan_context["task"]
    return [
        ref
        for ref in [*task.focus_refs, *task.context_refs]
        if ref.node_kind == GraphNodeKind.OBJECT
        and "portfolio" not in ref.node_id.lower()
    ]


def build_market_tool_definitions(
    provider: MarketToolBackend,
) -> list[ToolDefinition]:
    def resolved_queries(plan_context: dict[str, Any]) -> list[str]:
        result: list[str] = []
        for ref in _object_refs(plan_context):
            try:
                query = str(
                    provider.resolve_stock_query(ref) or ""
                ).strip()
            except (KeyError, LookupError, RuntimeError, ValueError):
                query = ""
            if query and query not in result:
                result.append(query)
        return result

    def ranking_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
        queries = resolved_queries(plan_context)
        return {
            "stock_code": (
                queries[0] if len(queries) == 1 else ""
            ),
            "top_k": max(
                1,
                min(int(plan_context.get("default_top_k") or 20), 100),
            ),
        }

    def lookup_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
        queries = resolved_queries(plan_context)
        if not queries:
            raise WorkerContextRequired(
                [
                    MissingContextItem(
                        key="stock_refs",
                        description="需要选择要分析或比较的证券对象",
                        expected_format="一个或多个已识别证券 GraphRef",
                        reason="市场分析不能从自由文本猜测证券标识",
                        searched_sources=[
                            "task.focus_refs",
                            "task.context_refs",
                            "session_memory",
                        ],
                        category=ContextRequestCategory.USER_INPUT_REQUIRED,
                        value_schema={
                            "type": "array",
                            "items": {"type": "GraphRef"},
                            "x-context-source": "user",
                        },
                    )
                ]
            )
        return {
            "stock_queries": queries,
            "user_id": plan_context["task"].user_id,
        }

    def signal_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": plan_context["task"].user_id,
            "sort_by": "original_rank",
        }

    def read_ranking(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return provider.read_ranking(
            stock_code=str(arguments.get("stock_code") or ""),
            top_k=max(1, min(int(arguments.get("top_k") or 20), 100)),
            output_dir=context.get("output_dir") or "outputs",
            model_name=str(arguments.get("model_name") or ""),
        )

    def lookup_stocks(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for query in list(arguments.get("stock_queries") or [])[:20]:
            result = provider.lookup_stock(
                str(query or ""),
                user_id=str(
                    arguments.get("user_id")
                    or context.get("user_id")
                    or ""
                ),
                output_dir=context.get("output_dir") or "outputs",
            )
            rows.append(
                {
                    "query": str(query or ""),
                    "success": bool(result.get("success")),
                    "message": str(result.get("message") or ""),
                    "data": dict(result.get("data") or {}),
                    "sources": list(result.get("sources") or []),
                    "warnings": list(result.get("warnings") or []),
                    "errors": list(result.get("errors") or []),
                }
            )
        return {
            "success": bool(rows) and all(row["success"] for row in rows),
            "data": {"lookup_results": rows},
        }

    def read_signal_summary(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return provider.read_signal_summary(
            user_id=str(
                arguments.get("user_id")
                or context.get("user_id")
                or ""
            ),
            output_dir=context.get("output_dir") or "outputs",
            sort_by=str(arguments.get("sort_by") or "original_rank"),
        )

    common_capability = [MARKET_CAPABILITY_ID]
    return [
        ToolDefinition(
            name=MARKET_READ_RANKING_TOOL,
            display_name="Read Local Market Ranking",
            description=description(
                "Read the latest local model ranking or one resolved stock row.",
                "The market-analysis capability needs rank, score, or candidate observations.",
                "News retrieval, portfolio state, target design, or any business write.",
                "Optional resolved stock code and top_k.",
                "Local ranking observations.",
            ),
            input_schema=schema(
                {
                    "stock_code": {
                        "type": "string",
                        "description": "Resolved optional security identifier.",
                    },
                    "top_k": {"type": "integer"},
                    "model_name": {"type": "string"},
                }
            ),
            output_schema=result_schema(["records"]),
            execution_handler=read_ranking,
            argument_builder=ranking_arguments,
            supported_actions=["read_market_ranking"],
            supported_objects=["market_ranking"],
            produced_outputs=["market_observations", "market_ranking"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=common_capability,
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            idempotency="read_only",
            audit_level="full",
            tags=["worker_private", "market", "atomic"],
        ),
        ToolDefinition(
            name=MARKET_LOOKUP_STOCKS_TOOL,
            display_name="Lookup Resolved Stocks",
            description=description(
                "Read local rows for one or more already resolved security GraphRefs.",
                "The market-analysis capability needs comparable row-level observations.",
                "Entity resolution from free text, evidence retrieval, recommendations, or writes.",
                "Resolved stock queries and user context.",
                "One normalized lookup result per requested security.",
            ),
            input_schema=schema(
                {
                    "stock_queries": {
                        "type": "array",
                        "description": "Identifiers resolved from authoritative stock GraphRefs.",
                        "x-context-source": "dependency",
                    },
                    "user_id": {"type": "string"},
                },
                required=["stock_queries", "user_id"],
            ),
            output_schema=result_schema(["lookup_results"]),
            execution_handler=lookup_stocks,
            argument_builder=lookup_arguments,
            supported_actions=["lookup_market_stocks"],
            supported_objects=["stock_graph_ref"],
            produced_outputs=["market_observations", "stock_lookup"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=common_capability,
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            idempotency="read_only",
            audit_level="full",
            tags=["worker_private", "market", "atomic", "batch_read"],
        ),
        ToolDefinition(
            name=MARKET_READ_SIGNAL_SUMMARY_TOOL,
            display_name="Read Local Signal Summary",
            description=description(
                "Read the stored local signal summary without generating a recommendation.",
                "The market-analysis capability needs the same model-signal view as the ranking UI.",
                "Generating AI adjustments, evidence retrieval, portfolio changes, or writes.",
                "User context and a deterministic sort key.",
                "Stored signal-summary observations.",
            ),
            input_schema=schema(
                {
                    "user_id": {"type": "string"},
                    "sort_by": {"type": "string"},
                },
                required=["user_id"],
            ),
            output_schema=result_schema(["records"]),
            execution_handler=read_signal_summary,
            argument_builder=signal_arguments,
            supported_actions=["read_market_signal_summary"],
            supported_objects=["market_signal_summary"],
            produced_outputs=["market_observations", "signal_summary"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=common_capability,
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            idempotency="read_only",
            audit_level="full",
            tags=["worker_private", "market", "atomic"],
        ),
    ]


__all__ = [
    "MARKET_CAPABILITY_ID",
    "MARKET_LOOKUP_STOCKS_TOOL",
    "MARKET_READ_RANKING_TOOL",
    "MARKET_READ_SIGNAL_SUMMARY_TOOL",
    "build_market_tool_definitions",
]
