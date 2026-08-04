from __future__ import annotations

import inspect
from types import SimpleNamespace

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration import integration as collaboration_integration
from agent.collaboration.completion import runtime_completion_report
from agent.collaboration.coordinator import AgentCollaborationCoordinator
from agent.collaboration.entry_decision import EntityScope, MainEntryDecisionPlanner
from agent.collaboration.models import (
    AccessMode,
    GraphAgentTask,
    GraphWorkerResult,
    ResultStatus,
)
from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.report_validation import build_report_policy
from agent.collaboration.specialist_runtime import _contract_violation_from_chain
from agent.collaboration.worker_contracts import WorkerContractViolation
from agent.collaboration.workers import report_writer, strategy_guard
from agent.graph.contracts import GraphNodeKind, GraphRef

from tests.unit._forward_plan_helpers import decorate_forward_plan


def _ref(task_id: str, output_type: str) -> dict[str, str]:
    return {"from_task_id": task_id, "expected_output_type": output_type}


def test_access_mode_is_only_read_or_write_and_proposal_is_read() -> None:
    directory = AgentDirectory()
    assert {AccessMode.READ.value, AccessMode.WRITE.value} == {item.value for item in AccessMode}
    for worker_id in ("W01", "W02", "W04", "W05", "W06", "W09"):
        card = directory.get(worker_id)
        assert AccessMode.from_value(card.access_mode) == AccessMode.READ
        assert all(AccessMode.from_value(item.access_mode) == AccessMode.READ for item in card.task_contracts)
    assert AccessMode.from_value(directory.get("W08").access_mode) == AccessMode.WRITE
    assert directory.get("W05").can_generate_proposal is True
    assert AccessMode.from_value(directory.get("W05").task_contract("build_proposal").access_mode) == AccessMode.READ


def test_proposal_plan_can_include_ephemeral_risk_analysis_without_write_permission() -> None:
    raw = {
        "goal_contract": {
            "goal_summary": "根据当前组合和风险形成当前 Run 内的待审批方案",
            "desired_output_types": ["ReviewedProposal", "FinalReport"],
            "required_information_slots": [],
            "completion_criteria": ["生成待审批方案并明确尚未执行"],
            "constraints": ["不修改持久化业务状态"],
            "access_mode": "read",
        },
        "tasks": [
            {
                "task_id": "T01",
                "worker_id": "W02",
                "objective": "读取当前权威组合状态",
                "task_type": "query_portfolio_state",
                "args": {},
                "inputs": {},
                "constraints": [],
                "expected_output_type": "PortfolioAnalysisResult",
                "priority": 1,
            },
            {
                "task_id": "T02",
                "worker_id": "W04",
                "objective": "分析当前组合风险并形成风险约束",
                "task_type": "analyze_risk",
                "args": {"risk_question": "评估组合层风险"},
                "inputs": {"portfolio_state": _ref("T01", "PortfolioAnalysisResult")},
                "constraints": [],
                "expected_output_type": "PortfolioRiskResult",
                "priority": 2,
            },
            {
                "task_id": "T03",
                "worker_id": "W05",
                "objective": "形成当前 Run 内的待审批调整方案",
                "task_type": "build_proposal",
                "args": {
                    "change_intent": "根据当前组合和风险形成调整方案",
                    "change_scope": "portfolio_adjustment",
                    "proposal_constraints": ["不得执行"],
                },
                "inputs": {
                    "current_state": _ref("T01", "PortfolioAnalysisResult"),
                    "risk_constraints": _ref("T02", "PortfolioRiskResult"),
                },
                "constraints": [],
                "expected_output_type": "ReviewedProposal",
                "priority": 3,
            },
            {
                "task_id": "T04",
                "worker_id": "W06",
                "objective": "汇总待审批方案",
                "task_type": "write_report",
                "args": {"report_goal": "说明调整方案"},
                "inputs": {
                    "upstream_results": [
                        _ref("T01", "PortfolioAnalysisResult"),
                        _ref("T02", "PortfolioRiskResult"),
                        _ref("T03", "ReviewedProposal"),
                    ]
                },
                "constraints": [],
                "expected_output_type": "FinalReport",
                "priority": 4,
            },
        ],
    }
    plan = decorate_forward_plan(
        raw,
        initial_slots=[
            "user_request", "user_identity", "reply_language",
            "explicit_change_intent", "proposal_permission",
        ],
        goal_slots=[
            "current_portfolio_state", "portfolio_risk_assessment",
            "reviewed_proposal", "user_facing_report",
        ],
    )
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=SimpleNamespace())
    prepared, _ = planner._prepare_payload(
        plan,
        runtime_values={
            "user_id": "cht", "reply_language": "zh", "focus_ref_ids": [],
            "context_ref_ids": [], "all_ref_ids": [], "as_of_time": "", "run_id": "run-v18",
        },
        authoritative_initial_information_slots=set(plan["planning_state"]["initial_available_information_slots"]),
        request_mode="proposal",
    )
    planner._validate_payload(
        prepared,
        request_mode="proposal",
        authoritative_ref_ids=set(),
        authoritative_user_id="cht",
        reply_language="zh",
        authoritative_initial_information_slots=set(plan["planning_state"]["initial_available_information_slots"]),
    )
    assert prepared["goal_contract"]["access_mode"] == "read"


