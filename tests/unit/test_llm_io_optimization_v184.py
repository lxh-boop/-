from __future__ import annotations

import copy
import inspect
import json
import os

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.planner import (
    PLAN_SCHEMA,
    PLANNER_CONTRACT_EXAMPLES,
    CoordinatorPlanner,
)
from agent.collaboration.report_validation import (
    build_report_policy,
    validate_report_output,
)
from agent.collaboration.workers import report_writer
from core.llm.prompt_compaction import (
    catalog_for_prompt,
    compact_json_dumps,
    coordinator_result_for_replan,
    observation_for_replan,
    plan_schema_for_prompt,
    planning_catalog_for_prompt,
)


class _CaptureLLM:
    def __init__(self) -> None:
        self.kwargs: dict = {}

    def generate_json(self, **kwargs):
        self.kwargs = kwargs
        raise RuntimeError("capture")


def _capture_plan(request_mode: str) -> dict:
    llm = _CaptureLLM()
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=llm)
    previous_trace = os.environ.get("AGENT_FLOW_TRACE")
    os.environ["AGENT_FLOW_TRACE"] = "0"
    try:
        try:
            planner.plan(
                query=(
                    "查看当前模拟盘账户和持仓"
                    if request_mode == "analysis"
                    else "你认为我的持仓应该怎么修改"
                ),
                request_mode=request_mode,
                session_id="session-test",
                run_id="run-test",
                user_id="cht",
                focus_refs=[],
                context_refs=[],
                memory_summary="recent context",
                language="zh",
            )
        except RuntimeError as exc:
            assert str(exc) == "capture"
    finally:
        if previous_trace is None:
            os.environ.pop("AGENT_FLOW_TRACE", None)
        else:
            os.environ["AGENT_FLOW_TRACE"] = previous_trace
    return llm.kwargs


def _original_role_contract(role_schema: dict, *, required: bool) -> dict:
    output_types: list[str] = []
    supports_one = False
    supports_many = False
    max_results = 1
    for branch in role_schema.get("anyOf") or []:
        if branch.get("type") == "object":
            supports_one = True
            ref = branch
        elif branch.get("type") == "array":
            supports_many = True
            max_results = max(max_results, int(branch.get("maxItems") or 1))
            ref = branch.get("items") or {}
        else:
            raise AssertionError("unexpected semantic input schema")
        output_schema = (
            (ref.get("properties") or {}).get("expected_output_type", {})
        )
        enum_values = list(output_schema.get("enum") or [])
        output_types.extend(
            enum_values
            if enum_values
            else ["*"]
            if output_schema.get("type") == "string"
            else []
        )
    return {
        "allowed_output_types": list(dict.fromkeys(output_types)),
        "required": required,
        "cardinality": (
            "one_or_many"
            if supports_one and supports_many
            else "many"
            if supports_many
            else "one"
        ),
        "min_results": 1 if required else 0,
        "max_results": max_results,
    }


def test_planning_catalog_compaction_preserves_every_legal_task_contract() -> None:
    directory = AgentDirectory()
    full = directory.planning_catalog()

    for mode in ("analysis", "proposal"):
        compact = planning_catalog_for_prompt(full, request_mode=mode)
        compact_by_key = {
            (worker["worker_id"], task["task_type"]): task
            for worker in compact
            for task in worker["task_contracts"]
        }
        expected_keys = set()
        for worker in full:
            if str(worker.get("access_mode") or "read") == "write":
                continue
            for task in worker.get("task_contracts") or []:
                modes = set(task.get("allowed_request_modes") or [])
                if modes and mode not in modes:
                    continue
                if str(task.get("access_mode") or "read") == "write":
                    continue
                key = (worker["worker_id"], task["task_type"])
                expected_keys.add(key)
                prompt_task = compact_by_key[key]
                for field in (
                    "output_type",
                    "completion_criteria",
                    "selection_requirements",
                    "consumes_information_slots",
                    "produces_information_slots",
                    "required_context_slots",
                    "coverage_semantics",
                    "freshness_semantics",
                    "authority_level",
                    "allowed_request_modes",
                    "access_mode",
                    "required_upstream_output_groups",
                ):
                    assert prompt_task[field] == task[field]
                original_semantic = task["semantic_inputs_schema"]
                required_roles = set(original_semantic.get("required") or [])
                prompt_roles = prompt_task["semantic_inputs_schema"]
                assert prompt_roles["required_roles"] == list(
                    original_semantic.get("required") or []
                )
                for role, role_schema in (
                    original_semantic.get("properties") or {}
                ).items():
                    assert prompt_roles["roles"][role] == _original_role_contract(
                        role_schema,
                        required=role in required_roles,
                    )
        assert set(compact_by_key) == expected_keys


