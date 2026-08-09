from __future__ import annotations

from types import SimpleNamespace

from agent.collaboration.worker_directory import PORTFOLIO_ANALYST
from agent.collaboration.workers.internal_system import run_internal_system
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.tool_dag.planner import WorkerToolDagPlanner
from agent.tool_dag.validation import ToolDagValidator
from agent.tool_runtime import (
    ToolDefinition,
    ToolInputContract,
    ToolOutputContract,
    ToolRegistry,
)
from agent.tool_runtime.contracts import OP_READ, TOOL_VISIBILITY_WORKER_PRIVATE
from agent.worker_tools.internal_system import (
    INTERNAL_ENTITY_RESOLVE_RANKED_SECURITY,
    INTERNAL_PREDICTION_GET_STOCK,
    INTERNAL_RANKING_GET_LATEST,
    build_internal_system_tool_definitions,
)
from agent.worker_tools.registry import WorkerToolDirectory


def _desc(name: str) -> str:
    return (
        f"Function: {name}.\n"
        "Applies when: the Worker needs this private capability.\n"
        "Not for: unrelated work.\n"
        "Preconditions: required inputs only.\n"
        "Main inputs: declared slots.\n"
        "Main outputs: declared slots.\n"
        "Side effects: None; read-only."
    )


def _tool(name: str, required: list[str], produced: list[str]) -> ToolDefinition:
    props = {slot: {"type": "object"} for slot in required}
    if "security_node_id" in required:
        props["security_node_id"] = {"type": "string"}
    return ToolDefinition(
        name=name,
        display_name=name,
        description=_desc(name),
        input_schema={"type": "object", "properties": props, "required": required},
        output_schema={"type": "object", "required_data_keys": []},
        execution_handler=lambda args, context: {"success": True, "data": {}},
        produced_outputs=produced,
        input_contracts=[
            ToolInputContract(slot_id=slot, required=True)
            for slot in required
        ],
        output_contracts=[
            ToolOutputContract(slot_id=slot, source_path="data")
            for slot in produced
        ],
        operation_type=OP_READ,
        allowed_agent_types=[PORTFOLIO_ANALYST],
        visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
    )


def test_private_tool_catalog_does_not_prebind_tool_dependencies() -> None:
    directory = WorkerToolDirectory(ToolRegistry([
        _tool("ranking", [], ["market_ranking_signals"]),
        _tool("resolve", ["market_ranking_signals"], ["security_node_id", "selected_entity_ref"]),
        _tool("prediction", ["security_node_id"], ["entity_model_signals"]),
    ]))

    assert directory.candidate_tool_names(PORTFOLIO_ANALYST) == [
        "ranking", "resolve", "prediction"
    ]


def test_w02_private_planner_builds_ranking_resolve_prediction_dag() -> None:
    directory = WorkerToolDirectory(ToolRegistry([
        _tool("ranking", [], ["market_ranking_signals"]),
        _tool("resolve", ["market_ranking_signals"], ["security_node_id", "selected_entity_ref"]),
        _tool("prediction", ["security_node_id"], ["entity_model_signals"]),
    ]))
    validator = ToolDagValidator(directory.registry, directory)

    class FakeLLM:
        def __init__(self) -> None:
            self.stages: list[str] = []

        def generate_json(self, **kwargs):
            self.stages.append(kwargs["stage"])
            if kwargs["stage"] == "worker_tool_candidate_selection":
                payload = {
                    "candidate_tool_ids": ["ranking", "resolve", "prediction"],
                    "selection_reason": "ranking discovers the target, resolve creates authoritative identity, prediction consumes it",
                }
            else:
                payload = {
                    "tasks": [
                        {
                            "tool_task_id": "P01",
                            "tool_name": "ranking",
                            "objective": "读取模型排名",
                            "args": {},
                            "inputs": {},
                            "priority": 1,
                        },
                        {
                            "tool_task_id": "P02",
                            "tool_name": "resolve",
                            "objective": "把排名第一标的解析为权威实体",
                            "args": {},
                            "inputs": {"market_ranking_signals": {"from_tool_task_id": "P01", "output_slot": "market_ranking_signals"}},
                            "priority": 2,
                        },
                        {
                            "tool_task_id": "P03",
                            "tool_name": "prediction",
                            "objective": "读取已解析标的模型信号",
                            "args": {},
                            "inputs": {"security_node_id": {"from_tool_task_id": "P02", "output_slot": "security_node_id"}},
                            "priority": 3,
                        },
                    ],
                    "final_output_task_ids": ["P01", "P03"],
                }
            kwargs["validator"](payload)
            return payload

    llm = FakeLLM()
    planner = WorkerToolDagPlanner(llm_service=llm, directory=directory, validator=validator)
    plan = planner.plan(
        worker_task_id="T01",
        worker_role=PORTFOLIO_ANALYST,
        worker_objective="确定模型排名第一的股票并提供模型信号",
        boundary_id="internal_fact.retrieval",
        worker_prompt="自主规划私有Tool DAG",
        available_context={"top_k": 1},
        required_output_keys=["market_ranking_signals", "entity_model_signals"],
        completion_criteria=["schema_valid"],
        allowed_tool_names=["ranking", "resolve", "prediction"],
        run_id="run",
        read_only=True,
    )
    assert llm.stages == ["worker_private_tool_dag_planner"]
    assert [task.tool_name for task in plan.tasks] == ["ranking", "resolve", "prediction"]
    assert plan.tasks[1].inputs["market_ranking_signals"]["from_tool_task_id"] == "P01"
    assert plan.tasks[2].inputs["security_node_id"]["from_tool_task_id"] == "P02"


