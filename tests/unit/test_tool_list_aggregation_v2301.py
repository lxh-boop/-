from __future__ import annotations

import pytest

from agent.collaboration.worker_directory import EVIDENCE_COLLECTOR, RISK_ANALYST
from agent.tool_dag.validation import ToolDagValidator
from agent.tool_runtime import (
    OP_READ,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    ToolInputContract,
    ToolOutputContract,
    ToolRegistry,
    description,
    result_schema,
    schema,
)
from agent.worker_tools.evidence import (
    EVIDENCE_FINALIZE_COLLECTION_TOOL,
    EVIDENCE_SEARCH_NEWS_TOOL,
    EVIDENCE_SEARCH_RAG_TOOL,
    build_evidence_tool_definitions,
)
from agent.worker_tools.registry import WorkerToolDirectory
from agent.worker_tools.risk import (
    RISK_CALCULATE_CONCENTRATION,
    RISK_FINALIZE_FACTS,
    RISK_READ_ACCOUNT_RISK_FACTS,
    RISK_SUMMARIZE_EXPOSURE,
    build_risk_tool_definitions,
)


def _producer(
    name: str,
    output_slot: str,
    schema_id: str,
    *,
    version: str = "1.0",
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        display_name=name,
        description=description(
            "Produce one semantic payload.",
            "A test Worker needs a semantic payload.",
            "Unrelated work.",
            "No required inputs.",
            "One semantic payload.",
        ),
        input_schema=schema(),
        output_schema=result_schema([output_slot]),
        execution_handler=lambda args, context: {
            "success": True,
            "data": {output_slot: {"producer": name}},
        },
        produced_outputs=[output_slot],
        input_contracts=[],
        output_contracts=[
            ToolOutputContract(
                slot_id=output_slot,
                schema_id=schema_id,
                source_path=f"data.{output_slot}",
                contract="test.collection",
                version=version,
            )
        ],
        operation_type=OP_READ,
        allowed_agent_types=[EVIDENCE_COLLECTOR],
        visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
    )


def _finalizer() -> ToolDefinition:
    return ToolDefinition(
        name="test.finalize",
        display_name="test.finalize",
        description=description(
            "Merge one or more semantic payloads.",
            "A test Worker needs a final aggregate.",
            "Source retrieval.",
            "collections: List[TestCollection].",
            "final_result.",
        ),
        input_schema=schema({"collections": {"type": "array"}}, required=["collections"]),
        output_schema=result_schema(["final_result"]),
        execution_handler=lambda args, context: {
            "success": True,
            "data": {"final_result": list(args["collections"])},
        },
        produced_outputs=["final_result"],
        input_contracts=[
            ToolInputContract(
                slot_id="collections",
                schema_id="TestCollection.v1",
                required=True,
                accepted_sources=("upstream_tool",),
                cardinality="many",
                contract="test.collection",
                version="1.0",
            )
        ],
        output_contracts=[
            ToolOutputContract(slot_id="final_result", source_path="data.final_result")
        ],
        operation_type=OP_READ,
        allowed_agent_types=[EVIDENCE_COLLECTOR],
        visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
    )


def _validator() -> ToolDagValidator:
    registry = ToolRegistry([
        _producer("test.a", "output_a", "TestCollection.v1"),
        _producer("test.b", "output_b", "TestCollection.v1"),
        _producer("test.bad", "wrong_output", "WrongCollection.v1"),
        _producer(
            "test.bad_version",
            "versioned_output",
            "TestCollection.v1",
            version="2.0",
        ),
        _finalizer(),
    ])
    return ToolDagValidator(registry, WorkerToolDirectory(registry))


def _payload(refs: list[dict[str, str]]) -> dict:
    tasks = []
    for index, ref in enumerate(refs, start=1):
        tool_name = str(ref.pop("tool_name"))
        output_slot = str(ref["output_slot"])
        task_id = f"P{index}"
        tasks.append({
            "tool_task_id": task_id,
            "tool_name": tool_name,
            "objective": "produce source payload",
            "args": {},
            "inputs": {},
            "priority": 1,
        })
        ref["from_tool_task_id"] = task_id
        ref["output_slot"] = output_slot
    tasks.append({
        "tool_task_id": "F1",
        "tool_name": "test.finalize",
        "objective": "merge selected semantic payloads",
        "args": {},
        "inputs": {"collections": refs},
        "priority": 2,
    })
    return {
        "goal_contract": {
            "goal_summary": "aggregate source payloads",
            "required_output_keys": ["final_result"],
            "completion_criteria": ["schema_valid"],
        },
        "tasks": tasks,
        "final_output_task_ids": ["F1"],
    }