def test_deterministic_worker_gets_runtime_completion_report_without_legacy_fallback() -> None:
    directory = AgentDirectory()
    contract = directory.get("W02").task_contract("query_stock_prediction")
    task = GraphAgentTask(
        task_id="T02",
        run_id="run-v18",
        session_id="session-v18",
        user_id="cht",
        worker_id="W02",
        assigned_agent=directory.get("W02").agent_id,
        objective="查询模型预测",
        task_type="query_stock_prediction",
        args={"top_k": 10, "focus_ref_ids": ["cn:security:sse:600519"]},
        inputs={},
        expected_output_type="ModelPredictionResult",
        expected_output={"information_slots": ["entity_model_signals"]},
        completion_criteria=list(contract.completion_criteria),
    )
    task.completion_contract = directory.completion_contract_for_task(task)
    report = runtime_completion_report(
        task,
        contract,
        result_status=ResultStatus.COMPLETED,
        output_type="ModelPredictionResult",
        data={"found": True},
        error=None,
    )
    assert report["report_source"] == "runtime"
    assert report["completion_status"] == "completed"
    assert report["produced_information_slots"] == ["entity_model_signals"]
    coordinator_source = inspect.getsource(AgentCollaborationCoordinator)
    assert "legacy_non_llm_worker_declared_completed" not in coordinator_source


def test_context_binding_prevents_previous_security_focus_for_portfolio_scope() -> None:
    class FakeLLM:
        def generate_json(self, **kwargs):
            payload = {
                "mode": "analysis",
                "reason": "当前目标是完整组合",
                "reply_language": "zh",
                "confidence": 1.0,
                "context_binding": {
                    "entity_scope": "portfolio",
                    "inherit_previous_focus": False,
                    "reason": "完整组合不继承上一轮单一证券",
                },
            }
            kwargs["validator"](payload)
            return payload

    decision = MainEntryDecisionPlanner(llm_service=FakeLLM()).decide(
        query="查看当前模拟盘账户和持仓",
        memory_summary="上一轮分析了某证券",
        execution_context={},
        language="zh",
    )
    assert decision.context_binding.entity_scope == EntityScope.PORTFOLIO
    assert decision.context_binding.inherit_previous_focus is False

    coordinator = AgentCollaborationCoordinator.__new__(AgentCollaborationCoordinator)
    coordinator._extract_mentions = lambda query, language: []
    inherited = [
        GraphRef(
            graph_id="financial_graph",
            node_id="cn:security:sse:600519",
            node_kind=GraphNodeKind.OBJECT,
            role="focus",
            locked=True,
        )
    ]
    focus, missing, audit = coordinator._resolve_request_refs(
        query="查看当前模拟盘账户和持仓",
        inherited_refs=inherited,
        context_refs=[],
        as_of_time="",
        language="zh",
        context_binding=decision.context_binding.to_dict(),
    )
    assert focus == []
    assert missing == []
    assert audit["context_binding"]["entity_scope"] == "portfolio"