def test_w02_no_graphref_reaches_private_tool_runtime_instead_of_need_context() -> None:
    class FakeDagRuntime:
        def __init__(self) -> None:
            self.called = False
            self.kwargs = {}

        def run(self, **kwargs):
            self.called = True
            self.kwargs = kwargs
            return SimpleNamespace(
                success=False,
                final_results=[],
                plan=SimpleNamespace(tasks=[]),
            )

    runtime = FakeDagRuntime()
    task = GraphAgentTask(
        task_id="T01",
        run_id="run",
        session_id="session",
        worker_id="W02",
        assigned_agent=PORTFOLIO_ANALYST,
        objective="确定模型排名第一的股票并提供模型信号",
        user_id="u",
        boundary_id="internal_fact.retrieval",
        contracts=[{
            "contract_id": "T01-C01",
            "promised_outputs": [
                {"slot_id": "market_ranking_signals"},
                {"slot_id": "entity_model_signals"},
            ],
            "acceptance_rule_ids": ["schema_valid"],
        }],
        expected_output_slots=["market_ranking_signals", "entity_model_signals"],
        focus_refs=[],
        context_refs=[],
    )
    result = run_internal_system(
        runtime,
        task,
        output_dir="outputs",
        db_path=None,
        default_top_k=10,
        worker_prompt="自主规划",
        allowed_tool_names=[INTERNAL_RANKING_GET_LATEST, INTERNAL_ENTITY_RESOLVE_RANKED_SECURITY, INTERNAL_PREDICTION_GET_STOCK],
    )
    assert runtime.called is True
    assert "security_node_id" not in runtime.kwargs["available_context"]
    assert result.status == ResultStatus.FAILED
    assert not result.missing_items
    assert result.error["code"] == "internal_capability_tool_dag_failed"


def test_real_w02_private_catalog_declares_rank_to_identity_bridge() -> None:
    class FakeIdentity:
        pass

    class FakeProvider:
        identity = FakeIdentity()

        def public_entity_descriptor(self, ref):
            return {}

    definitions = build_internal_system_tool_definitions(FakeProvider())
    directory = WorkerToolDirectory(ToolRegistry(definitions))
    candidates = directory.candidate_tool_names(PORTFOLIO_ANALYST)
    assert INTERNAL_RANKING_GET_LATEST in candidates
    assert INTERNAL_ENTITY_RESOLVE_RANKED_SECURITY in candidates
    assert INTERNAL_PREDICTION_GET_STOCK in candidates
    resolver = directory.registry.get(INTERNAL_ENTITY_RESOLVE_RANKED_SECURITY)
    assert [item.slot_id for item in resolver.input_contracts if item.required] == [
        "market_ranking_signals"
    ]
    assert "security_node_id" in [item.slot_id for item in resolver.output_contracts]