def test_planning_catalog_reduces_mainagent_catalog_by_more_than_35_percent() -> None:
    directory = AgentDirectory()
    full_prompt = catalog_for_prompt(directory.planning_catalog())
    full_chars = len(compact_json_dumps(full_prompt))

    analysis_chars = len(
        compact_json_dumps(
            planning_catalog_for_prompt(
                directory.planning_catalog(), request_mode="analysis"
            )
        )
    )
    proposal_chars = len(
        compact_json_dumps(
            planning_catalog_for_prompt(
                directory.planning_catalog(), request_mode="proposal"
            )
        )
    )

    assert analysis_chars < full_chars * 0.60
    assert proposal_chars < full_chars * 0.65


def test_prompt_plan_schema_omits_only_code_owned_fields() -> None:
    original = copy.deepcopy(PLAN_SCHEMA)
    prompt_schema = plan_schema_for_prompt(PLAN_SCHEMA)

    assert PLAN_SCHEMA == original
    goal = prompt_schema["properties"]["goal_contract"]
    assert "access_mode" not in goal["properties"]
    planning = prompt_schema["properties"]["planning_state"]
    assert planning["required"] == ["stop_reason"]
    assert set(planning["properties"]) == {"stop_reason"}
    input_contract = prompt_schema["properties"]["tasks"]["items"]["properties"][
        "input_contract"
    ]
    assert input_contract["maxProperties"] == 0
    assert input_contract["additionalProperties"] is False


def test_mainagent_primary_prompt_is_below_50000_chars_for_both_modes() -> None:
    for mode in ("analysis", "proposal"):
        kwargs = _capture_plan(mode)
        prompt_chars = sum(len(item["content"]) for item in kwargs["messages"])
        assert prompt_chars < 50000


def test_targeted_repair_context_is_below_26000_chars() -> None:
    for mode in ("analysis", "proposal"):
        kwargs = _capture_plan(mode)
        builder = kwargs["repair_context_builder"]
        repair_messages = builder({}, {"contract_code": "test"})
        repair_chars = sum(len(item["content"]) for item in repair_messages)
        assert repair_chars < 26000


def test_planner_example_places_portfolio_risk_in_risk_constraints_role() -> None:
    inputs = PLANNER_CONTRACT_EXAMPLES["multiple_upstream_inputs"]["inputs"]
    assert inputs["risk_constraints"]["expected_output_type"] == "PortfolioRiskResult"
    supporting_types = {
        row["expected_output_type"] for row in inputs["supporting_analysis"]
    }
    assert "PortfolioRiskResult" not in supporting_types