def test_report_authority_is_compiled_from_direct_portfolio_results() -> None:
    raw_result = {
        "task_id": "T02",
        "status": "completed",
        "output_type": "PortfolioAnalysisResult",
        "payload": {
            "display_positions": [
                {"security_code": "000001", "security_name": "平安银行"},
                {"security_code": "600519", "security_name": "贵州茅台"},
            ],
            "entity_catalog": [
                {"security_code": "000001", "security_name": "平安银行"},
                {"security_code": "600519", "security_name": "贵州茅台"},
            ],
        },
    }
    goal = {
        "required_information_slots": [
            "account_financial_state", "current_portfolio_state",
            "portfolio_positions", "authoritative_holding_entities",
        ],
        "desired_output_types": ["AccountStateResult", "PortfolioAnalysisResult", "FinalReport"],
    }
    policy = build_report_policy(
        "查看当前模拟盘账户和持仓",
        [raw_result],
        request_mode="analysis",
        goal_contract=goal,
        authority_results=[raw_result],
    )
    assert policy.view_only is True
    assert set(policy.entity_map) == {"000001", "600519"}


def test_w04_is_hybrid_llm_worker_with_private_atomic_read_tools() -> None:
    card = AgentDirectory().get("W04")
    assert card.task_contract("analyze_risk").completion_report_source == "llm"
    tools = set(card.private_tools_for("analyze_risk"))
    assert tools == {
        "risk.calculate_concentration",
        "risk.read_account_risk_facts",
        "risk.summarize_exposure",
        "risk.finalize_facts",
    }
    assert all("write" not in name for name in tools)


def test_w05_proposal_is_run_local_and_does_not_call_legacy_persistent_tool() -> None:
    source = inspect.getsource(strategy_guard)
    assert "execute_tool_legacy_dict" not in source
    assert '"scope": "current_run_only"' in source
    assert '"persistent_write_performed": False' in source
    assert '"execution_allowed": False' in source


def test_report_writer_uses_sectioned_markdown_and_terminal_results() -> None:
    source = inspect.getsource(report_writer)
    assert "source_claim_ids" in source
    assert "report_section_unknown_source_claim_id" in source
    assert "terminal_worker_results" in source
    assert "sectioned_markdown_report.v1" in source
    assert "raw_evidence_result_count" in source
    assert '"claims": array_schema' not in source


def test_wrapped_local_output_repair_failure_keeps_contract_failure_classification() -> None:
    violation = WorkerContractViolation(
        "report_output_validation_failed",
        "$.content",
        "unsupported_entity_code",
    )
    try:
        try:
            raise violation
        except WorkerContractViolation as inner:
            raise RuntimeError("LLM JSON/schema repair failed") from inner
    except RuntimeError as wrapped:
        assert _contract_violation_from_chain(wrapped) is violation

    coordinator_source = inspect.getsource(AgentCollaborationCoordinator)
    assert "worker_output_contract_failure" in coordinator_source


def test_report_writer_prompt_has_one_structured_report_policy_payload() -> None:
    source = inspect.getsource(report_writer)
    assert '"report_policy": policy.to_prompt_dict(),\n                        "report_policy"' not in source


def test_runtime_build_marker_exposes_v18_contract_versions() -> None:
    assert collaboration_integration.RUNTIME_BUILD == "V18.1"
    assert collaboration_integration.ACCESS_MODEL_VERSION == "read-write.v1"
    assert collaboration_integration.COMPLETION_CONTRACT_VERSION == "worker-completion-contract.v1"
    assert collaboration_integration.COMPLETION_REPORT_VERSION == "worker-completion-report.v1"
    assert collaboration_integration.EVIDENCE_ANALYSIS_REPORT_VERSION == "evidence-analysis-report.v1"


def test_current_baseline_graph_context_and_entry_examples_are_preserved() -> None:
    from agent.worker_tools import registry as worker_registry
    from agent.collaboration import entry_decision

    registry_source = inspect.getsource(worker_registry)
    assert "build_graph_context_tool_definitions" in registry_source
    assert "build_risk_tool_definitions" in registry_source

    entry_source = inspect.getsource(entry_decision.MainEntryDecisionPlanner)
    assert "你认为我的持仓应该怎么调整" in entry_source
    assert "分析我的持仓有什么风险" in entry_source

