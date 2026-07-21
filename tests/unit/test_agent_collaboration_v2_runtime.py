from __future__ import annotations

from pathlib import Path

import pytest

from agent.collaboration_v2.agent_directory import AgentDirectory
from agent.collaboration_v2.coordinator import AgentCollaborationCoordinator
from agent.collaboration_v2.entry_decision import MainEntryDecisionPlanner, RequestMode
from agent.collaboration_v2.integration import route_unified_agent_request
from agent.collaboration_v2.models import AgentResult, AgentTask, ResultStatus, TaskStatus
from agent.collaboration_v2.planner import CoordinatorPlanner
from agent.collaboration_v2.requirements import RequirementEngine


class FakeLLMService:
    is_available = True
    profile_id = "test-profile"
    config_hash = "test-config-hash"
    settings = object()

    def __init__(self, responses=None, error_stage: str = ""):
        self.responses = dict(responses or {})
        self.error_stage = error_stage
        self.calls = []

    def generate_json(self, *, stage, messages, max_output_tokens, validator=None, operation=""):
        self.calls.append(("json", stage, operation))
        if stage == self.error_stage:
            raise RuntimeError(f"forced:{stage}")
        payload = self.responses.get(stage)
        if payload is None:
            payload = {"requirements": []}
        if validator:
            validator(payload)
        return payload

    def generate_text(self, *, stage, messages, max_output_tokens, temperature=0.0, operation=""):
        self.calls.append(("text", stage, operation))
        if stage == self.error_stage:
            raise RuntimeError(f"forced:{stage}")
        return str(self.responses.get(stage) or "统一报告")


def test_route_facade_is_non_semantic_and_constant():
    routed = route_unified_agent_request("分析 600519")
    assert routed.intent == "agent_collaboration_v2"
    assert routed.execution_route == "single_main_agent_entry"
    assert routed.parameters == {}
    assert routed.decomposition["diagnostics"]["legacy_router_called"] is False


def test_entry_decision_uses_protocol_for_confirmation_without_llm():
    service = FakeLLMService()
    planner = MainEntryDecisionPlanner(llm_service=service)
    decision = planner.decide(
        query="确认",
        memory_summary="",
        execution_context={"conversation_state": {"relation_type": "confirmation"}},
        language="zh",
    )
    assert decision.mode == RequestMode.CONFIRM
    assert decision.source == "hard_protocol_state"
    assert service.calls == []


def test_entry_decision_business_semantics_use_run_service():
    service = FakeLLMService(
        {"main_agent_single_entry": {"mode": "analysis", "reason": "read", "reply_language": "", "confidence": 0.9}}
    )
    planner = MainEntryDecisionPlanner(llm_service=service)
    decision = planner.decide(
        query="分析组合风险",
        memory_summary="",
        execution_context={},
        language="zh",
    )
    assert decision.mode == RequestMode.ANALYSIS
    assert service.calls == [("json", "main_agent_single_entry", "request_mode_decision")]


def test_proposal_plan_is_llm_generated_and_requires_strategy_guard_and_reporter():
    service = FakeLLMService(
        {
            "coordinator_planner": {
                "tasks": [
                    {
                        "task_id": "portfolio",
                        "assigned_agent": "PORTFOLIO_ANALYST",
                        "objective": "分析当前模拟盘组合与用户目标",
                        "task_type": "analyze_portfolio",
                        "constraints": [],
                        "dependency_task_ids": [],
                        "expected_output_type": "portfolio_analysis",
                        "priority": 1,
                    },
                    {
                        "task_id": "proposal",
                        "assigned_agent": "STRATEGY_GUARD",
                        "objective": "基于标准结果生成待审批的模拟盘预案",
                        "task_type": "build_proposal",
                        "constraints": ["不得 Commit"],
                        "dependency_task_ids": ["portfolio"],
                        "expected_output_type": "proposal",
                        "priority": 2,
                    },
                    {
                        "task_id": "report",
                        "assigned_agent": "REPORT_WRITER",
                        "objective": "汇总预案并明确等待用户审批",
                        "task_type": "write_report",
                        "constraints": [],
                        "dependency_task_ids": ["portfolio", "proposal"],
                        "expected_output_type": "report_draft",
                        "priority": 3,
                    },
                ]
            }
        }
    )
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=service)
    tasks, metadata = planner.plan(
        query="给我一个调仓方案",
        request_mode="proposal",
        session_id="s",
        run_id="r",
        memory_summary="",
    )
    assert [task.assigned_agent for task in tasks] == [
        "PORTFOLIO_ANALYST", "STRATEGY_GUARD", "REPORT_WRITER"
    ]
    assert metadata["fallback_used"] is False
    assert metadata["keyword_business_fallback_used"] is False


def test_requirement_failure_does_not_use_semantic_fallback():
    service = FakeLLMService(error_stage="specialist_requirement")
    engine = RequirementEngine(llm_service=service)
    task = AgentTask(
        task_id="t",
        run_id="r",
        session_id="s",
        assigned_agent="EVIDENCE_RETRIEVER",
        objective="分析股票",
        task_type="analyze_stock_evidence",
        status=TaskStatus.READY,
    )
    with pytest.raises(RuntimeError, match="forced:specialist_requirement"):
        engine.infer(task, auto_context={})


def test_all_collaboration_components_share_same_service_identity(tmp_path: Path):
    service = FakeLLMService(
        {
            "main_agent_single_entry": {"mode": "analysis", "reason": "test", "reply_language": "", "confidence": 1.0},
            "coordinator_planner": {
                "tasks": [
                    {
                        "task_id": "diagnose",
                        "assigned_agent": "SYSTEM_DIAGNOSTIC",
                        "objective": "诊断系统运行状态",
                        "task_type": "diagnose_system",
                        "constraints": [],
                        "dependency_task_ids": [],
                        "expected_output_type": "diagnostic_analysis",
                        "priority": 1,
                    },
                    {
                        "task_id": "report",
                        "assigned_agent": "REPORT_WRITER",
                        "objective": "汇总专业 Agent 标准结果",
                        "task_type": "write_report",
                        "constraints": [],
                        "dependency_task_ids": ["diagnose"],
                        "expected_output_type": "report_draft",
                        "priority": 2,
                    },
                ]
            },
        }
    )
    coordinator = AgentCollaborationCoordinator(
        output_dir=tmp_path,
        db_path=None,
        llm_service=service,
    )
    assert coordinator.llm_service is service
    assert coordinator.entry_planner.llm_service is service
    assert coordinator.planner.llm_service is service
    assert coordinator.reporter.llm_service is service
    assert coordinator.specialist_runtime.llm_service is service
    assert coordinator.specialist_runtime.business_runtime.llm_service is service

    coordinator.specialist_runtime.run = lambda task, **_: AgentResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        summary="完成",
    )
    result = coordinator.execute(
        query="检查系统",
        decomposition={},
        user_id="u",
        default_top_k=10,
        session_id="s",
        run_id="r",
        language="zh",
        execution_context={},
    )
    assert result["success"] is True
    assert result["agent_collaboration_v2"]["llm_runtime"]["single_service_identity"] is True
