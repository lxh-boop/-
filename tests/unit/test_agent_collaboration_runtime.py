from __future__ import annotations

import json

import pytest

from agent.collaboration.agent_directory import (
    AgentDirectory,
    EVIDENCE_RESEARCHER,
    GRAPH_IMPACT_ANALYST,
    PORTFOLIO_ANALYST,
    REPORT_COMPOSER,
)
from agent.collaboration.capability_contracts import (
    AgentCapabilityCard,
    WorkerCapability,
)
from agent.collaboration.entry_decision import (
    MainEntryDecisionPlanner,
    RequestMode,
)
from agent.collaboration.integration import route_unified_agent_request
from agent.collaboration.planner import (
    CoordinatorPlanner,
    CoordinatorPlanningError,
)
from agent.dag_validation import DagNode, DagValidationError, DagValidator


class FakeLLMService:
    is_available = True
    profile_id = "test-profile"
    config_hash = "test-config-hash"
    settings = object()

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls = []
        self.messages = []

    def generate_json(
        self,
        *,
        stage,
        messages,
        max_output_tokens,
        validator=None,
        operation="",
    ):
        self.calls.append(("json", stage, operation))
        self.messages = list(messages)
        payload = self.responses.get(stage)
        if payload is None:
            raise AssertionError(f"missing_fake_response:{stage}")
        if validator:
            validator(payload)
        return payload


def _row(
    task_id: str,
    capability_id: str,
    *,
    dependencies=(),
    outputs=(),
) -> dict:
    return {
        "task_id": task_id,
        "capability_id": capability_id,
        "objective": f"完成任务 {task_id} 的业务目标",
        "dependency_task_ids": list(dependencies),
        "required_outputs": list(outputs),
        "constraints": [],
        "priority": 1,
    }


def _plan(rows: list[dict], *, mode: str = "analysis"):
    service = FakeLLMService(
        {"graph_coordinator_planner": {"tasks": rows}}
    )
    tasks, metadata = CoordinatorPlanner(
        AgentDirectory(),
        llm_service=service,
    ).plan(
        query="分析新闻对当前持仓的影响",
        request_mode=mode,
        session_id="session-1",
        run_id="run-1",
        user_id="user-1",
        focus_refs=[],
        context_refs=[],
        memory_summary="",
    )
    return tasks, metadata, service


def _impact_plan() -> list[dict]:
    return [
        _row(
            "evidence",
            "evidence.research",
            outputs=("evidence_result",),
        ),
        _row(
            "portfolio",
            "portfolio.analysis",
            outputs=("portfolio_snapshot",),
        ),
        _row(
            "impact",
            "graph.impact_analysis",
            dependencies=("evidence", "portfolio"),
            outputs=("impact_paths",),
        ),
        _row(
            "report",
            "report.compose",
            dependencies=("impact",),
            outputs=("report_draft",),
        ),
    ]


def test_route_facade_is_non_semantic_and_constant() -> None:
    routed = route_unified_agent_request("分析 600519")

    assert routed.intent == "financial_graph_agent"
    assert routed.execution_route == "single_main_agent_graph_entry"
    assert routed.parameters == {}
    assert routed.decomposition["task_plan"]["tool_visibility"] == "none"


def test_entry_decision_uses_protocol_without_llm() -> None:
    service = FakeLLMService()
    decision = MainEntryDecisionPlanner(llm_service=service).decide(
        query="确认",
        memory_summary="",
        execution_context={
            "conversation_state": {"relation_type": "confirmation"}
        },
        language="zh",
    )

    assert decision.mode == RequestMode.CONFIRM
    assert decision.source == "hard_protocol_state"
    assert service.calls == []


def test_entry_decision_business_semantics_use_run_service() -> None:
    service = FakeLLMService(
        {
            "main_agent_single_entry": {
                "mode": "analysis",
                "reason": "read",
                "reply_language": "",
                "confidence": 0.9,
            }
        }
    )
    decision = MainEntryDecisionPlanner(llm_service=service).decide(
        query="分析组合风险",
        memory_summary="",
        execution_context={},
        language="zh",
    )

    assert decision.mode == RequestMode.ANALYSIS
    assert service.calls == [
        ("json", "main_agent_single_entry", "request_mode_decision")
    ]


def test_main_plans_capabilities_then_runtime_resolves_workers() -> None:
    tasks, metadata, service = _plan(_impact_plan())

    assert [task.capability_id for task in tasks] == [
        "evidence.research",
        "portfolio.analysis",
        "graph.impact_analysis",
        "report.compose",
    ]
    assert [task.assigned_agent for task in tasks] == [
        EVIDENCE_RESEARCHER,
        PORTFOLIO_ANALYST,
        GRAPH_IMPACT_ANALYST,
        REPORT_COMPOSER,
    ]
    assert metadata["selection_basis"] == "worker_capability"
    prompt_payload = json.loads(service.messages[1]["content"])
    encoded_catalog = json.dumps(
        prompt_payload["worker_capability_catalog"],
        ensure_ascii=False,
    )
    assert '"agent_id"' not in encoded_catalog
    assert '"task_type"' not in encoded_catalog
    assert EVIDENCE_RESEARCHER not in encoded_catalog


