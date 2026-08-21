from __future__ import annotations

from agent.collaboration.worker_directory import PORTFOLIO_ANALYST
from agent.tool_dag.contracts import ToolDagContractViolation
from agent.tool_dag.executor import ToolDagExecutor
from agent.tool_dag.validation import ToolDagValidator
from agent.tool_runtime import (
    OP_READ,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    ToolExecutor,
    ToolInputContract,
    ToolOutputContract,
    ToolRegistry,
    UnifiedToolResult,
)
from agent.worker_tools.internal_system import (
    INTERNAL_ENTITY_RESOLVE_RANKED_SECURITY,
    INTERNAL_PREDICTION_GET_STOCK,
    INTERNAL_RANKING_GET_LATEST,
    INTERNAL_PORTFOLIO_GET_STATE,
    INTERNAL_USER_PROFILE_GET,
    build_internal_system_tool_definitions,
)
from agent.worker_tools.registry import WorkerToolDirectory
from agent.artifacts import build_artifact_from_result


def _desc(name: str) -> str:
    return (
        f"Function: {name}.\n"
        "Applies when: the Worker needs this private capability.\n"
        "Not for: unrelated work.\n"
        "Preconditions: required inputs only.\n"
        "Main inputs: declared semantic slots.\n"
        "Main outputs: declared semantic slots.\n"
        "Side effects: None; read-only."
    )


def _contracted_tool(
    *,
    name: str,
    handler,
    input_properties: dict,
    required: list[str],
    inputs: list[ToolInputContract],
    outputs: list[ToolOutputContract],
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        display_name=name,
        description=_desc(name),
        input_schema={
            "type": "object",
            "properties": dict(input_properties),
            "required": list(required),
            "additionalProperties": True,
        },
        output_schema={"type": "object", "required_data_keys": []},
        execution_handler=handler,
        produced_outputs=[item.slot_id for item in outputs],
        required_input_slots=list(required),
        input_contracts=inputs,
        output_contracts=outputs,
        operation_type=OP_READ,
        allowed_agent_types=[PORTFOLIO_ANALYST],
        visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
    )


def test_runtime_maps_raw_tool_result_to_semantic_output_slot() -> None:
    definition = _contracted_tool(
        name="ranking",
        handler=lambda args, ctx: {
            "success": True,
            "data": {"records": [{"code": "600519", "rank": 1}]},
        },
        input_properties={},
        required=[],
        inputs=[],
        outputs=[
            ToolOutputContract(
                slot_id="market_ranking_signals",
                schema_id="RankingSignals.v1",
                source_path="data.records",
            )
        ],
    )
    registry = ToolRegistry([definition])
    result = ToolExecutor(registry).execute(
        "ranking", {}, context={}, agent_type=PORTFOLIO_ANALYST
    )

    assert result.success is True
    assert result.data["records"][0]["code"] == "600519"
    assert result.data["slots"]["market_ranking_signals"] == [
        {"code": "600519", "rank": 1}
    ]
    assert "market_ranking_signals" in result.data["produced_information_slots"]
    assert result.metadata["tool_io_contract_version"] == "tool-io-contract.v2"
    assert result.data["slot_contracts"]["market_ranking_signals"] == {
        "contract": "market_ranking_signals",
        "version": "1.0",
        "schema_id": "RankingSignals.v1",
    }


def test_worker_sees_semantic_contract_but_not_runtime_source_path() -> None:
    definition = _contracted_tool(
        name="ranking",
        handler=lambda args, ctx: {"success": True, "data": {"records": []}},
        input_properties={},
        required=[],
        inputs=[],
        outputs=[
            ToolOutputContract(
                slot_id="market_ranking_signals",
                schema_id="RankingSignals.v1",
                source_path="data.records",
                description="ranking facts",
            )
        ],
    )
    directory = WorkerToolDirectory(ToolRegistry([definition]))
    details = directory.load_details(PORTFOLIO_ANALYST, ["ranking"])[0]

    assert details["output_contract"] == [
        {
            "slot_id": "market_ranking_signals",
            "contract": "market_ranking_signals",
            "version": "1.0",
            "schema_id": "RankingSignals.v1",
            "description": "ranking facts",
            "provenance_required": True,
        }
    ]
    assert "source_path" not in str(details)