def test_replan_views_preserve_decision_facts_and_drop_business_payloads() -> None:
    result = {
        "task_id": "T01",
        "agent_id": "PORTFOLIO_ANALYST",
        "status": "completed",
        "output_type": "PortfolioAnalysisResult",
        "summary": "portfolio loaded",
        "confidence": 1.0,
        "payload": {"display_positions": [{"blob": "x" * 20000}]},
        "data": {"display_positions": [{"blob": "x" * 20000}]},
        "findings": [{"blob": "x" * 10000}],
        "completion": {
            "execution_status": "succeeded",
            "contract_status": "valid",
            "business_status": "sufficient",
            "completion_status": "completed",
            "expected_task_completed": True,
            "produced_information_slots": ["current_portfolio_state"],
            "missing_information_slots": [],
            "criteria": [{"reason": "x" * 5000}],
        },
        "warnings": [],
    }
    observation = {
        "task_id": "T06",
        "worker_id": "W06",
        "task_type": "write_report",
        "expected_output_type": "FinalReport",
        "actual_output_type": "FinalReport",
        "status": "failed",
        "contract_valid": True,
        "completion_report_valid": True,
        "semantic_satisfied": False,
        "produced_information_slots": [],
        "missing_information_slots": ["user_facing_report"],
        "failure_kind": "worker_execution_failure",
        "retryable": True,
        "repairable": True,
        "replan_recommended": True,
        "reusable": False,
        "freeze_reason": "retryable_failure_requires_replan",
        "error": {
            "code": "report_llm_generation_failed",
            "message": "x" * 5000,
            "component": "REPORT_WRITER",
            "retryable": True,
        },
        "completion": {"criteria": [{"reason": "y" * 20000}]},
        "replan_triggers": ["missing output"],
    }

    compact_result = coordinator_result_for_replan(result)
    compact_observation = observation_for_replan(observation)

    assert compact_result["produced_information_slots"] == [
        "current_portfolio_state"
    ]
    assert compact_result["expected_task_completed"] is True
    assert "payload" not in compact_result
    assert "data" not in compact_result
    assert "completion" not in compact_observation
    assert compact_observation["error"]["code"] == "report_llm_generation_failed"
    full_chars = len(compact_json_dumps([result, observation]))
    compact_chars = len(
        compact_json_dumps([compact_result, compact_observation])
    )
    assert compact_chars < full_chars * 0.10


def test_cash_management_proposal_does_not_require_unrequested_risk_worker() -> None:
    safe_results = [
        {"status": "proposal_ready", "output_type": "ReviewedProposal"},
        {"status": "completed", "output_type": "AccountStateResult"},
        {"status": "completed", "output_type": "PortfolioAnalysisResult"},
    ]
    policy = build_report_policy(
        "说明多余现金如何处理",
        safe_results,
        request_mode="proposal",
        goal_contract={
            "desired_output_types": ["ReviewedProposal", "FinalReport"],
            "required_information_slots": [
                "account_financial_state",
                "current_portfolio_state",
                "reviewed_proposal",
                "user_facing_report",
            ],
        },
    )
    assert policy.adjustment_requested is True
    assert policy.risk_requested is False
    result = validate_report_output("现金处理建议已形成，方案待审批且尚未执行。", policy)
    assert all(
        issue.code != "missing_required_risk_worker_output"
        for issue in result.issues
    )


def test_risk_required_goal_still_requires_portfolio_risk_result() -> None:
    safe_results = [
        {"status": "proposal_ready", "output_type": "ReviewedProposal"},
        {"status": "completed", "output_type": "PortfolioAnalysisResult"},
    ]
    policy = build_report_policy(
        "根据风险评估调整持仓",
        safe_results,
        request_mode="proposal",
        goal_contract={
            "desired_output_types": ["ReviewedProposal", "FinalReport"],
            "required_information_slots": [
                "portfolio_risk_assessment",
                "reviewed_proposal",
                "user_facing_report",
            ],
        },
    )
    assert policy.risk_requested is True
    result = validate_report_output("调仓方案待审批且尚未执行。", policy)
    assert any(
        issue.code == "missing_required_risk_worker_output"
        for issue in result.issues
    )


def test_no_llm_stage_removed_by_v184() -> None:
    source = inspect.getsource(CoordinatorPlanner.plan)
    replan_source = inspect.getsource(CoordinatorPlanner.replan_forward)
    report_source = inspect.getsource(report_writer.run_report_writer)
    assert "generate_json" in source
    assert "generate_json" in replan_source
    assert "generate_json" in report_source