def test_many_input_accepts_one_upstream_semantic_output() -> None:
    validator = _validator()
    payload = _payload([{"tool_name": "test.a", "output_slot": "output_a"}])
    plan = validator.validate_payload(
        payload,
        worker_role=EVIDENCE_COLLECTOR,
        worker_task_id="T01",
        available_context_keys=set(),
        allowed_tool_names={"test.a", "test.finalize"},
        read_only=True,
    )
    assert plan.tasks[-1].inputs["collections"] == [
        {"output_slot": "output_a", "from_tool_task_id": "P1"}
    ]


def test_many_input_accepts_multiple_independent_tool_outputs() -> None:
    validator = _validator()
    payload = _payload([
        {"tool_name": "test.a", "output_slot": "output_a"},
        {"tool_name": "test.b", "output_slot": "output_b"},
    ])
    plan = validator.validate_payload(
        payload,
        worker_role=EVIDENCE_COLLECTOR,
        worker_task_id="T01",
        available_context_keys=set(),
        allowed_tool_names={"test.a", "test.b", "test.finalize"},
        read_only=True,
    )
    assert len(plan.tasks[-1].inputs["collections"]) == 2


def test_many_input_rejects_single_binding_object() -> None:
    validator = _validator()
    payload = _payload([{"tool_name": "test.a", "output_slot": "output_a"}])
    payload["tasks"][-1]["inputs"]["collections"] = {
        "from_tool_task_id": "P1",
        "output_slot": "output_a",
    }
    with pytest.raises(Exception, match="tool_input_many_requires_non_empty_list"):
        validator.validate_payload(
            payload,
            worker_role=EVIDENCE_COLLECTOR,
            worker_task_id="T01",
            available_context_keys=set(),
            allowed_tool_names={"test.a", "test.finalize"},
            read_only=True,
        )


def test_many_input_rejects_wrong_element_schema() -> None:
    validator = _validator()
    payload = _payload([{"tool_name": "test.bad", "output_slot": "wrong_output"}])
    with pytest.raises(Exception, match="tool_slot_schema_mismatch"):
        validator.validate_payload(
            payload,
            worker_role=EVIDENCE_COLLECTOR,
            worker_task_id="T01",
            available_context_keys=set(),
            allowed_tool_names={"test.bad", "test.finalize"},
            read_only=True,
        )


def test_many_input_rejects_incompatible_artifact_contract_version() -> None:
    validator = _validator()
    payload = _payload(
        [{"tool_name": "test.bad_version", "output_slot": "versioned_output"}]
    )
    with pytest.raises(Exception, match="tool_slot_artifact_contract_mismatch"):
        validator.validate_payload(
            payload,
            worker_role=EVIDENCE_COLLECTOR,
            worker_task_id="T01",
            available_context_keys=set(),
            allowed_tool_names={"test.bad_version", "test.finalize"},
            read_only=True,
        )


def test_one_input_rejects_list_binding() -> None:
    producer = _producer("test.source", "payload", "Payload.v1")
    consumer = ToolDefinition(
        name="test.single",
        display_name="test.single",
        description=description(
            "Consume one payload.",
            "A test Worker needs one payload.",
            "Aggregation.",
            "payload.",
            "done.",
        ),
        input_schema=schema({"payload": {"type": "object"}}, required=["payload"]),
        output_schema=result_schema(["done"]),
        execution_handler=lambda args, context: {"success": True, "data": {"done": True}},
        produced_outputs=["done"],
        input_contracts=[
            ToolInputContract(slot_id="payload", schema_id="Payload.v1", required=True, cardinality="one")
        ],
        output_contracts=[ToolOutputContract(slot_id="done", source_path="data.done")],
        operation_type=OP_READ,
        allowed_agent_types=[EVIDENCE_COLLECTOR],
        visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
    )
    registry = ToolRegistry([producer, consumer])
    validator = ToolDagValidator(registry, WorkerToolDirectory(registry))
    payload = {
        "goal_contract": {
            "goal_summary": "single binding",
            "required_output_keys": ["done"],
            "completion_criteria": ["schema_valid"],
        },
        "tasks": [
            {"tool_task_id": "P1", "tool_name": "test.source", "objective": "produce", "args": {}, "inputs": {}, "priority": 1},
            {
                "tool_task_id": "C1",
                "tool_name": "test.single",
                "objective": "consume",
                "args": {},
                "inputs": {"payload": [{"from_tool_task_id": "P1", "output_slot": "payload"}]},
                "priority": 2,
            },
        ],
        "final_output_task_ids": ["C1"],
    }
    with pytest.raises(Exception, match="tool_input_one_requires_single_binding"):
        validator.validate_payload(
            payload,
            worker_role=EVIDENCE_COLLECTOR,
            worker_task_id="T01",
            available_context_keys=set(),
            allowed_tool_names={"test.source", "test.single"},
            read_only=True,
        )