def test_artifact_carries_unified_contract_and_provenance() -> None:
    contract = ToolOutputContract(
        slot_id="portfolio_risk",
        schema_id="PortfolioRisk.v1",
        source_path="data.risk",
        contract="portfolio.risk",
        version="1.0",
    )
    artifact = build_artifact_from_result(
        user_id="alice",
        run_id="run_1",
        task_id="task_1",
        producer_id="risk.calculate",
        result={"success": True, "data": {"risk": {"level": "low"}}},
        output_contracts=[contract],
        provenance={
            "provider_type": "mcp",
            "server_id": "data",
            "transport_tool_name": "get_portfolio_risk",
        },
    )
    assert artifact.contract == "portfolio.risk"
    assert artifact.version == "1.0"
    assert artifact.schema_id == "PortfolioRisk.v1"
    assert artifact.provenance["producer_id"] == "risk.calculate"
    assert artifact.provenance["provider_type"] == "mcp"
    assert artifact.contracts == [
        {
            "slot_id": "portfolio_risk",
            "contract": "portfolio.risk",
            "version": "1.0",
            "schema_id": "PortfolioRisk.v1",
        }
    ]


def test_validator_requires_semantic_output_slot_for_contracted_tool() -> None:
    ranking = _contracted_tool(
        name="ranking",
        handler=lambda args, ctx: {"success": True, "data": {"records": []}},
        input_properties={},
        required=[],
        inputs=[],
        outputs=[
            ToolOutputContract(
                slot_id="market_ranking_signals",
                schema_id="RankingSignals.v1",
                source_path="data.records",
            )
        ],
    )
    resolver = _contracted_tool(
        name="resolver",
        handler=lambda args, ctx: {"success": True, "data": {"node": "n1"}},
        input_properties={"market_ranking_signals": {"type": "array"}},
        required=["market_ranking_signals"],
        inputs=[
            ToolInputContract(
                slot_id="market_ranking_signals",
                schema_id="RankingSignals.v1",
                required=True,
                accepted_sources=("upstream_tool",),
            )
        ],
        outputs=[
            ToolOutputContract(
                slot_id="security_node_id",
                schema_id="SecurityNodeId.v1",
                source_path="data.node",
            )
        ],
    )
    registry = ToolRegistry([ranking, resolver])
    validator = ToolDagValidator(registry, WorkerToolDirectory(registry))
    payload = {
        "goal_contract": {
            "goal_summary": "resolve ranking",
            "required_output_keys": ["security_node_id"],
        },
        "tasks": [
            {
                "tool_task_id": "P01",
                "tool_name": "ranking",
                "objective": "ranking",
                "args": {},
                "inputs": {},
                "priority": 1,
            },
            {
                "tool_task_id": "P02",
                "tool_name": "resolver",
                "objective": "resolve",
                "args": {},
                "inputs": {
                    "market_ranking_signals": {
                        "from_tool_task_id": "P01"
                    }
                },
                "priority": 2,
            },
        ],
        "final_output_task_ids": ["P02"],
    }

    try:
        validator.validate_payload(
            payload,
            worker_role=PORTFOLIO_ANALYST,
            worker_task_id="T01",
            available_context_keys=set(),
            allowed_tool_names={"ranking", "resolver"},
            read_only=True,
        )
    except ToolDagContractViolation as exc:
        assert exc.code == "tool_output_slot_required"
    else:
        raise AssertionError("contracted Tool handoff without output_slot must be rejected")


