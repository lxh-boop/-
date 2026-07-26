"""End-to-end proof for the hard-cut Main-to-Worker execution chain."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.dag_runtime import run_worker_dag
from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.result_assembler import assemble_main_result
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.worker_tools import (
    DIAGNOSTIC_GRAPH_CONNECTIVITY_TOOL,
    build_worker_tool_directory,
    build_worker_tool_registry,
)


class ChainLLM:
    settings = SimpleNamespace()
    profile_id = "test"
    config_hash = "test"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_json(
        self,
        *,
        stage: str,
        messages: list[dict],
        validator=None,
        **_: object,
    ) -> dict:
        self.calls.append({"stage": stage, "messages": messages})
        if stage == "graph_coordinator_planner":
            payload = {
                "tasks": [
                    {
                        "task_id": "diagnostic",
                        "capability_id": (
                            "system.check_graph_connectivity"
                        ),
                        "objective": "check graph connectivity",
                        "dependency_task_ids": [],
                        "required_outputs": [
                            "diagnostic_analysis"
                        ],
                    },
                    {
                        "task_id": "report",
                        "capability_id": "report.write",
                        "objective": "write the final report",
                        "dependency_task_ids": ["diagnostic"],
                        "required_outputs": ["report_draft"],
                    },
                ]
            }
        else:
            payload = {
                "steps": [
                    {
                        "step_id": "connectivity",
                        "tool_name": (
                            DIAGNOSTIC_GRAPH_CONNECTIVITY_TOOL
                        ),
                        "objective": "check graph connectivity",
                        "dependency_step_ids": [],
                        "required_outputs": [
                            "diagnostic_analysis"
                        ],
                    }
                ]
            }
        if validator:
            validator(payload)
        return json.loads(json.dumps(payload))

    def generate_text(self, **_: object) -> str:
        return "The financial graph is available."


def test_main_capability_plan_executes_worker_private_tool_chain(
    tmp_path,
) -> None:
    llm = ChainLLM()
    backend = SimpleNamespace(
        check_connectivity=Mock(
            return_value={
                "success": True,
                "status": "ok",
                "graph_id": "financial_graph",
            }
        )
    )
    registry = build_worker_tool_registry(
        evidence_backend=backend,
        portfolio_backend=backend,
        risk_backend=backend,
        diagnostic_backend=backend,
        impact_backend=None,
    )
    directory = AgentDirectory()
    tasks, plan_meta = CoordinatorPlanner(
        directory,
        llm_service=llm,
    ).plan(
        query="Is the financial graph available?",
        request_mode="analysis",
        session_id="session-1",
        run_id="run-1",
        user_id="user-1",
        focus_refs=[],
        context_refs=[],
        memory_summary="",
        language="en",
    )
    specialist = SpecialistRuntime(
        llm_service=llm,
        worker_tool_directory=build_worker_tool_directory(registry),
    )

    results, batches, timeline = run_worker_dag(
        tasks,
        specialist=specialist,
        query="Is the financial graph available?",
        output_dir=tmp_path,
        db_path=None,
        default_top_k=5,
        language="en",
        execution_context={},
    )
    public = assemble_main_result(
        tasks=tasks,
        results=results,
        batches=batches,
        timeline=timeline,
        directory=directory,
        language="en",
        question="",
        request_id="",
        graph_id="financial_graph",
        focus_refs=[],
        resolution_audit={},
        plan_meta=plan_meta,
    )

    assert public["success"] is True
    assert public["execution_status"] == "completed"
    assert public["answer"] == "The financial graph is available."
    assert [task.capability_id for task in tasks] == [
        "system.check_graph_connectivity",
        "report.write",
    ]
    assert backend.check_connectivity.call_count == 1
    main_prompt = json.dumps(llm.calls[0]["messages"])
    assert DIAGNOSTIC_GRAPH_CONNECTIVITY_TOOL not in main_prompt
    assert [call["stage"] for call in llm.calls] == [
        "graph_coordinator_planner",
        "worker_private_tool_planner",
    ]