def test_tool_input_contract_never_names_a_concrete_producer() -> None:
    contract = ToolInputContract(
        slot_id="collections",
        schema_id="EvidenceSourceCollection.v1",
        required=True,
        cardinality="many",
    )
    view = contract.planner_view()
    assert view["cardinality"] == "many"
    assert "producer_tool" not in view
    assert "source_slot" not in view
    assert "from_tool_task_id" not in view


def test_real_evidence_finalizer_declares_source_independent_list_input() -> None:
    class FakeProvider:
        pass

    definitions = build_evidence_tool_definitions(FakeProvider())
    by_name = {item.name: item for item in definitions}
    finalizer = by_name[EVIDENCE_FINALIZE_COLLECTION_TOOL]
    collection_contract = next(item for item in finalizer.input_contracts if item.slot_id == "collections")
    assert collection_contract.cardinality == "many"
    assert collection_contract.schema_id == "EvidenceSourceCollection.v1"
    assert collection_contract.accepted_sources == ("upstream_tool",)

    news = by_name[EVIDENCE_SEARCH_NEWS_TOOL]
    rag = by_name[EVIDENCE_SEARCH_RAG_TOOL]
    assert any(item.slot_id == "news_evidence" and item.schema_id == "EvidenceSourceCollection.v1" for item in news.output_contracts)
    assert any(item.slot_id == "rag_evidence" and item.schema_id == "EvidenceSourceCollection.v1" for item in rag.output_contracts)


def test_real_evidence_dag_accepts_one_or_two_source_tools() -> None:
    class FakeProvider:
        pass

    definitions = build_evidence_tool_definitions(FakeProvider())
    registry = ToolRegistry(definitions)
    validator = ToolDagValidator(registry, WorkerToolDirectory(registry))

    base_source = {
        "tool_task_id": "N1",
        "tool_name": EVIDENCE_SEARCH_NEWS_TOOL,
        "objective": "search news",
        "args": {},
        "inputs": {"object_refs": {"from_context": "authoritative_entity_refs"}},
        "priority": 1,
    }
    rag_source = {
        "tool_task_id": "R1",
        "tool_name": EVIDENCE_SEARCH_RAG_TOOL,
        "objective": "search rag",
        "args": {"query": "贵州茅台"},
        "inputs": {"object_refs": {"from_context": "authoritative_entity_refs"}},
        "priority": 1,
    }

    for source_tasks, refs in [
        ([base_source], [{"from_tool_task_id": "N1", "output_slot": "news_evidence"}]),
        (
            [base_source, rag_source],
            [
                {"from_tool_task_id": "N1", "output_slot": "news_evidence"},
                {"from_tool_task_id": "R1", "output_slot": "rag_evidence"},
            ],
        ),
    ]:
        payload = {
            "goal_contract": {
                "goal_summary": "collect evidence",
                "required_output_keys": ["validated_evidence_collection"],
                "completion_criteria": ["schema_valid"],
            },
            "tasks": [
                *source_tasks,
                {
                    "tool_task_id": "F1",
                    "tool_name": EVIDENCE_FINALIZE_COLLECTION_TOOL,
                    "objective": "finalize evidence",
                    "args": {},
                    "inputs": {
                        "collections": refs,
                        "required_object_refs": {"from_context": "authoritative_entity_refs"},
                    },
                    "priority": 2,
                },
            ],
            "final_output_task_ids": ["F1"],
        }
        plan = validator.validate_payload(
            payload,
            worker_role=EVIDENCE_COLLECTOR,
            worker_task_id="T01",
            available_context_keys={"authoritative_entity_refs"},
            allowed_tool_names={item.name for item in definitions},
            read_only=True,
        )
        assert plan.tasks[-1].tool_name == EVIDENCE_FINALIZE_COLLECTION_TOOL


