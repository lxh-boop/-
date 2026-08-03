from __future__ import annotations

from types import SimpleNamespace

from agent.collaboration.agent_directory import EVIDENCE_COLLECTOR
from agent.collaboration.coordinator import AgentCollaborationCoordinator
from agent.collaboration.models import GraphAgentTask, GraphWorkerResult, ResultStatus
from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.report_validation import build_report_policy, validate_report_output
from agent.tool_dag import (
    ToolDagExecutionResult,
    ToolDagPlan,
    ToolDagTask,
    ToolDagExecutor,
    WorkerToolDagRuntime,
)
from agent.tool_runtime import UnifiedToolResult


class _FailingSpecialist:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, task: GraphAgentTask, **kwargs) -> GraphWorkerResult:
        del kwargs
        self.calls.append(task.task_id)
        if task.task_id != "T01":
            raise AssertionError("downstream worker must not execute after upstream failure")
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.FAILED,
            output_type=task.expected_output_type,
            data=None,
            error={
                "code": "worker_execution_failed",
                "message": "source failed",
                "retryable": True,
            },
            summary="source failed",
        )


def _worker_task(task_id: str, dependency_ids: list[str]) -> GraphAgentTask:
    return GraphAgentTask(
        task_id=task_id,
        run_id="run-v16",
        session_id="session-v16",
        worker_id="W01" if task_id == "T01" else "W09",
        assigned_agent=EVIDENCE_COLLECTOR if task_id == "T01" else "ENTITY_ANALYST",
        objective=task_id,
        task_type="collect_external_evidence" if task_id == "T01" else "analyze_financial_entities",
        expected_output_type="EvidenceCollectionResult" if task_id == "T01" else "EntityAnalysisResult",
        dependency_task_ids=dependency_ids,
        user_id="u",
    )


def test_worker_failure_blocks_downstream_and_reports_for_replan(tmp_path) -> None:
    coordinator = object.__new__(AgentCollaborationCoordinator)
    coordinator.runtime_services = None
    coordinator.specialist = _FailingSpecialist()
    tasks = [_worker_task("T01", []), _worker_task("T02", ["T01"])]

    results, batches, timeline = coordinator._run_dag(
        tasks,
        query="分析",
        output_dir=tmp_path,
        db_path=None,
        default_top_k=10,
        language="zh",
        execution_context={},
    )

    assert coordinator.specialist.calls == ["T01"]
    assert results["T01"].status == ResultStatus.FAILED
    assert results["T02"].status == ResultStatus.BLOCKED
    assert results["T02"].error["code"] == "upstream_worker_failed"
    observation = coordinator._task_observation(tasks[1], results["T02"])
    assert observation["replan_recommended"] is True
    assert observation["should_freeze"] is False
    assert [row["status"] for row in timeline] == ["failed", "blocked"]
    assert len(batches) == 1


class _PlannerStub:
    def __init__(self) -> None:
        self.replan_records: list[dict] = []

    @staticmethod
    def _goal() -> dict:
        return {
            "goal_summary": "collect evidence",
            "required_output_keys": ["validated_evidence_collection", "results"],
            "completion_criteria": ["finalized"],
        }

    def plan(self, **kwargs) -> ToolDagPlan:
        del kwargs
        return ToolDagPlan(
            worker_task_id="T01",
            worker_role=EVIDENCE_COLLECTOR,
            goal_contract=self._goal(),
            tasks=[
                ToolDagTask("TT1", "news", "news", expected_output_keys=["results"]),
                ToolDagTask("TT2", "rag", "rag", expected_output_keys=["results"]),
                ToolDagTask(
                    "TT3",
                    "finalize",
                    "finalize",
                    inputs={
                        "collections": [
                            {"from_tool_task_id": "TT1"},
                            {"from_tool_task_id": "TT2"},
                        ]
                    },
                    expected_output_keys=["validated_evidence_collection", "results"],
                ),
            ],
            final_output_task_ids=["TT3"],
        )

    def replan(self, **kwargs) -> ToolDagPlan:
        self.replan_records = list(kwargs["node_records"])
        previous = kwargs["previous_plan"]
        frozen = [task for task in previous.tasks if task.tool_task_id in {"TT1", "TT2"}]
        return ToolDagPlan(
            worker_task_id=previous.worker_task_id,
            worker_role=previous.worker_role,
            goal_contract=previous.goal_contract,
            tasks=[
                *frozen,
                ToolDagTask(
                    "TT4",
                    "finalize",
                    "finalize reusable results",
                    inputs={
                        "collections": [
                            {"from_tool_task_id": "TT1"},
                            {"from_tool_task_id": "TT2"},
                        ]
                    },
                    expected_output_keys=["validated_evidence_collection", "results"],
                ),
            ],
            final_output_task_ids=["TT4"],
        )


