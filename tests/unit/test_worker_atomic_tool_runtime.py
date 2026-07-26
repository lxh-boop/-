"""Regression tests for capability-scoped private Worker tools."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.models import (
    ContextRequestCategory,
    GraphAgentTask,
    ResultStatus,
)
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.graph.contracts import (
    GraphNodeKind,
    GraphPathRef,
    GraphRef,
)
from agent.tool_engine import (
    ToolDefinition as FacadeToolDefinition,
    ToolExecutor as FacadeToolExecutor,
    ToolRegistry as FacadeToolRegistry,
    get_tool_registry_v2,
)
from agent.tool_runtime import (
    AGENT_MAIN,
    AGENT_WORKER,
    OP_PROPOSAL,
    TOOL_VISIBILITY_PUBLIC,
    TOOL_VISIBILITY_SYSTEM_PRIVATE,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
)
from agent.worker_planning.executor import WorkerPlanExecutor
from agent.worker_planning.validator import (
    WorkerPlanValidationError,
    WorkerPlanValidator,
)
from agent.worker_tools import (
    EVIDENCE_ANALYZE_ENTITIES_TOOL,
    EVIDENCE_INGEST_TOOL,
    EVIDENCE_SEARCH_TOOL,
    IMPACT_FIND_PATHS_TOOL,
    IMPACT_SUMMARIZE_PATHS_TOOL,
    MARKET_READ_RANKING_TOOL,
    PORTFOLIO_MATERIALIZE_SNAPSHOT_TOOL,
    PORTFOLIO_READ_SNAPSHOT_TOOL,
    WorkerToolDirectory,
    build_worker_tool_directory,
    build_worker_tool_registry,
)


class FakeLLM:
    settings = SimpleNamespace()
    profile_id = "test"
    config_hash = "test"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def generate_json(self, *, stage: str, validator=None, **_: object):
        self.calls.append(stage)
        payload = json.loads(json.dumps(self.payload))
        if validator:
            validator(payload)
        return payload


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
        search_evidence=Mock(
            return_value={
                "success": True,
                "results": [
                    {
                        "focus_ref": ref.to_dict(),
                        "success": True,
                        "message": "ok",
                        "records": [{"source_id": "news-1"}],
                        "sources": [],
                    }
                ],
            }
        ),
        ingest_evidence=Mock(
            return_value={
                "success": True,
                "evidence_refs": [],
                "ingestion_results": [{"patch_id": "patch-1"}],
            }
        ),
        read_portfolio_snapshot=Mock(
            return_value={
                "success": True,
                "message": "ok",
                "account_summary": {"total_assets": 100000.0},
                "positions": [],
                "position_count": 0,
            }
        ),
        materialize_portfolio_snapshot=Mock(
            return_value={
                "success": True,
                "portfolio_ref": {
                    "graph_id": "financial_graph",
                    "node_id": "portfolio:user-1",
                    "node_kind": "portfolio",
                    "role": "portfolio",
                },
                "holding_refs": [],
                "unresolved_positions": [],
                "portfolio": {},
            }
        ),
    )


def _directory(
    provider=None,
    impact_backend=None,
    market_backend=None,
) -> WorkerToolDirectory:
    backend = provider or _provider()
    registry = build_worker_tool_registry(
        evidence_backend=backend,
        portfolio_backend=backend,
        risk_backend=backend,
        diagnostic_backend=backend,
        market_backend=market_backend,
        impact_backend=impact_backend or SimpleNamespace(),
    )
    return build_worker_tool_directory(registry)


def test_tool_engine_facade_separates_public_and_system_private_tools() -> None:
    assert FacadeToolDefinition is ToolDefinition
    assert FacadeToolExecutor is ToolExecutor
    assert FacadeToolRegistry is ToolRegistry

    definitions = get_tool_registry_v2().list()

    assert len(definitions) == 48
    assert {
        "market.analyze_stock",
        "market.compare_stocks",
        "evidence.get_stock_evidence",
        "evidence.get_market_evidence",
        "portfolio.design_target_portfolio",
    }.isdisjoint(
        definition.name for definition in definitions
    )
    private_names = {
        definition.name
        for definition in definitions
        if definition.visibility == TOOL_VISIBILITY_SYSTEM_PRIVATE
    }
    assert private_names == {
        "memory.search",
        "memory.get_summary",
        "sandbox.python_analysis",
        "portfolio.save_target_artifact",
    }
    assert all(
        definition.visibility
        in {TOOL_VISIBILITY_PUBLIC, TOOL_VISIBILITY_SYSTEM_PRIVATE}
        for definition in definitions
    )


def test_worker_directory_is_projected_by_capability_not_worker_name() -> None:
    directory = _directory()

    assert directory.allowed_tool_names("evidence.research") == [
        EVIDENCE_ANALYZE_ENTITIES_TOOL,
        EVIDENCE_SEARCH_TOOL,
        EVIDENCE_INGEST_TOOL,
    ]
    assert directory.allowed_tool_names("EVIDENCE_RESEARCHER") == []
    assert directory.allows("evidence.research", EVIDENCE_SEARCH_TOOL)
    assert not directory.allows(
        "portfolio.risk_analysis",
        EVIDENCE_SEARCH_TOOL,
    )
    assert all(
        definition.visibility == TOOL_VISIBILITY_WORKER_PRIVATE
        for definition in directory.registry.list()
    )


def test_private_tool_rejects_another_capability() -> None:
    provider = _provider()
    directory = _directory(provider)
    executor = ToolExecutor(registry=directory.registry)

    result = executor.execute(
        EVIDENCE_ANALYZE_ENTITIES_TOOL,
        {
            "object_refs": [_object_ref().to_dict()],
            "user_id": "user-1",
        },
        agent_type=AGENT_WORKER,
        capability_id="portfolio.risk_analysis",
    )

    assert result.success is False
    assert result.error_type == "unauthorized_worker_capability"
    provider.analyze_entities.assert_not_called()


def test_portfolio_worker_reads_one_atomic_snapshot(tmp_path) -> None:
    provider = _provider()
    directory = _directory(provider)
    executor = ToolExecutor(registry=directory.registry)

    assert directory.allowed_tool_names("portfolio.analysis") == [
        PORTFOLIO_READ_SNAPSHOT_TOOL,
        PORTFOLIO_MATERIALIZE_SNAPSHOT_TOOL,
    ]
    assert directory.registry.get("graph.portfolio.read_state") is None

    result = executor.execute(
        PORTFOLIO_READ_SNAPSHOT_TOOL,
        {"user_id": "user-1"},
        context={"output_dir": tmp_path},
        agent_type=AGENT_WORKER,
        capability_id="portfolio.analysis",
    )

    assert result.success is True
    assert result.data["portfolio_payload"]["position_count"] == 0
    provider.read_portfolio_snapshot.assert_called_once()
    provider.materialize_portfolio_snapshot.assert_not_called()


def test_atomic_evidence_search_does_not_ingest(tmp_path) -> None:
    provider = _provider()
    directory = _directory(provider)
    executor = ToolExecutor(registry=directory.registry)

    result = executor.execute(
        EVIDENCE_SEARCH_TOOL,
        {
            "object_refs": [_object_ref().to_dict()],
            "user_id": "user-1",
            "query": "evidence",
            "top_k": 5,
        },
        context={"output_dir": tmp_path},
        agent_type=AGENT_WORKER,
        capability_id="evidence.research",
    )

    assert result.success is True
    provider.search_evidence.assert_called_once()
    provider.ingest_evidence.assert_not_called()


def test_market_worker_plans_atomic_ranking_read(tmp_path) -> None:
    market_backend = SimpleNamespace(
        resolve_stock_query=Mock(
            side_effect=lambda ref: ref.node_id
        ),
        read_ranking=Mock(
            return_value={
                "success": True,
                "data": {
                    "records": [
                        {"stock_code": "600519", "rank": 1}
                    ]
                },
            }
        ),
        lookup_stock=Mock(),
        read_signal_summary=Mock(),
    )
    directory = _directory(market_backend=market_backend)
    assert directory.allowed_tool_names("market.stock_analysis") == [
        MARKET_READ_RANKING_TOOL,
        "market.lookup_stocks",
        "market.read_signal_summary",
    ]
    binding = AgentDirectory().resolve("market.stock_analysis")
    runtime = SpecialistRuntime(
        llm_service=FakeLLM(
            {
                "steps": [
                    {
                        "step_id": "ranking",
                        "tool_name": MARKET_READ_RANKING_TOOL,
                        "objective": "read local ranking",
                        "dependency_step_ids": [],
                        "required_outputs": [
                            "market_observations"
                        ],
                    }
                ]
            }
        ),
        worker_tool_directory=directory,
    )
    task = GraphAgentTask(
        task_id="task-market",
        run_id="run-1",
        session_id="session-1",
        assigned_agent=binding.worker_id,
        objective="analyze local market ranking",
        task_type=binding.task_type,
        user_id="user-1",
        capability_id=binding.capability_id,
    )

    result = runtime.run(
        task,
        current_user_request="analyze local market ranking",
        dependency_results={},
        output_dir=tmp_path,
        db_path=None,
        default_top_k=5,
        language="en",
    )

    assert result.status == ResultStatus.COMPLETED
    market_backend.read_ranking.assert_called_once()
    market_backend.lookup_stock.assert_not_called()


def test_evidence_worker_plans_and_executes_search_then_ingest(
    tmp_path,
) -> None:
    provider = _provider()
    llm = FakeLLM(
        {
            "steps": [
                {
                    "step_id": "search",
                    "tool_name": EVIDENCE_SEARCH_TOOL,
                    "objective": "search evidence",
                    "dependency_step_ids": [],
                    "required_outputs": ["evidence_results"],
                    "proposed_arguments": {},
                },
                {
                    "step_id": "ingest",
                    "tool_name": EVIDENCE_INGEST_TOOL,
                    "objective": "ingest searched evidence",
                    "dependency_step_ids": ["search"],
                    "required_outputs": ["ingestion_results"],
                    "proposed_arguments": {},
                },
            ]
        }
    )
    runtime = SpecialistRuntime(
        llm_service=llm,
        worker_tool_directory=_directory(provider),
    )
    task = GraphAgentTask(
        task_id="task-evidence",
        run_id="run-1",
        session_id="session-1",
        assigned_agent="EVIDENCE_RESEARCHER",
        objective="research evidence",
        task_type="research_evidence",
        user_id="user-1",
        capability_id="evidence.research",
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
    assert result.metadata["worker_plan"]["step_count"] == 2
    assert provider.search_evidence.call_count == 1
    assert provider.ingest_evidence.call_count == 1
    assert llm.calls == ["worker_private_tool_planner"]


def test_worker_plan_rejects_missing_atomic_dependency() -> None:
    validator = WorkerPlanValidator(_directory())

    with pytest.raises(
        WorkerPlanValidationError,
        match="worker_tool_dependency_output_missing",
    ):
        validator.parse_and_validate(
            {
                "steps": [
                    {
                        "step_id": "ingest",
                        "tool_name": EVIDENCE_INGEST_TOOL,
                        "objective": "ingest",
                        "dependency_step_ids": [],
                        "required_outputs": ["ingestion_results"],
                    },
                    {
                        "step_id": "search",
                        "tool_name": EVIDENCE_SEARCH_TOOL,
                        "objective": "search",
                        "dependency_step_ids": [],
                        "required_outputs": ["evidence_results"],
                    },
                ]
            },
            capability_id="evidence.research",
        )


def test_impact_worker_plans_atomic_lookup_then_summary(tmp_path) -> None:
    evidence_ref = GraphRef(
        graph_id="financial_graph",
        node_id="evidence:news-1",
        node_kind=GraphNodeKind.EVIDENCE,
        role="cause",
    )
    portfolio_ref = GraphRef(
        graph_id="financial_graph",
        node_id="portfolio:user-1",
        node_kind=GraphNodeKind.OBJECT,
        role="portfolio",
    )
    path = GraphPathRef(
        path_id="path-1",
        start_ref=evidence_ref,
        end_ref=portfolio_ref,
        confidence=0.9,
    )
    impact_service = SimpleNamespace(
        find_paths=Mock(return_value=[path]),
        summarize_paths=Mock(
            return_value={"holding_count": 1, "path_count": 1}
        ),
    )
    llm = FakeLLM(
        {
            "steps": [
                {
                    "step_id": "find",
                    "tool_name": IMPACT_FIND_PATHS_TOOL,
                    "objective": "find impact paths",
                    "dependency_step_ids": [],
                    "required_outputs": ["impact_paths"],
                },
                {
                    "step_id": "summarize",
                    "tool_name": IMPACT_SUMMARIZE_PATHS_TOOL,
                    "objective": "summarize impact paths",
                    "dependency_step_ids": ["find"],
                    "required_outputs": ["impact_summary"],
                },
            ]
        }
    )
    runtime = SpecialistRuntime(
        llm_service=llm,
        worker_tool_directory=_directory(
            _provider(),
            impact_service,
        ),
    )
    binding = AgentDirectory().resolve(
        "graph.impact_analysis"
    )
    task = GraphAgentTask(
        task_id="task-impact",
        run_id="run-1",
        session_id="session-1",
        assigned_agent=binding.worker_id,
        objective="map event impact to holdings",
        task_type=binding.task_type,
        user_id="user-1",
        capability_id=binding.capability_id,
        focus_refs=[evidence_ref],
        context_refs=[portfolio_ref],
    )

    result = runtime.run(
        task,
        current_user_request="analyze the holding impact",
        dependency_results={},
        output_dir=tmp_path,
        db_path=None,
        default_top_k=5,
        language="en",
    )

    assert result.status == ResultStatus.COMPLETED
    impact_service.find_paths.assert_called_once()
    impact_service.summarize_paths.assert_called_once()
    assert result.metadata["worker_plan"]["step_count"] == 2


def test_strategy_worker_has_one_proposal_only_private_step() -> None:
    directory = _directory()
    definitions = [
        definition
        for definition in directory.registry.list()
        if "strategy.proposal"
        in definition.allowed_capability_ids
    ]

    assert definitions
    assert directory.max_steps("strategy.proposal") == 1
    assert all(
        definition.operation_type == OP_PROPOSAL
        and definition.allowed_agent_types == [AGENT_WORKER]
        and AGENT_MAIN not in definition.allowed_agent_types
        for definition in definitions
    )
    with pytest.raises(
        WorkerPlanValidationError,
        match="worker_plan_too_many_steps",
    ):
        WorkerPlanValidator(directory).parse_and_validate(
            {
                "steps": [
                    {
                        "step_id": "proposal_1",
                        "tool_name": "strategy.builder.preview",
                        "objective": "build proposal",
                        "proposed_arguments": {
                            "requirement": "low turnover"
                        },
                    },
                    {
                        "step_id": "proposal_2",
                        "tool_name": "strategy.management.preview",
                        "objective": "build another proposal",
                        "proposed_arguments": {"action": "disable"},
                    },
                ]
            },
            capability_id="strategy.proposal",
        )


def test_missing_proposal_scope_becomes_worker_context_request(
    tmp_path,
) -> None:
    directory = _directory()
    validator = WorkerPlanValidator(directory)
    plan = validator.parse_and_validate(
        {
            "steps": [
                {
                    "step_id": "prepare",
                    "tool_name": "strategy.prepare_implementation",
                    "objective": "prepare implementation proposal",
                    "proposed_arguments": {
                        "proposal_id": "proposal-1",
                        "proposal_version": 1,
                    },
                }
            ]
        },
        capability_id="strategy.proposal",
    )
    binding = AgentDirectory().resolve("strategy.proposal")
    task = GraphAgentTask(
        task_id="task-proposal",
        run_id="run-1",
        session_id="session-1",
        assigned_agent=binding.worker_id,
        objective="prepare the proposal",
        task_type=binding.task_type,
        user_id="user-1",
        capability_id=binding.capability_id,
    )

    execution = WorkerPlanExecutor(
        directory=directory,
        tool_executor=ToolExecutor(registry=directory.registry),
    ).execute(
        plan,
        task=task,
        user_request="prepare it",
        dependency_results={},
        output_dir=tmp_path,
        db_path=None,
        default_top_k=5,
        memory_values={},
        execution_context={},
    )

    assert execution.success is False
    assert [item.key for item in execution.missing_items] == [
        "account_id"
    ]
    assert (
        execution.missing_items[0].category.value
        == "memory_lookup_required"
    )


def test_missing_input_source_is_declarative_not_name_heuristic() -> None:
    missing = WorkerPlanExecutor._missing_required_inputs(
        {
            "type": "object",
            "required": ["account_id", "stock_id", "api_key"],
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "已确认账户",
                    "x-context-source": "memory",
                },
                "stock_id": {
                    "type": "string",
                    "description": "用户选择的证券",
                },
                "api_key": {
                    "type": "string",
                    "description": "外部服务密钥",
                    "x-context-source": "system_config",
                },
            },
        },
        {},
    )

    by_key = {item.key: item for item in missing}
    assert (
        by_key["account_id"].category
        == ContextRequestCategory.MEMORY_LOOKUP_REQUIRED
    )
    assert by_key["account_id"].allow_memory_lookup is True
    assert (
        by_key["stock_id"].category
        == ContextRequestCategory.USER_INPUT_REQUIRED
    )
    assert by_key["stock_id"].allow_memory_lookup is False
    assert (
        by_key["api_key"].category
        == ContextRequestCategory.SYSTEM_CONFIG_REQUIRED
    )
    assert by_key["api_key"].sensitivity == "secret"
    assert by_key["api_key"].allow_memory_lookup is False


def test_worker_tools_do_not_import_worker_identity_constants() -> None:
    root = Path(__file__).resolve().parents[2]
    for path in (root / "agent" / "worker_tools").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "agent.collaboration.agent_directory" not in source
        assert "EVIDENCE_RESEARCHER" not in source
        assert "PORTFOLIO_RISK_ANALYST" not in source


def test_coordinator_capability_cards_hide_private_tool_names() -> None:
    encoded = json.dumps(
        AgentDirectory().safe_catalog(),
        ensure_ascii=False,
        sort_keys=True,
    )

    assert "graph.evidence." not in encoded
    assert "graph.portfolio." not in encoded
    assert "provider" not in encoded.lower()