def test_real_risk_finalizer_uses_common_fragment_schema_without_knowing_producers() -> None:
    definitions = build_risk_tool_definitions()
    by_name = {item.name: item for item in definitions}
    finalizer = by_name[RISK_FINALIZE_FACTS]
    collection_contract = next(item for item in finalizer.input_contracts if item.slot_id == "collections")
    assert collection_contract.cardinality == "many"
    assert collection_contract.schema_id == "RiskFactFragment.v1"

    expected = {
        RISK_CALCULATE_CONCENTRATION: "concentration_risk_fragment",
        RISK_READ_ACCOUNT_RISK_FACTS: "account_risk_fragment",
        RISK_SUMMARIZE_EXPOSURE: "exposure_risk_fragment",
    }
    for tool_name, slot_id in expected.items():
        tool = by_name[tool_name]
        assert any(
            item.slot_id == slot_id and item.schema_id == "RiskFactFragment.v1"
            for item in tool.output_contracts
        )


def test_real_risk_dag_accepts_multiple_independent_fragments() -> None:
    definitions = build_risk_tool_definitions()
    registry = ToolRegistry(definitions)
    validator = ToolDagValidator(registry, WorkerToolDirectory(registry))
    payload = {
        "goal_contract": {
            "goal_summary": "collect risk facts",
            "required_output_keys": ["risk_facts"],
            "completion_criteria": ["schema_valid"],
        },
        "tasks": [
            {
                "tool_task_id": "C1",
                "tool_name": RISK_CALCULATE_CONCENTRATION,
                "objective": "concentration facts",
                "args": {},
                "inputs": {"portfolio_state": {"from_context": "portfolio_state"}},
                "priority": 1,
            },
            {
                "tool_task_id": "E1",
                "tool_name": RISK_SUMMARIZE_EXPOSURE,
                "objective": "exposure facts",
                "args": {},
                "inputs": {"portfolio_state": {"from_context": "portfolio_state"}},
                "priority": 1,
            },
            {
                "tool_task_id": "F1",
                "tool_name": RISK_FINALIZE_FACTS,
                "objective": "finalize risk facts",
                "args": {},
                "inputs": {
                    "collections": [
                        {"from_tool_task_id": "C1", "output_slot": "concentration_risk_fragment"},
                        {"from_tool_task_id": "E1", "output_slot": "exposure_risk_fragment"},
                    ]
                },
                "priority": 2,
            },
        ],
        "final_output_task_ids": ["F1"],
    }
    plan = validator.validate_payload(
        payload,
        worker_role=RISK_ANALYST,
        worker_task_id="T04",
        available_context_keys={"portfolio_state"},
        allowed_tool_names={item.name for item in definitions},
        read_only=True,
    )
    assert len(plan.tasks[-1].inputs["collections"]) == 2


def test_executor_resolves_many_input_as_list_of_semantic_values() -> None:
    from agent.tool_dag.executor import ToolDagExecutor
    from agent.tool_runtime import UnifiedToolResult

    results = {
        "A1": UnifiedToolResult(
            success=True,
            tool_name="test.a",
            data={"slots": {"output_a": {"source": "a"}}},
        ),
        "B1": UnifiedToolResult(
            success=True,
            tool_name="test.b",
            data={"slots": {"output_b": {"source": "b"}}},
        ),
    }
    resolved = ToolDagExecutor._resolve_ref(
        [
            {"from_tool_task_id": "A1", "output_slot": "output_a"},
            {"from_tool_task_id": "B1", "output_slot": "output_b"},
        ],
        context={},
        results=results,
    )
    assert resolved == [{"source": "a"}, {"source": "b"}]


