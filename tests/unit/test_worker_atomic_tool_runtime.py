"""Regression tests for the private atomic Worker-tool boundary."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

from agent.collaboration.agent_directory import (
    AgentDirectory,
    EVIDENCE_RETRIEVER,
    RISK_ANALYST,
)
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.tool_engine import (
    ToolDefinition as FacadeToolDefinition,
    ToolExecutor as FacadeToolExecutor,
    ToolRegistry as FacadeToolRegistry,
    get_tool_registry_v2,
)
from agent.tool_runtime import (
    OP_SYSTEM,
    TOOL_VISIBILITY_PUBLIC,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
)
from agent.worker_tools import (
    EVIDENCE_ANALYZE_ENTITIES_TOOL,
    EVIDENCE_RETRIEVE_TOOL,
    WorkerToolDirectory,
    build_worker_tool_registry,
)


def _object_ref() -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id="object:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
    )


def _provider() -> SimpleNamespace:
    ref = _object_ref()
    return SimpleNamespace(
        analyze_entities=Mock(
            return_value={
                "success": True,
                "results": [
                    {
                        "focus_ref": ref.to_dict(),
                        "success": True,
                        "message": "ok",
                        "records": [],
                        "sources": [],
                        "data": {},
                    }
                ],
            }
        ),
        retrieve_evidence=Mock(
            return_value={
                "success": True,
                "results": [
                    {
                        "focus_ref": ref.to_dict(),
                        "success": True,
                        "message": "ok",
                        "records": [],
                        "sources": [],
                    }
                ],
                "evidence_refs": [],
                "ingestion_results": [],
            }
        ),
    )


def test_tool_engine_remains_a_compatible_runtime_facade() -> None:
    assert FacadeToolDefinition is ToolDefinition
    assert FacadeToolExecutor is ToolExecutor
    assert FacadeToolRegistry is ToolRegistry

    definitions = get_tool_registry_v2().list()

    assert len(definitions) == 55
    assert all(
        definition.visibility == TOOL_VISIBILITY_PUBLIC
        for definition in definitions
    )


def test_worker_directory_is_generated_from_private_registry_metadata() -> None:
    registry = build_worker_tool_registry(provider=_provider())
    directory = WorkerToolDirectory(registry)

    assert directory.allowed_tool_names(EVIDENCE_RETRIEVER) == [
        EVIDENCE_ANALYZE_ENTITIES_TOOL,
        EVIDENCE_RETRIEVE_TOOL,
    ]
    assert directory.allowed_tool_names(RISK_ANALYST) == []
    assert directory.allows(
        EVIDENCE_RETRIEVER,
        EVIDENCE_RETRIEVE_TOOL,
    )
    assert not directory.allows(RISK_ANALYST, EVIDENCE_RETRIEVE_TOOL)
    assert all(
        definition.visibility == TOOL_VISIBILITY_WORKER_PRIVATE
        for definition in registry.list()
    )
    assert registry.get(EVIDENCE_RETRIEVE_TOOL).operation_type == OP_SYSTEM
    assert registry.get(EVIDENCE_RETRIEVE_TOOL).mutates_business_state is False
    assert registry.get(EVIDENCE_RETRIEVE_TOOL).side_effects == [
        "derived_evidence_graph_upsert"
    ]


def test_private_evidence_tool_rejects_another_worker_role() -> None:
    provider = _provider()
    executor = ToolExecutor(
        registry=build_worker_tool_registry(provider=provider)
    )

    result = executor.execute(
        EVIDENCE_ANALYZE_ENTITIES_TOOL,
        {
            "object_refs": [_object_ref().to_dict()],
            "user_id": "user-1",
        },
        agent_type=RISK_ANALYST,
    )

    assert result.success is False
    assert result.error_type == "unauthorized_tool"
    provider.analyze_entities.assert_not_called()


def test_private_evidence_tool_translates_graphrefs_for_provider() -> None:
    provider = _provider()
    executor = ToolExecutor(
        registry=build_worker_tool_registry(provider=provider)
    )

    result = executor.execute(
        EVIDENCE_ANALYZE_ENTITIES_TOOL,
        {
            "object_refs": [_object_ref().to_dict()],
            "user_id": "user-1",
        },
        agent_type=EVIDENCE_RETRIEVER,
    )

    assert result.success is True
    assert result.data["results"][0]["success"] is True
    provider.analyze_entities.assert_called_once()
    assert provider.analyze_entities.call_args.args[0] == [_object_ref()]


def test_evidence_worker_calls_registered_private_tool(tmp_path) -> None:
    provider = _provider()
    runtime = SpecialistRuntime(
        llm_service=SimpleNamespace(),
        provider=provider,
        impact_service=SimpleNamespace(),
    )
    task = GraphAgentTask(
        task_id="task-evidence",
        run_id="run-1",
        session_id="session-1",
        assigned_agent=EVIDENCE_RETRIEVER,
        objective="retrieve evidence",
        task_type="retrieve_evidence",
        user_id="user-1",
        focus_refs=[_object_ref()],
    )

    result = runtime.run(
        task,
        current_user_request="retrieve evidence",
        dependency_results={},
        output_dir=tmp_path,
        db_path=None,
        default_top_k=5,
        language="zh",
    )

    assert result.status == ResultStatus.COMPLETED
    assert (
        result.metadata["tool_execution"]["tool_name"]
        == EVIDENCE_RETRIEVE_TOOL
    )
    provider.retrieve_evidence.assert_called_once()
    assert provider.retrieve_evidence.call_args.args[0] == [_object_ref()]


def test_evidence_worker_locally_selects_entity_analysis_tool(tmp_path) -> None:
    provider = _provider()
    runtime = SpecialistRuntime(
        llm_service=SimpleNamespace(),
        provider=provider,
        impact_service=SimpleNamespace(),
    )
    task = GraphAgentTask(
        task_id="task-compare-evidence",
        run_id="run-1",
        session_id="session-1",
        assigned_agent=EVIDENCE_RETRIEVER,
        objective="compare evidence",
        task_type="compare_entity_evidence",
        user_id="user-1",
        focus_refs=[_object_ref()],
    )

    result = runtime.run(
        task,
        current_user_request="compare evidence",
        dependency_results={},
        output_dir=tmp_path,
        db_path=None,
        default_top_k=5,
        language="zh",
    )

    assert result.status == ResultStatus.COMPLETED
    assert (
        result.metadata["tool_execution"]["tool_name"]
        == EVIDENCE_ANALYZE_ENTITIES_TOOL
    )
    provider.analyze_entities.assert_called_once()
    provider.retrieve_evidence.assert_not_called()


def test_coordinator_capability_cards_hide_private_tool_names() -> None:
    encoded = json.dumps(
        AgentDirectory().safe_catalog(),
        ensure_ascii=False,
        sort_keys=True,
    )

    assert "graph.evidence." not in encoded
    assert "provider" not in encoded.lower()