def test_semantic_slot_drives_tool_to_tool_execution() -> None:
    ranking = _contracted_tool(
        name="ranking",
        handler=lambda args, ctx: {
            "success": True,
            "data": {"records": [{"code": "600519", "rank": 1}]},
        },
        input_properties={},
        required=[],
        inputs=[],
        outputs=[
            ToolOutputContract(
                slot_id="market_ranking_signals",
                schema_id="RankingSignals.v1",
                source_path="data.records",
            )
        ],
    )

    def resolve(args, ctx):
        records = args["market_ranking_signals"]
        return {"success": True, "data": {"node": f"cn:security:sse:{records[0]['code']}"}}

    resolver = _contracted_tool(
        name="resolver",
        handler=resolve,
        input_properties={"market_ranking_signals": {"type": "array"}},
        required=["market_ranking_signals"],
        inputs=[
            ToolInputContract(
                slot_id="market_ranking_signals",
                schema_id="RankingSignals.v1",
                required=True,
                accepted_sources=("upstream_tool",),
            )
        ],
        outputs=[
            ToolOutputContract(
                slot_id="security_node_id",
                schema_id="SecurityNodeId.v1",
                source_path="data.node",
            )
        ],
    )

    def predict(args, ctx):
        return {"success": True, "data": {"record": {"node": args["security_node_id"], "score": 0.99}}}

    prediction = _contracted_tool(
        name="prediction",
        handler=predict,
        input_properties={"security_node_id": {"type": "string"}},
        required=["security_node_id"],
        inputs=[
            ToolInputContract(
                slot_id="security_node_id",
                schema_id="SecurityNodeId.v1",
                required=True,
            )
        ],
        outputs=[
            ToolOutputContract(
                slot_id="entity_model_signals",
                schema_id="EntityModelSignals.v1",
                source_path="data.record",
            )
        ],
    )
    registry = ToolRegistry([ranking, resolver, prediction])
    directory = WorkerToolDirectory(registry)
    validator = ToolDagValidator(registry, directory)
    plan = validator.validate_payload(
        {
            "goal_contract": {
                "goal_summary": "rank then analyze",
                "required_output_keys": ["market_ranking_signals", "entity_model_signals"],
            },
            "tasks": [
                {
                    "tool_task_id": "P01",
                    "tool_name": "ranking",
                    "objective": "ranking",
                    "args": {},
                    "inputs": {},
                    "priority": 1,
                },
                {
                    "tool_task_id": "P02",
                    "tool_name": "resolver",
                    "objective": "resolve",
                    "args": {},
                    "inputs": {
                        "market_ranking_signals": {
                            "from_tool_task_id": "P01",
                            "output_slot": "market_ranking_signals",
                        }
                    },
                    "priority": 2,
                },
                {
                    "tool_task_id": "P03",
                    "tool_name": "prediction",
                    "objective": "predict",
                    "args": {},
                    "inputs": {
                        "security_node_id": {
                            "from_tool_task_id": "P02",
                            "output_slot": "security_node_id",
                        }
                    },
                    "priority": 3,
                },
            ],
            "final_output_task_ids": ["P01", "P03"],
        },
        worker_role=PORTFOLIO_ANALYST,
        worker_task_id="T01",
        available_context_keys=set(),
        allowed_tool_names={"ranking", "resolver", "prediction"},
        read_only=True,
    )
    result = ToolDagExecutor(ToolExecutor(registry)).execute(
        plan,
        available_context={},
        execution_context={},
    )

    assert result.success is True
    assert result.results["P03"].data["slots"]["entity_model_signals"]["score"] == 0.99