def test_worker_cards_have_one_normalized_capability_each() -> None:
    directory = AgentDirectory()
    cards = directory.list_cards()
    capability_ids = [
        capability.capability_id
        for card in cards
        for capability in card.capabilities
    ]

    assert len(cards) == 8
    assert len(capability_ids) == 8
    assert all(len(card.capabilities) == 1 for card in cards)
    assert len(set(capability_ids)) == len(capability_ids)


def test_main_plan_rejects_identity_fields_and_missing_outputs() -> None:
    identity_rows = _impact_plan()
    identity_rows[0]["assigned_agent"] = EVIDENCE_RESEARCHER
    with pytest.raises(
        CoordinatorPlanningError,
        match="coordinator_plan_exposes_worker_identity",
    ):
        _plan(identity_rows)

    dependency_rows = [
        row for row in _impact_plan() if row["task_id"] != "portfolio"
    ]
    dependency_rows[1]["dependency_task_ids"] = ["evidence"]
    with pytest.raises(
        CoordinatorPlanningError,
        match="capability_dependency_output_missing:impact:portfolio_snapshot",
    ):
        _plan(dependency_rows)


def test_proposal_mode_requires_and_resolves_proposal_capability() -> None:
    missing_proposal = [
        _row("portfolio", "portfolio.analysis"),
        _row("report", "report.compose", dependencies=("portfolio",)),
    ]
    with pytest.raises(
        CoordinatorPlanningError,
        match="request_mode_output_missing:proposal",
    ):
        _plan(missing_proposal, mode="proposal")

    tasks, metadata, _ = _plan(
        [
            _row("portfolio", "portfolio.analysis"),
            _row(
                "proposal",
                "strategy.proposal",
                dependencies=("portfolio",),
                outputs=("proposal",),
            ),
            _row(
                "report",
                "report.compose",
                dependencies=("proposal",),
                outputs=("report_draft",),
            ),
        ],
        mode="proposal",
    )
    assert [task.capability_id for task in tasks] == [
        "portfolio.analysis",
        "strategy.proposal",
        "report.compose",
    ]
    assert metadata["required_plan_outputs"] == ["proposal", "report_draft"]


def test_portfolio_risk_uses_snapshot_output_dependency() -> None:
    tasks, _, _ = _plan(
        [
            _row(
                "portfolio",
                "portfolio.analysis",
                outputs=("portfolio_snapshot",),
            ),
            _row(
                "risk",
                "portfolio.risk_analysis",
                dependencies=("portfolio",),
                outputs=("risk_analysis",),
            ),
            _row(
                "report",
                "report.compose",
                dependencies=("risk",),
                outputs=("report_draft",),
            ),
        ]
    )

    assert [task.capability_id for task in tasks] == [
        "portfolio.analysis",
        "portfolio.risk_analysis",
        "report.compose",
    ]


def test_worker_rename_does_not_change_public_capability_contract() -> None:
    capability = WorkerCapability(
        capability_id="custom.analysis",
        task_type="private_task",
        description="执行自定义分析。",
        when_to_use="需要自定义分析时使用。",
        produced_output_types=["analysis_result"],
    )

    def directory(worker_id: str) -> AgentDirectory:
        return AgentDirectory(
            cards=[
                AgentCapabilityCard(
                    agent_id=worker_id,
                    role=worker_id,
                    description="自定义分析能力。",
                    capabilities=[capability],
                )
            ],
            required_outputs_by_mode={"analysis": ("analysis_result",)},
        )

    original = directory("ORIGINAL_WORKER")
    renamed = directory("RENAMED_WORKER")
    assert original.safe_catalog() == renamed.safe_catalog()
    assert original.resolve("custom.analysis").worker_id == "ORIGINAL_WORKER"
    assert renamed.resolve("custom.analysis").worker_id == "RENAMED_WORKER"


def test_shared_dag_validator_orders_and_rejects_cycles() -> None:
    result = DagValidator().validate(
        [
            DagNode.from_values("read"),
            DagNode.from_values("analyze", ("read",)),
            DagNode.from_values("report", ("analyze",), terminal=True),
        ],
        require_terminal_coverage=True,
    )
    assert result.ordered_node_ids == ("read", "analyze", "report")

    with pytest.raises(DagValidationError, match="dag_dependency_cycle"):
        DagValidator().validate(
            [
                DagNode.from_values("a", ("b",)),
                DagNode.from_values("b", ("a",)),
            ]
        )
