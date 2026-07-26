"""Worker-to-Main context requests, memory lookup, and DAG resume."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent.collaboration.agent_directory import (
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    RISK_ANALYST,
    AgentDirectory,
)
from agent.collaboration.context_handoff import MainContextHandoff
from agent.collaboration.coordinator import AgentCollaborationCoordinator
from agent.collaboration.models import (
    ContextRequestCategory,
    GraphAgentTask,
    GraphWorkerResult,
    MissingContextItem,
    ResultStatus,
    WorkerContextRequest,
)
from agent.collaboration.session_memory import SessionMemoryStore
from agent.graph.contracts import GraphNodeKind, GraphRef


class ContextLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def generate_json(self, *, validator=None, **_: object):
        self.calls += 1
        if validator:
            validator(self.payload)
        return dict(self.payload)


def _request() -> WorkerContextRequest:
    return WorkerContextRequest(
        source_task_id="risk",
        source_capability_id="risk.analyze",
        requirements=[
            MissingContextItem(
                key="account_scope",
                description="需要确定要分析的模拟盘账户",
                expected_format="账户名称",
                category=ContextRequestCategory.MEMORY_LOOKUP_REQUIRED,
                value_schema={"type": "string"},
            )
        ],
    )


def test_main_uses_confirmed_memory_before_asking_user(tmp_path) -> None:
    memory = SessionMemoryStore(output_dir=tmp_path)
    memory.put(
        session_id="session-1",
        key="account_scope",
        value="default",
        source_type="user_clarification",
        confirmed=True,
        confidence=1.0,
    )
    handoff = MainContextHandoff(
        memory=memory,
        llm_service=ContextLLM({}),
    )

    resolved, unresolved = handoff.memory_values(
        "session-1",
        [_request()],
    )

    assert resolved == {"account_scope": "default"}
    assert unresolved == []


def test_main_resolves_and_remembers_user_clarification(tmp_path) -> None:
    memory = SessionMemoryStore(output_dir=tmp_path)
    llm = ContextLLM(
        {
            "action": "provide_context",
            "values": {"account_scope": "default"},
            "reason": "answers requested account",
            "confidence": 0.99,
        }
    )
    handoff = MainContextHandoff(memory=memory, llm_service=llm)
    request = _request()

    decision = handoff.resolve_user_turn(
        query="默认账户",
        requests=[request],
        memory_summary="",
        language="zh",
    )
    handoff.remember_clarification(
        session_id="session-1",
        request_id=request.request_id,
        values=decision.values,
    )

    item = memory.get("session-1", "account_scope")
    assert decision.action == "provide_context"
    assert item is not None
    assert item.value == "default"
    assert item.confirmed is True
    assert item.source_type == "user_clarification"


def test_secret_requirement_is_not_rendered_as_chat_request(tmp_path) -> None:
    handoff = MainContextHandoff(
        memory=SessionMemoryStore(output_dir=tmp_path),
        llm_service=ContextLLM({}),
    )
    requirement = MissingContextItem(
        key="api_key",
        description="请提供内部 API Key",
        category=ContextRequestCategory.SYSTEM_CONFIG_REQUIRED,
        sensitivity="secret",
        allow_memory_lookup=False,
    )

    question = handoff.clarification_question(
        [requirement],
        language="zh",
    )

    assert "应用设置" in question
    assert "不要在对话中发送" in question
    assert "API Key" not in question


class PausingSpecialist:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.portfolio_ref = GraphRef(
            graph_id="financial_graph",
            node_id="portfolio:user-1",
            node_kind=GraphNodeKind.OBJECT,
            role="portfolio",
        )

    def run(
        self,
        task: GraphAgentTask,
        *,
        execution_context: dict,
        **_: object,
    ) -> GraphWorkerResult:
        self.calls.append(task.task_id)
        if task.capability_id == "portfolio.load_snapshot":
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.COMPLETED,
                focus_refs=[self.portfolio_ref],
                summary="portfolio ready",
            )
        if task.capability_id == "risk.analyze":
            if not dict(
                execution_context.get("resolved_context") or {}
            ).get("account_scope"):
                missing = MissingContextItem(
                    key="account_scope",
                    description="需要确定要分析的模拟盘账户",
                    expected_format="账户名称",
                    category=(
                        ContextRequestCategory.MEMORY_LOOKUP_REQUIRED
                    ),
                    value_schema={"type": "string"},
                )
                return GraphWorkerResult(
                    task_id=task.task_id,
                    agent_id=task.assigned_agent,
                    status=ResultStatus.NEED_CONTEXT,
                    summary="account missing",
                    missing_items=[missing],
                    context_request=WorkerContextRequest(
                        source_task_id=task.task_id,
                        source_capability_id=task.capability_id,
                        requirements=[missing],
                        attempt=task.attempt,
                    ),
                )
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.COMPLETED,
                summary="risk ready",
            )
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.COMPLETED,
            summary="report ready",
        )


def _task(
    task_id: str,
    capability_id: str,
    assigned_agent: str,
    dependencies=(),
) -> GraphAgentTask:
    binding = AgentDirectory().resolve(capability_id)
    return GraphAgentTask(
        task_id=task_id,
        run_id="run-1",
        session_id="session-1",
        assigned_agent=assigned_agent,
        objective=f"objective {task_id}",
        task_type=binding.task_type,
        user_id="user-1",
        capability_id=capability_id,
        dependency_task_ids=list(dependencies),
    )


def _coordinator(tmp_path: Path) -> AgentCollaborationCoordinator:
    coordinator = object.__new__(AgentCollaborationCoordinator)
    coordinator.output_dir = tmp_path
    coordinator.db_path = None
    coordinator.memory = SessionMemoryStore(output_dir=tmp_path)
    coordinator.llm_service = ContextLLM(
        {
            "action": "provide_context",
            "values": {"account_scope": "default"},
            "reason": "clarification",
            "confidence": 1.0,
        }
    )
    coordinator.context_handoff = MainContextHandoff(
        memory=coordinator.memory,
        llm_service=coordinator.llm_service,
    )
    coordinator.directory = AgentDirectory()
    coordinator.specialist = PausingSpecialist()
    coordinator.store = SimpleNamespace(graph_id="financial_graph")
    return coordinator


def test_main_persists_and_resumes_only_waiting_task_and_descendants(
    tmp_path,
) -> None:
    coordinator = _coordinator(tmp_path)
    tasks = [
        _task(
            "portfolio",
            "portfolio.load_snapshot",
            PORTFOLIO_ANALYST,
        ),
        _task(
            "risk",
            "risk.analyze",
            RISK_ANALYST,
            ("portfolio",),
        ),
        _task(
            "report",
            "report.write",
            REPORT_WRITER,
            ("risk",),
        ),
    ]

    first = coordinator._execute_plan(
        tasks=tasks,
        query="分析我的组合风险",
        user_id="user-1",
        session_id="session-1",
        run_id="run-1",
        default_top_k=5,
        language="zh",
        execution_context={},
        focus_refs=[],
        resolution_audit={},
        plan_meta={"selection_basis": "worker_capability"},
    )

    assert first["execution_status"] == "waiting_context"
    assert first["need_clarification"] is True
    assert coordinator.memory.stats("session-1")[
        "waiting_task_count"
    ] == 1
    assert coordinator.specialist.calls.count("portfolio") == 1

    resumed = coordinator._resume_waiting_context(
        query="默认账户",
        user_id="user-1",
        session_id="session-1",
        run_id="run-2",
        language="zh",
        default_top_k=5,
        execution_context={},
        memory_summary="",
    )

    assert resumed is not None
    assert resumed["execution_status"] == "completed"
    assert resumed["context_resume"]["status"] == "resumed"
    assert coordinator.specialist.calls.count("portfolio") == 1
    assert coordinator.specialist.calls.count("risk") == 2
    assert coordinator.specialist.calls.count("report") == 1
    assert coordinator.memory.stats("session-1")[
        "waiting_task_count"
    ] == 0