def test_local_replan_can_reference_frozen_successful_tool_slot() -> None:
    ranking = _contracted_tool(
        name="ranking",
        handler=lambda args, ctx: {"success": True, "data": {"records": [{"code": "600519"}]}},
        input_properties={},
        required=[],
        inputs=[],
        outputs=[
            ToolOutputContract(
                slot_id="market_ranking_signals",
                schema_id="RankingSignals.v1",
                source_path="data.records",
            )
        ],
    )
    resolver = _contracted_tool(
        name="resolver",
        handler=lambda args, ctx: {"success": True, "data": {"node": "cn:security:sse:600519"}},
        input_properties={"market_ranking_signals": {"type": "array"}},
        required=["market_ranking_signals"],
        inputs=[ToolInputContract("market_ranking_signals", "RankingSignals.v1", True)],
        outputs=[ToolOutputContract("security_node_id", "SecurityNodeId.v1", "data.node")],
    )
    prediction = _contracted_tool(
        name="prediction",
        handler=lambda args, ctx: {"success": True, "data": {"signal": {"score": 1.0}}},
        input_properties={"security_node_id": {"type": "string"}},
        required=["security_node_id"],
        inputs=[ToolInputContract("security_node_id", "SecurityNodeId.v1", True)],
        outputs=[ToolOutputContract("entity_model_signals", "EntityModelSignals.v1", "data.signal")],
    )
    registry = ToolRegistry([ranking, resolver, prediction])
    validator = ToolDagValidator(registry, WorkerToolDirectory(registry))

    frozen_task = {
        "tool_task_id": "P01",
        "tool_name": "ranking",
        "objective": "ranking",
        "args": {},
        "inputs": {},
        "expected_output_keys": [],
        "priority": 1,
    }
    replan = validator.validate_payload(
        {
            "goal_contract": {
                "goal_summary": "finish prediction",
                "required_output_keys": ["market_ranking_signals", "entity_model_signals"],
            },
            "tasks": [
                {
                    "tool_task_id": "P02_retry",
                    "tool_name": "resolver",
                    "objective": "resolve frozen ranking",
                    "args": {},
                    "inputs": {
                        "market_ranking_signals": {
                            "from_tool_task_id": "P01",
                            "output_slot": "market_ranking_signals",
                        }
                    },
                    "priority": 2,
                },
                {
                    "tool_task_id": "P03_retry",
                    "tool_name": "prediction",
                    "objective": "prediction",
                    "args": {},
                    "inputs": {
                        "security_node_id": {
                            "from_tool_task_id": "P02_retry",
                            "output_slot": "security_node_id",
                        }
                    },
                    "priority": 3,
                },
            ],
            "final_output_task_ids": ["P01", "P03_retry"],
        },
        worker_role=PORTFOLIO_ANALYST,
        worker_task_id="T01",
        available_context_keys=set(),
        allowed_tool_names={"ranking", "resolver", "prediction"},
        read_only=True,
        frozen_task_signatures={"P01": frozen_task},
        previous_task_ids={"P01", "P02", "P03"},
    )
    frozen_result = UnifiedToolResult(
        success=True,
        tool_name="ranking",
        data={
            "records": [{"code": "600519"}],
            "slots": {"market_ranking_signals": [{"code": "600519"}]},
            "produced_information_slots": ["market_ranking_signals"],
        },
    )
    executed = ToolDagExecutor(ToolExecutor(registry)).execute(
        replan,
        available_context={},
        execution_context={},
        existing_results={"P01": frozen_result},
        only_task_ids={"P02_retry", "P03_retry"},
    )

    assert executed.success is True
    assert executed.execution_batches == [["P02_retry"], ["P03_retry"]]


def test_real_w02_contracts_form_semantic_chain_without_exposing_paths() -> None:
    class FakeIdentity:
        def resolve_identity(self, *args, **kwargs):
            return []

    class FakeProvider:
        identity = FakeIdentity()

        def public_entity_descriptor(self, ref):
            return {}

    directory = WorkerToolDirectory(ToolRegistry(build_internal_system_tool_definitions(FakeProvider())))
    details = {
        row["tool_id"]: row
        for row in directory.load_details(
            PORTFOLIO_ANALYST,
            [
                INTERNAL_RANKING_GET_LATEST,
                INTERNAL_ENTITY_RESOLVE_RANKED_SECURITY,
                INTERNAL_PREDICTION_GET_STOCK,
            ],
        )
    }

    assert details[INTERNAL_RANKING_GET_LATEST]["output_contract"][0]["slot_id"] == "market_ranking_signals"
    assert details[INTERNAL_ENTITY_RESOLVE_RANKED_SECURITY]["input_contract"][0]["schema_id"] == "RankingSignals.v1"
    assert any(
        item["slot_id"] == "security_node_id" and item["schema_id"] == "SecurityNodeId.v1"
        for item in details[INTERNAL_ENTITY_RESOLVE_RANKED_SECURITY]["output_contract"]
    )
    assert details[INTERNAL_PREDICTION_GET_STOCK]["input_contract"][0]["schema_id"] == "SecurityNodeId.v1"
    assert "source_path" not in str(details)


def test_real_w02_portfolio_and_profile_use_split_semantic_projections() -> None:
    class FakeIdentity:
        def resolve_identity(self, *args, **kwargs):
            return []

    class FakeProvider:
        identity = FakeIdentity()

        def public_entity_descriptor(self, ref):
            return {}

    definitions = {
        item.name: item
        for item in build_internal_system_tool_definitions(FakeProvider())
    }
    portfolio = definitions[INTERNAL_PORTFOLIO_GET_STATE]
    portfolio_paths = {item.slot_id: item.source_path for item in portfolio.output_contracts}
    assert portfolio_paths == {
        "current_portfolio_state": "data.portfolio_state",
        "portfolio_positions": "data.portfolio_positions",
    }
    profile = definitions[INTERNAL_USER_PROFILE_GET]
    profile_paths = {item.slot_id: item.source_path for item in profile.output_contracts}
    assert profile_paths == {
        "user_profile_state": "data.profile_state",
        "user_constraints": "data.constraints",
    }