def test_real_w01_planner_uses_one_llm_stage_and_can_plan_finalizer() -> None:
    from agent.tool_dag.planner import WorkerToolDagPlanner

    class FakeProvider:
        pass

    definitions = build_evidence_tool_definitions(FakeProvider())
    registry = ToolRegistry(definitions)
    directory = WorkerToolDirectory(registry)
    validator = ToolDagValidator(registry, directory)

    class FakeLLM:
        def __init__(self) -> None:
            self.stages: list[str] = []
            self.user_messages: list[str] = []

        def generate_json(self, **kwargs):
            self.stages.append(kwargs["stage"])
            self.user_messages.append(str(kwargs["messages"][-1]["content"]))
            payload = {
                "tasks": [
                    {
                        "tool_task_id": "N1",
                        "tool_name": EVIDENCE_SEARCH_NEWS_TOOL,
                        "objective": "search news",
                        "args": {},
                        "inputs": {"object_refs": {"from_context": "authoritative_entity_refs"}},
                        "priority": 1,
                    },
                    {
                        "tool_task_id": "R1",
                        "tool_name": EVIDENCE_SEARCH_RAG_TOOL,
                        "objective": "search rag",
                        "args": {"query": "贵州茅台"},
                        "inputs": {"object_refs": {"from_context": "authoritative_entity_refs"}},
                        "priority": 1,
                    },
                    {
                        "tool_task_id": "F1",
                        "tool_name": EVIDENCE_FINALIZE_COLLECTION_TOOL,
                        "objective": "finalize evidence",
                        "args": {},
                        "inputs": {
                            "collections": [
                                {"from_tool_task_id": "N1", "output_slot": "news_evidence"},
                                {"from_tool_task_id": "R1", "output_slot": "rag_evidence"},
                            ],
                            "required_object_refs": {"from_context": "authoritative_entity_refs"},
                        },
                        "priority": 2,
                    },
                ],
                "final_output_task_ids": ["F1"],
            }
            kwargs["validator"](payload)
            return payload

    llm = FakeLLM()
    planner = WorkerToolDagPlanner(llm_service=llm, directory=directory, validator=validator)
    plan = planner.plan(
        worker_task_id="T01",
        worker_role=EVIDENCE_COLLECTOR,
        worker_objective="分析贵州茅台并收集证据",
        boundary_id="external_evidence.research",
        worker_prompt="收集外部证据",
        available_context={"authoritative_entity_refs": [{"node_id": "cn:security:sse:600519"}]},
        required_output_keys=[
            "results",
            "record_count",
            "source_count",
            "deduplication",
            "coverage",
            "validated_evidence_collection",
        ],
        completion_criteria=["schema_valid"],
        allowed_tool_names=[item.name for item in definitions],
        run_id="run-v2301",
        read_only=True,
    )
    assert llm.stages == ["worker_private_tool_dag_planner"]
    assert any(EVIDENCE_FINALIZE_COLLECTION_TOOL in message for message in llm.user_messages)
    assert [task.tool_name for task in plan.tasks] == [
        EVIDENCE_SEARCH_NEWS_TOOL,
        EVIDENCE_SEARCH_RAG_TOOL,
        EVIDENCE_FINALIZE_COLLECTION_TOOL,
    ]


def test_real_risk_fragments_roundtrip_into_finalizer() -> None:
    definitions = build_risk_tool_definitions()
    by_name = {item.name: item for item in definitions}
    portfolio_state = {
        "positions": [
            {"stock_code": "600519", "market_value": 600.0, "industry": "白酒", "market": "SSE"},
            {"stock_code": "000001", "market_value": 400.0, "industry": "银行", "market": "SZSE"},
        ],
        "portfolio_totals": {"total_assets": 1200.0, "cash": 200.0},
    }

    concentration_raw = by_name[RISK_CALCULATE_CONCENTRATION].execution_handler(
        {"portfolio_state": portfolio_state}, {}
    )
    exposure_raw = by_name[RISK_SUMMARIZE_EXPOSURE].execution_handler(
        {"portfolio_state": portfolio_state}, {}
    )
    fragments = [
        concentration_raw["data"]["risk_fact_fragment"],
        exposure_raw["data"]["risk_fact_fragment"],
    ]
    final = by_name[RISK_FINALIZE_FACTS].execution_handler({"collections": fragments}, {})
    assert final["success"] is True
    assert final["data"]["source_tool_count"] == 2
    assert {item["fact_type"] for item in final["data"]["risk_facts"]} == {"concentration", "exposure"}