class _ExecutorStub:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.finalize_count = 0

    def execute(self, tool_name, arguments, **kwargs):
        del arguments, kwargs
        self.calls.append(tool_name)
        if tool_name in {"news", "rag"}:
            return UnifiedToolResult(
                success=True,
                tool_name=tool_name,
                data={"results": [{"source": tool_name}]},
            )
        self.finalize_count += 1
        if self.finalize_count == 1:
            return UnifiedToolResult(
                success=False,
                tool_name=tool_name,
                data={},
                error_type="finalize_contract_error",
                error_message="bad handoff",
                metadata={"failure_kind": "tool_failure", "retryable": True},
            )
        return UnifiedToolResult(
            success=True,
            tool_name=tool_name,
            data={
                "validated_evidence_collection": True,
                "results": [{"records": []}],
                "business_empty": True,
            },
        )


def test_local_tool_replan_uses_one_node_record_shape_and_freezes_successes() -> None:
    planner = _PlannerStub()
    executor_stub = _ExecutorStub()
    runtime = WorkerToolDagRuntime(
        planner=planner,
        executor=ToolDagExecutor(executor_stub, max_parallel=2),
    )
    result = runtime.run(
        worker_task_id="T01",
        worker_role=EVIDENCE_COLLECTOR,
        worker_task_type="collect_external_evidence",
        worker_objective="collect",
        worker_prompt="",
        available_context={},
        required_output_keys=["validated_evidence_collection", "results"],
        completion_criteria=["finalized"],
        allowed_tool_names=["news", "rag", "finalize"],
        execution_context={},
        max_replans=1,
    )

    assert result.success is True
    assert executor_stub.calls.count("news") == 1
    assert executor_stub.calls.count("rag") == 1
    assert executor_stub.calls.count("finalize") == 2
    records = planner.replan_records
    assert {row["status"] for row in records} == {"succeeded", "failed"}
    successful = [row for row in records if row["status"] == "succeeded"]
    failed = [row for row in records if row["status"] == "failed"]
    assert all(row["should_freeze"] and row["reusable"] for row in successful)
    assert all(not row["should_freeze"] and not row["reusable"] for row in failed)
    assert all(isinstance(row["result_summary"], dict) for row in records)


def test_main_planner_compiles_information_contract_fields() -> None:
    planner = CoordinatorPlanner(SimpleNamespace(), llm_service=SimpleNamespace())
    # Use the real directory while avoiding an LLM call.
    from agent.collaboration.agent_directory import AgentDirectory

    planner.directory = AgentDirectory()
    payload = {
        "goal_contract": {"required_information_slots": ["entity_external_evidence"]},
        "planning_state": {"stop_reason": "done"},
        "tasks": [
            {
                "task_id": "T01",
                "worker_id": "W01",
                "task_type": "collect_external_evidence",
                "args": {"collection_goal": "evidence"},
                "inputs": {},
                "input_contract": {
                    "upstream_information_slots": ["authoritative_financial_entities"],
                    "available_context_slots": [],
                },
                "expected_output": {
                    "information_slots": ["entity_external_evidence", "evidence_source_records"]
                },
            }
        ],
    }
    prepared, _ = planner._prepare_payload(
        payload,
        runtime_values={"all_ref_ids": ["cn:security:sse:600519"]},
        authoritative_initial_information_slots={"authoritative_financial_entities"},
    )
    contract = prepared["tasks"][0]["input_contract"]
    assert contract["upstream_information_slots"] == []
    assert contract["available_context_slots"] == ["authoritative_financial_entities"]
    assert prepared["planning_state"]["unmet_information_slots"] == []


def test_report_validator_allows_retry_guidance_and_contextual_entity_prefix() -> None:
    safe_results = [
        {
            "status": "completed",
            "output_type": "EntityAnalysisResult",
            "payload": {
                "entity_catalog": [
                    {
                        "public_code": "600519",
                        "display_label": "贵州茅台",
                        "identity_locked": True,
                    }
                ]
            },
        }
    ]
    policy = build_report_policy("分析贵州茅台", safe_results)
    text = (
        "本报告基于上游专业分析结果，聚焦于贵州茅台（600519）的实体分析。\n\n"
        "建议在数据链路恢复后重新发起对贵州茅台（600519）的实体分析请求。"
    )
    checked = validate_report_output(text, policy)
    assert checked.valid is True
